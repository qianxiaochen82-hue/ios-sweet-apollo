#!/usr/bin/env python3
"""Generate 0131: read the PM8150 GPIO level from 0x10, not 0x0a.

    python tools/mk-keys-rt-patch.py <apollo_keys.c as built by CI> [out.patch]

The vendor pinctrl-spmi-gpio.c only defines PMIC_MPP_REG_RT_STS (0x10) for the
pad level; 0x0a is not a PMIC5 GPIO status register, so every pin read back 0
and volume-up could never be seen.
"""
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STACK = ['0128-apollo-keys-gpio-diag.patch', '0129-apollo-keys-echo.patch']
OUT = os.path.join(ROOT, 'xnu', 'patches', '0131-apollo-keys-rt-status.patch')


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else OUT
    tmp = tempfile.mkdtemp(prefix='keys-rt-')
    dst = os.path.join(tmp, 'bsd', 'dev', 'apollo_keys.c')
    os.makedirs(os.path.dirname(dst))
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        f.write(open(base, encoding='utf-8').read())
    for p in STACK:
        subprocess.run(['git', 'apply', os.path.join(ROOT, 'xnu', 'patches', p)],
                       cwd=tmp, check=True)
    with open(dst, encoding='utf-8') as f:
        old = f.read()
    shutil.rmtree(tmp)

    a = '#define KEYS_GPIO_RT     0x0au    /* PMIC5 GPIO pin status */\n'
    b = '''/*
 * The live pad level lives in DIG_RT_STATUS at 0x10, the offset the vendor
 * pinctrl-spmi-gpio.c reads (PMIC_MPP_REG_RT_STS, valid bit0). 0x0a is not a
 * PMIC5 GPIO status register on this block: reading it returns 0 for every
 * pin, which is why volume-up looked dead while its config was already right
 * (mode=input, vin=1, pull=0 == 30uA pull-up, en=0x80).
 */
#define KEYS_GPIO_RT     0x10u    /* PMIC5 GPIO DIG_RT_STATUS (pad level) */
'''
    assert old.count(a) == 1
    new = old.replace(a, b, 1)

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
