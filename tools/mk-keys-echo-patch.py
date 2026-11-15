#!/usr/bin/env python3
"""Generate 0129: re-print the GPIO6 cfg readout from the keys thread.

    python tools/mk-keys-echo-patch.py <apollo_keys.c as built by CI> [out.patch]

The input is the CI build tree's file (0082/0083/0084/0106 applied). We stack
0128 on top of it in a temp copy, apply the echo edits, and diff the result so
the new patch applies after 0128.
"""
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
P128 = os.path.join(ROOT, 'xnu', 'patches', '0128-apollo-keys-gpio-diag.patch')
OUT = os.path.join(ROOT, 'xnu', 'patches', '0129-apollo-keys-echo.patch')


def apply_0128(base_text):
    tmp = tempfile.mkdtemp(prefix='keys-echo-')
    dst = os.path.join(tmp, 'bsd', 'dev', 'apollo_keys.c')
    os.makedirs(os.path.dirname(dst))
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        f.write(base_text)
    subprocess.run(['git', 'apply', P128], cwd=tmp, check=True)
    with open(dst, encoding='utf-8') as f:
        text = f.read()
    shutil.rmtree(tmp)
    return text


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else OUT
    old = apply_0128(open(base, encoding='utf-8').read())

    # 1) take the RT status as an argument and keep reading the config there.
    a = '''static void
keys_dump_gpio6(void)
{'''
    b = '''static void
keys_dump_gpio6(uint8_t rt)
{'''
    assert old.count(a) == 1
    new = old.replace(a, b, 1)

    a = '''	printf("SWEET KEYS(apollo): gpio6 cfg type=%#x/%d sub=%#x/%d mode=%#x/%d vin=%#x/%d pull=%#x/%d in=%#x/%d out=%#x/%d en=%#x/%d\\n",
	    v[0], ok[0], v[1], ok[1], v[2], ok[2], v[3], ok[3],
	    v[4], ok[4], v[5], ok[5], v[6], ok[6], v[7], ok[7]);'''
    b = '''	printf("SWEET KEYS(apollo): gpio6 type=%#x/%d sub=%#x/%d mode=%#x/%d vin=%#x/%d pull=%#x/%d in=%#x/%d out=%#x/%d en=%#x/%d rt=%#x\\n",
	    v[0], ok[0], v[1], ok[1], v[2], ok[2], v[3], ok[3],
	    v[4], ok[4], v[5], ok[5], v[6], ok[6], v[7], ok[7], rt);'''
    assert new.count(a) == 1
    new = new.replace(a, b, 1)

    a = '''	keys_dump_gpio6();
'''
    b = '''	keys_dump_gpio6(gpio);
'''
    assert new.count(a) == 1
    new = new.replace(a, b, 1)

    # 2) echo the latest values from the polling thread, so the line survives
    #    the boot log scrolling away (~2 s at the 20 ms poll interval).
    a = '''		keys_dump_gpios();
		keys_wait();'''
    b = '''		keys_dump_gpios();
		{
			static unsigned echo;

			if ((echo++ % 100u) == 0) {
				keys_dump_gpio6(gok ? gpio : 0xffu);
			}
		}
		keys_wait();'''
    assert new.count(a) == 1
    new = new.replace(a, b, 1)

    # 3) also repeat the KEYSDBG snapshot every 5 s when it is enabled.
    a = '''	if (!changed) {'''
    b = '''	if (!changed && (tick % 250u) != 0) {'''
    assert new.count(a) == 1
    new = new.replace(a, b, 1)

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
