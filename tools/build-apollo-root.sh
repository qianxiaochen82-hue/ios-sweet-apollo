#!/bin/bash
# Build the apollo iOS root volume (24 GiB HFS+ on userdata) from the three
# images unpacked out of
#   iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw   (16.7.16 / 20H392)
#
# MUST run on Linux: needs apfs-fuse (reads the LZBITMAP-compressed APFS
# images through FUSE), hfsprogs (mkfs.hfsplus / fsck.hfsplus) and rsync.
# The Windows box only unpacks the IPSW; nothing here touches the phone.
#
#   build-apollo-root.sh [IPSW_DIR] [OUT.img] [SIZE]
#
# Defaults: ~/apollo-ipsw, ~/apollo-root-24g.img, 24G.  Override with the
# three arguments or IPSW_DIR / OUT / SIZE.  Everything is pre-flighted:
# hashes, volume names, the dyld shared-cache path mkiosroot.sh hard-links
# from, then the build, then the post-build checks from the NOTES checklist.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
ipsw_dir=${1:-${IPSW_DIR:-$HOME/apollo-ipsw}}
out=${2:-${OUT:-$HOME/apollo-root-24g.img}}
size=${3:-${SIZE:-24G}}
os=$ipsw_dir/OS.dmg sysos=$ipsw_dir/SYSTEMOS.dmg appos=$ipsw_dir/APPOS.dmg

# sha256 of the images as extracted from the 20H392 restore IPSW.
# (OS is UDIF+LZVN, SYSTEMOS/APPOS are raw APFS containers.)
known_os=80f426d5b8fca8552f95be427434f1911dbb4c2c6d28aad94f2426ddd0c92483
known_sysos=9cd738f3b0169055549df84ad6d8d13e50a2da39af618ce0522ca4e06df86849
known_appos=391f2df322c3172b021b2874f6da5c3e78b70b3df8f502e1a4af2b1d715c4608

die() { echo "error: $*" >&2; exit 1; }

for t in apfs-fuse mkfs.hfsplus fsck.hfsplus rsync sha256sum; do
	command -v "$t" >/dev/null || die "missing host tool $t (apt install apfs-fuse hfsprogs rsync)"
done
for f in "$os" "$sysos" "$appos"; do
	[[ -f $f ]] || die "missing $f"
done
[[ ! -e $out ]] || die "refusing to overwrite $out"

echo "== 1. input hashes"
check() {
	local got; got=$(sha256sum "$1" | cut -d' ' -f1)
	[[ $got == "$2" ]] || die "$(basename "$1"): sha256 $got != $2"
	printf '   ok %-12s %s\n' "$(basename "$1")" "$got"
}
check "$os" "$known_os"
check "$sysos" "$known_sysos"
check "$appos" "$known_appos"

# Volume names matter twice: apfs-fuse mounts a container as one directory per
# volume, and mkiosroot.sh copies from $mount/root, i.e. it requires the OS
# volume to be called "root".
echo "== 2. APFS volumes"
for f in "$os" "$sysos" "$appos"; do
	echo "   -- $(basename "$f")"
	sudo apfs-fuse -l "$f" 2>/dev/null | sed 's/^/      /'
done

# The volume names apfs-fuse reports must include "root" for every image.
names_root=$(sudo apfs-fuse -l "$os" 2>/dev/null | tr -d '\r')
for f in "$sysos" "$appos"; do
	names_root+=$'\n'$(sudo apfs-fuse -l "$f" 2>/dev/null | tr -d '\r')
done

