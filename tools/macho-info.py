#!/usr/bin/env python3
"""Print cputype/cpusubtype of Mach-O files (thin or fat).

Used before pulling an IPSW userland into the root image: apollo is ARMv8.2
(no FEAT_PAuth), so only subtype 0 (plain arm64) binaries can execute; subtype
2 (arm64e) traps on PACIA/PAUTH.

    python tools/macho-info.py FILE...

Exit status is 0 when every file has at least one plain arm64 slice.
"""
import struct
import sys

CPU_NAMES = {
    7: "i386",
    0x01000007: "x86_64",
    12: "arm",
    0x0100000C: "arm64",
}

# aarch64 subtypes; 0 is the plain one we can run
ARM64_SUBTYPES = {
    0: "ALL (plain arm64)",
    1: "V8",
    2: "arm64e",
    0x80000002: "arm64e (user ABI)",
}


def _names(cputype, cpusubtype):
    name = CPU_NAMES.get(cputype, "?")
    if cputype == 0x0100000C:
        sub = ARM64_SUBTYPES.get(cpusubtype, "?")
    else:
        sub = "?"
    return name, sub


def _slice(raw, off, label):
    magic = struct.unpack_from("<I", raw, off)[0]
    if magic in (0xFEEDFACF, 0xFEEDFACE):
        end = "<"
    elif magic in (0xCFFAEDFE, 0xCEFAEDFE):
        end = ">"
    else:
        return None
    cputype, cpusubtype = struct.unpack_from(end + "II", raw, off + 4)
    name, sub = _names(cputype, cpusubtype)
    print("%s: cputype=0x%08x (%s) cpusubtype=0x%08x (%s)"
          % (label, cputype, name, cpusubtype, sub))
    return cputype, cpusubtype


def inspect(path):
    with open(path, "rb") as f:
        head = f.read()
    magic = struct.unpack_from(">I", head, 0)[0]
    slices = []
    if magic in (0xCAFEBABE, 0xCAFEBABF):
        count = struct.unpack_from(">I", head, 4)[0]
        step = 20 if magic == 0xCAFEBABE else 32
        for i in range(count):
            base = 8 + i * step
            cputype, cpusubtype, off = struct.unpack_from(">III", head, base)
            name, sub = _names(cputype, cpusubtype)
            print("%s[%d]: cputype=0x%08x (%s) cpusubtype=0x%08x (%s) @%#x"
                  % (path, i, cputype, name, cpusubtype, sub, off))
            slices.append((cputype, cpusubtype))
    else:
        one = _slice(head, 0, path)
        if one is None:
            print("%s: not a Mach-O" % path)
            return False
        slices.append(one)
    return any(ct == 0x0100000C and cs == 0 for ct, cs in slices)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ok = True
    for path in argv[1:]:
        try:
            ok = inspect(path) and ok
        except OSError as e:
            print("%s: %s" % (path, e))
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
