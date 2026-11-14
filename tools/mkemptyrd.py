#!/usr/bin/env python3
"""Write an empty newc cpio (gzip -9), the ramdisk a boot image needs when the
payload rides behind the kernel instead of in the ramdisk."""
import gzip
import sys

hdr = b"070701" + b"0" * 8                     # ino
hdr += b"0" * 8 + b"0" * 8                     # mode, uid
hdr += b"0" * 8 + b"0" * 8                     # gid, nlink
hdr += b"0" * 8 + b"0" * 8 + b"0" * 8          # mtime, filesize, devmajor
hdr += b"0" * 8 + b"0" * 8                     # devminor, rdevmajor
hdr += b"0" * 8 + b"0" * 8                     # rdevminor, namesize
hdr += b"0" * 8                                # check
name = b"TRAILER!!!\0"
name += b"\0" * ((-len(name)) % 4)

with gzip.GzipFile(filename="", mode="wb", fileobj=open(sys.argv[1], "wb"), mtime=0) as f:
    f.write(hdr + name)
print("empty ramdisk ->", sys.argv[1])
