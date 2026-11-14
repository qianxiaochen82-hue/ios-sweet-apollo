#!/usr/bin/env python3
"""Pack an Android boot image (header v2, 4096-byte pages) without mkbootimg.

apollo's stock boot is header v2 (kernel_addr 0x8000, ramdisk_addr 0x1000000,
tags 0x100, dtb 0x1f00000), so we mirror it instead of the v4 that topaz needs.
The shim payload rides behind the kernel Image (see shim/build.ps1).
"""
import argparse
import os
import struct

PAGE = 4096
BOOT_MAGIC = b"ANDROID!"


def pad(b, page=PAGE):
    return b + b"\0" * ((-len(b)) % page)


def os_version(v, patch):
    # "17.0.0" + "2035-06" -> (17<<25)|(0<<18)|(0<<11)|(35<<4)|6
    a, b, c = (int(x) for x in v.split("."))
    return (a << 25) | (b << 18) | (c << 11) | os_patch(patch)


def os_patch(s):
    y, m = (int(x) for x in s.split("-"))
    return ((y - 2000) << 4) | m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", required=True)
    ap.add_argument("--dtb")
    ap.add_argument("--cmdline", default="")
    ap.add_argument("--base", default="0")
    ap.add_argument("--kernel_offset", default="0x8000")
    ap.add_argument("--ramdisk_offset", default="0x1000000")
    ap.add_argument("--tags_offset", default="0x100")
    ap.add_argument("--dtb_offset", default="0x1f00000")
    ap.add_argument("--os_version", default="17.0.0")
    ap.add_argument("--os_patch_level", default="2035-06")
    ap.add_argument("--header_version", type=int, default=2)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    kernel = open(a.kernel, "rb").read()
    ramdisk = open(a.ramdisk, "rb").read()
    dtb = open(a.dtb, "rb").read() if a.dtb else b""
    base = int(a.base, 0)

    hdr = bytearray(1660)
    hdr[0:8] = BOOT_MAGIC
    struct.pack_into("<I", hdr, 8, len(kernel))
    struct.pack_into("<I", hdr, 12, base + int(a.kernel_offset, 0))
    struct.pack_into("<I", hdr, 16, len(ramdisk))
    struct.pack_into("<I", hdr, 20, base + int(a.ramdisk_offset, 0))
    struct.pack_into("<I", hdr, 24, 0)                      # second_size
    struct.pack_into("<I", hdr, 28, 0)                      # second_addr
    struct.pack_into("<I", hdr, 32, base + int(a.tags_offset, 0))
    struct.pack_into("<I", hdr, 36, PAGE)                   # page_size
    struct.pack_into("<I", hdr, 40, a.header_version)
    struct.pack_into("<I", hdr, 44, os_version(a.os_version, a.os_patch_level))
    hdr[48:64] = b"\0" * 16                                 # name
    cmd = a.cmdline.encode()
    assert len(cmd) < 512
    hdr[64:64 + len(cmd)] = cmd
    struct.pack_into("<I", hdr, 1632, 0)                    # recovery_dtbo_size
    struct.pack_into("<Q", hdr, 1636, 0)                    # recovery_dtbo_offset
    struct.pack_into("<I", hdr, 1644, len(hdr))             # header_size
    struct.pack_into("<I", hdr, 1648, len(dtb))             # dtb_size
    struct.pack_into("<Q", hdr, 1652, base + int(a.dtb_offset, 0))

    out = pad(bytes(hdr)) + pad(kernel) + pad(ramdisk) + pad(dtb)
    with open(a.output, "wb") as f:
        f.write(out)

    print("kernel   %#x (%d)" % (len(kernel), len(kernel)))
    print("ramdisk  %#x (%d)" % (len(ramdisk), len(ramdisk)))
    print("dtb      %#x (%d)" % (len(dtb), len(dtb)))
    print("image    %#x (%d)  %.1f MiB" % (len(out), len(out), len(out) / 1048576.0))
    print("header   version=%d os=%#x patch=%#x" % (a.header_version,
          os_version(a.os_version, a.os_patch_level), os_patch(a.os_patch_level)))
    assert len(out) <= 128 * 1024 * 1024, "boot image exceeds the 128 MiB cap"


if __name__ == "__main__":
    main()
