#!/usr/bin/env python3
"""Rewrite a boot-args token in a SWEETXNU payload without touching anything else.

    python tools/patchpayload.py --in payload/known-good.bin \
        --out payload/known-good-cpus8.bin --set cpus=8

The payload header keeps the command line in a fixed 608-byte field at 0x48
(loader.c copies it verbatim into boot_args), so an equal-length edit is a
single-point change and trivially reversible: keep the source payload around.
"""
import argparse
import struct
import sys

MAGIC = b"SWEETXNU"
CMDLINE_OFF = 0x48
CMDLINE_LEN = 608


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--set", dest="kv", action="append", required=True,
                    metavar="KEY=VALUE")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    data = bytearray(open(a.src, "rb").read())
    if data[:8] != MAGIC:
        sys.exit("%s: not a SWEETXNU payload" % a.src)

    raw = bytes(data[CMDLINE_OFF:CMDLINE_OFF + CMDLINE_LEN])
    old = raw.split(b"\0")[0].decode()
    if a.show:
        print("before: %s" % old)

    toks = old.split()
    for kv in a.kv:
        k, _, v = kv.partition("=")
        if not _:
            sys.exit("--set wants KEY=VALUE, got %r" % kv)
        for i, t in enumerate(toks):
            if t == k or t.startswith(k + "="):
                toks[i] = "%s=%s" % (k, v)
                break
        else:
            toks.append("%s=%s" % (k, v))

    new = " ".join(toks)
    enc = new.encode()
    if len(enc) >= CMDLINE_LEN:
        sys.exit("command line too long: %d >= %d" % (len(enc), CMDLINE_LEN))

    data[CMDLINE_OFF:CMDLINE_OFF + CMDLINE_LEN] = enc + b"\0" * (CMDLINE_LEN - len(enc))

    # Only the command line may change; anything else means a corrupt payload.
    orig = open(a.src, "rb").read()
    if len(orig) != len(data):
        sys.exit("size changed: %d != %d" % (len(orig), len(data)))
    diff = [i for i in range(len(orig))
            if orig[i] != data[i] and not (CMDLINE_OFF <= i < CMDLINE_OFF + CMDLINE_LEN)]
    if diff:
        sys.exit("bytes outside the command line changed: %r" % diff[:8])

    open(a.dst, "wb").write(data)
    print("after:  %s" % new)
    print("wrote   %s (%d bytes, %d byte(s) changed)"
          % (a.dst, len(data), sum(1 for i in range(len(orig)) if orig[i] != data[i])))
    # Sanity: the header must still describe the same kernel.
    print("header  version=%d nsegs=%d phys=%#x mem=%#x adt=%#x/%#x" % (
        struct.unpack_from("<I", data, 8)[0], struct.unpack_from("<I", data, 12)[0],
        struct.unpack_from("<Q", data, 56)[0], struct.unpack_from("<Q", data, 64)[0],
        struct.unpack_from("<Q", data, 32)[0], struct.unpack_from("<Q", data, 40)[0]))


if __name__ == "__main__":
    main()
