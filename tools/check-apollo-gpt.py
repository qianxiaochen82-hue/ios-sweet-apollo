#!/usr/bin/env python3
"""Verify the apollo GPT dumps captured under apollo-backup/ (read-only).

    python tools/check-apollo-gpt.py apollo-backup [--image-size 24G]

Each `<lun>_gpt_{primary,backup}_34x4096.bin` is a 34 x 4096 snapshot of the
GPT header plus the entry array.  This checks the two copies against each
other and against the spec, then reports whether a root-volume image fits in
userdata.  Nothing here touches a device.
"""
import argparse
import os
import struct
import sys
import uuid
import zlib

SIG = b'EFI PART'
CHUNK = 4096


def find_header(buf):
    i = buf.find(SIG)
    if i < 0:
        return None
    # header starts at a chunk boundary
    off = (i // CHUNK) * CHUNK
    return off


def parse_header(buf, off):
    h = buf[off:off + 92]
    (rev, hsize, hcrc, _res, my, alt, first, last, guid,
     ent_lba, nent, esize, ecrc) = struct.unpack('<IIIIQQQQ16sQIII', h[8:92])
    hcrc_calc = zlib.crc32(h[:16] + b'\x00' * 4 + h[20:hsize]) & 0xFFFFFFFF
    return dict(off=off, rev=rev, hsize=hsize, hcrc=hcrc, hcrc_ok=hcrc_calc == hcrc,
                my=my, alt=alt, first=first, last=last,
                guid=str(uuid.UUID(bytes_le=guid)),
                ent_lba=ent_lba, nent=nent, esize=esize, ecrc=ecrc)


def entries(buf, hdr):
    base = hdr['off'] + (hdr['ent_lba'] - hdr['my']) * CHUNK
    need = hdr['nent'] * hdr['esize']
    if base < 0 or base + need > len(buf):
        return None
    raw = buf[base:base + need]
    ecrc_calc = zlib.crc32(raw) & 0xFFFFFFFF
    out = []
    for k in range(hdr['nent']):
        e = raw[k * hdr['esize']:(k + 1) * hdr['esize']]
        tg = e[:16]
        if tg == b'\x00' * 16:
            continue
        first, last, attr = struct.unpack('<QQQ', e[32:56])
        name = e[56:128].decode('utf-16-le', 'replace').split('\x00')[0]
        out.append(dict(name=name, first=first, last=last, attr=attr,
                        guid=str(uuid.UUID(bytes_le=tg))))
    return out, ecrc_calc


def size_bytes(s):
    mult = dict(K=1024, M=1024 ** 2, G=1024 ** 3, T=1024 ** 4)
    if s and s[-1].upper() in mult:
        return int(float(s[:-1]) * mult[s[-1].upper()])
    return int(s)


def check_lun(d, lun, image_size):
    p = os.path.join(d, f'{lun}_gpt_primary_34x4096.bin')
    b = os.path.join(d, f'{lun}_gpt_backup_34x4096.bin')
    if not (os.path.exists(p) and os.path.exists(b)):
        return None
    pb, bb = open(p, 'rb').read(), open(b, 'rb').read()
    ph, bh = find_header(pb), find_header(bb)
    bad = []
    if ph is None or bh is None:
        return dict(lun=lun, bad=['signature missing'], parts=[])
    ph, bh = parse_header(pb, ph), parse_header(bb, bh)
    pe = entries(pb, ph)
    be = entries(bb, bh)
    if not ph['hcrc_ok']:
        bad.append('primary header CRC')
    if not bh['hcrc_ok']:
        bad.append('backup header CRC')
    if pe is None or pe[1] != ph['ecrc']:
        bad.append('primary entry CRC')
    if be is None or be[1] != bh['ecrc']:
        bad.append('backup entry CRC')
    if ph['alt'] != bh['my']:
        bad.append(f"primary altLBA {ph['alt']} != backup myLBA {bh['my']}")
    if bh['alt'] != ph['my']:
        bad.append(f"backup altLBA {bh['alt']} != primary myLBA {ph['my']}")
    if ph['first'] != bh['first'] or ph['last'] != bh['last']:
        bad.append('usable range differs between copies')
    if ph['nent'] != bh['nent'] or ph['esize'] != bh['esize']:
        bad.append('entry geometry differs between copies')
    if pe and be and [(x['name'], x['first'], x['last'], x['guid']) for x in pe[0]] != \
            [(x['name'], x['first'], x['last'], x['guid']) for x in be[0]]:
        bad.append('partition tables differ between copies')
    parts = pe[0] if pe else []
    first, last = ph['first'], ph['last']
    for part in parts:
        if part['first'] < first or part['last'] > last:
            bad.append(f"{part['name']} outside usable range")
    parts = sorted(parts, key=lambda x: x['first'])
    for a, c in zip(parts, parts[1:]):
        if a['last'] >= c['first']:
            bad.append(f"overlap {a['name']} / {c['name']}")
    return dict(lun=lun, bad=bad, parts=parts, hdr=ph,
                backup_ok=not [x for x in bad if 'backup' in x])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir', nargs='?', default='apollo-backup')
    ap.add_argument('--image-size', default=None)
    a = ap.parse_args()
    img = size_bytes(a.image_size) if a.image_size else None
    fails = 0
    for lun in ['sda', 'sdb', 'sdc', 'sdd', 'sde', 'sdf']:
        r = check_lun(a.dir, lun, img)
        if r is None:
            continue
        hdr = r['hdr']
        state = 'OK' if not r['bad'] else 'FAIL'
        print(f"{lun}: {state} primary={hdr['my']} backup={hdr['alt']} "
              f"usable={hdr['first']}..{hdr['last']} parts={len(r['parts'])}")
        for x in r['bad']:
            print('   !', x)
        fails += bool(r['bad'])
        if lun != 'sda' or not r['parts']:
            continue
        ud = [p for p in r['parts'] if p['name'] == 'userdata']
        if not ud:
            print('   ! userdata not found')
            fails += 1
            continue
        u = ud[0]
        n = u['last'] - u['first'] + 1
        print(f"   userdata LBA4k {u['first']}..{u['last']} = {n} x 4 KiB "
              f"= {n * 4096 / 2**30:.2f} GiB ({n * 8} x 512 B)")
        if u['first'] % 1 or (u['last'] + 1) % 1:
            print('   ! userdata not 4 KiB aligned')
            fails += 1
        if img:
            blocks = (img + 4095) // 4096
            ok = blocks <= n
            print(f"   image {img / 2**30:.2f} GiB = {blocks} x 4 KiB "
                  f"-> {'fits' if ok else 'TOO BIG'}")
            fails += 0 if ok else 1
    print('\nRESULT:', 'all checks passed' if not fails else f'{fails} problem(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