work=$(mktemp -d)
mounted=()
cleanup() {
	local m
	for m in "${mounted[@]}"; do
		mountpoint -q "$m" && sudo umount "$m" 2>/dev/null
	done
	rm -f "$work"/*.dmg
	rmdir "$work"/* "$work" 2>/dev/null || true
}
trap cleanup EXIT
mnt() { # mnt <image> <tag>
	ln -s "$1" "$work/$2.dmg"
	mkdir -p "$work/$2"
	sudo apfs-fuse "$work/$2.dmg" "$work/$2"
	mounted+=("$work/$2")
}
mnt "$os" os
mnt "$sysos" sysos
mnt "$appos" appos

echo "== 3. mount roots (mkiosroot.sh copies <mount>/root)"
for t in os sysos appos; do
	printf '   %-6s %s\n' "$t" "$(ls -m "$work/$t" 2>/dev/null || echo '(empty)')"
	[[ -d $work/$t/root ]] || die "$t volume is not named 'root' (see the listing above)"
done

# Where the dyld shared cache actually lives.  iOS 16 split it into
# dyld_shared_cache_arm64 + .01..N subcaches inside the SystemOS cryptex.
# A11 (iPhone10,3/10,6) is arm64, not arm64e - there is no *_arm64e file.
echo "== 4. dyld shared cache"
dsc_rel=System/Library/Caches/com.apple.dyld   # what mkiosroot.sh hard-links
dsc=$work/sysos/root/$dsc_rel
if [[ -d $dsc ]]; then
	echo "   found $dsc_rel ($(ls "$dsc" | wc -l) entries)"
	ls -lh "$dsc" | sed -n '1,6p;$p' | sed 's/^/      /'
	[[ -f $dsc/dyld_shared_cache_arm64 ]] ||
		die "$dsc_rel has no dyld_shared_cache_arm64"
	[[ -e $dsc/dyld_shared_cache_arm64e ]] &&
		echo "   note: an arm64e cache is present as well"
else
	echo "   MISSING $dsc_rel - looking for the cache elsewhere:" >&2
	sudo find "$work/sysos" -name 'dyld_shared_cache*' -maxdepth 12 2>/dev/null |
		sed 's/^/      /' >&2 || true
	die "mkiosroot.sh expects $dsc_rel; fix the dsc= line before building"
fi
# The OS root must NOT carry its own copy, or the hard links would be skipped.
if [[ -d $work/os/root/$dsc_rel ]]; then
	echo "   note: the OS root already has $dsc_rel ($(ls "$work/os/root/$dsc_rel" | wc -l) entries)"
fi
for t in os sysos appos; do
	du -sh "$work/$t/root" 2>/dev/null | sed 's/^/   /'
done

cleanup
trap - EXIT

echo "== 5. build ($size, HFS_BLOCK=4096)"
HFS_BLOCK=4096 "$here/mkiosroot.sh" "$os" "$sysos" "$appos" "$out" "$size"

echo "== 6. post-build checks"
fsck.hfsplus -n "$out" | sed 's/^/   /'
python3 - "$out" <<'PY'
import os, struct, sys
p = sys.argv[1]
with open(p, 'rb') as f:
    f.seek(1024)
    h = f.read(512)
sig, ver, attr = struct.unpack_from('>HHI', h, 0)
bs, total, free = struct.unpack_from('>III', h, 40)
journaled = bool(attr & 0x2000)
print("   sig=%s version=%d journaled=%s case-sensitive=%s block=%d total=%d MiB free=%d MiB" % (
    sig.decode('latin-1'), ver, journaled, sig == b'HX', bs,
    total * bs >> 20, free * bs >> 20))
ok = sig == b'HX' and ver == 5 and journaled and bs == 4096
print("   %s" % ("volume header ok" if ok else "VOLUME HEADER MISMATCH"))
sys.exit(0 if ok else 1)
PY
sz=$(stat -c %s "$out")
printf '   size=%d (%.2f GiB) 4K-aligned=%d\n' "$sz" \
	"$(awk "BEGIN{print $sz/1073741824}")" "$(( sz % 4096 == 0 ))"
echo "   sha256 $(sha256sum "$out" | cut -d' ' -f1)"
echo "   copy to the phone host, then flash userdata only (not before the user says go)"
