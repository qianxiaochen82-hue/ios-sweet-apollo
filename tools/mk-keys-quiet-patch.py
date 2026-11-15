#!/usr/bin/env python3
"""Generate 0133: quiet the keys diagnostics now that volume-up works.

    python tools/mk-keys-quiet-patch.py <apollo_keys.c as built by CI> [out.patch]

Removes the temporary spam added while chasing volume-up:
  - the 2 s `gpio6 type=... rt=...` reprint from the keys thread (0129),
  - the 5 s KEYSDBG reprint (0129); it is change-only again,
  - the six-line pin/ppid/apid table (0132); the summary line keeps pin6.
Key polling and HID reporting are untouched.
"""
import difflib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STACK = ['0128-apollo-keys-gpio-diag.patch', '0129-apollo-keys-echo.patch',
         '0131-apollo-keys-rt-status.patch', '0132-apollo-keys-pin-apid.patch']
OUT = os.path.join(ROOT, 'xnu', 'patches', '0133-apollo-keys-quiet.patch')


def sub(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else OUT
    tmp = tempfile.mkdtemp(prefix='keys-quiet-')
    dst = os.path.join(tmp, 'bsd', 'dev', 'apollo_keys.c')
    os.makedirs(os.path.dirname(dst))
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        f.write(open(base, encoding='utf-8').read())
    for p in STACK:
        subprocess.run(['git', 'apply', os.path.join(ROOT, 'xnu', 'patches', p)],
                       cwd=tmp, check=True)
    with open(dst, encoding='utf-8') as f:
        old = f.read()

    new = old

    # 1. change-only KEYSDBG again
    new = sub(new,
              '\tif (!changed && (tick % 250u) != 0) {\n',
              '\tif (!changed) {\n')

    # 2. no 2 s gpio6 reprint from the thread
    new = sub(new,
              '\t\tkeys_dump_gpios();\n'
              '\t\t{\n'
              '\t\t\tstatic unsigned echo;\n'
              '\n'
              '\t\t\tif ((echo++ % 100u) == 0) {\n'
              '\t\t\t\tkeys_dump_gpio6(gok ? gpio : 0xffu);\n'
              '\t\t\t}\n'
              '\t\t}\n'
              '\t\tkeys_wait();\n',
              '\t\tkeys_dump_gpios();\n'
              '\t\tkeys_wait();\n')

    # 3. one summary line instead of the six-line pin table
    new = sub(new,
              '\t\tkeys_pin_apid[i] = keys_find_apid(KEYS_GPIO_PIN_PPID(i), count);\n'
              '\t\tif (keys_pin_apid[i] != KEYS_NO_APID) {\n'
              '\t\t\tprintf("SWEET KEYS(apollo): pin%u ppid=%#x apid=%u\\n",\n'
              '\t\t\t    i + 1u, KEYS_GPIO_PIN_PPID(i), keys_pin_apid[i]);\n'
              '\t\t}\n',
              '\t\tkeys_pin_apid[i] = keys_find_apid(KEYS_GPIO_PIN_PPID(i), count);\n')

    diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                'a/bsd/dev/apollo_keys.c',
                                'b/bsd/dev/apollo_keys.c', n=3)
    body = ''.join(l for l in diff if not l.startswith(('--- ', '+++ ')))
    header = ('diff --git a/bsd/dev/apollo_keys.c b/bsd/dev/apollo_keys.c\n'
              '--- a/bsd/dev/apollo_keys.c\n'
              '+++ b/bsd/dev/apollo_keys.c\n')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(header + body)
    print('wrote', out, len(body.splitlines()), 'diff lines')


if __name__ == '__main__':
    main()
