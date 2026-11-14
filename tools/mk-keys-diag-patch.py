#!/usr/bin/env python3
"""Turn 0082's apollo_keys.c into a diagnostics-only patch (0128).

Reads the new-file body out of 0082, adds a read-only PMIC5 GPIO6 config dump
and prints the arbiter map when the GPIO APID is missing, then emits a unified
diff against the same file so git apply can stack it after 0082.
"""
import difflib
import os
import re

PATCH82 = 'xnu/patches/0082-sweet-apollo-input.patch'
OUT = 'xnu/patches/0128-apollo-keys-gpio-diag.patch'


def extract():
    lines = open(PATCH82, encoding='utf-8').read().splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.startswith('diff --git b/bsd/dev/apollo_keys.c'))
    end = next(i for i, l in enumerate(lines)
               if l.startswith('diff --git b/bsd/dev/apollo_touch.c'))
    body = []
    for l in lines[start:end]:
        if l.startswith(('diff ', 'index ', 'new file', '--- ', '+++ ', '@@')):
            continue
        if not l.startswith('+'):
            raise SystemExit('unexpected line in 0082: %r' % l)
        body.append(l[1:])
    return '\n'.join(body) + '\n'


DUMP = '''
/* Read-only: PMIC5 GPIO6 configuration, to find out why the pin never moves. */
static void
keys_dump_gpio6(uint16_t apid)
{
	static const uint8_t off[] = { 0x04u, 0x05u, 0x40u, 0x41u, 0x42u,
	    0x43u, 0x45u, 0x46u, 0x0au, 0x10u };
	uint8_t v[10];
	bool ok[10];
	unsigned i;

	for (i = 0; i < 10; ++i) {
		v[i] = 0;
		ok[i] = keys_read(apid, (uint16_t)(KEYS_GPIO6 + off[i]), &v[i]);
	}
	printf("SWEET KEYS(apollo): gpio6 type=%#x/%d sub=%#x/%d mode=%#x/%d vin=%#x/%d pull=%#x/%d in=%#x/%d out=%#x/%d en=%#x/%d rt0a=%#x/%d rt10=%#x/%d\\n",
	    v[0], ok[0], v[1], ok[1], v[2], ok[2], v[3], ok[3], v[4], ok[4],
	    v[5], ok[5], v[6], ok[6], v[7], ok[7], v[8], ok[8], v[9], ok[9]);
}
'''


def main():
    old = extract()
    new = old.replace('''
static void
keys_dump_map(uint32_t count)
''', DUMP + '''
static void
keys_dump_map(uint32_t count)
''', 1)
    assert new != old, 'anchor for keys_dump_gpio6 not found'

    old2 = new
    new = new.replace('''	if (!pok) {
		keys_dump_map(count);
	}
''', '''	if (!pok || keys_gpio_apid == KEYS_NO_APID) {
		keys_dump_map(count);
	}
	keys_dump_gpio6(keys_gpio_apid);
''', 1)
    assert new != old2, 'anchor for the init dump not found'

    diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                'a/bsd/dev/apollo_keys.c',
                                'b/bsd/dev/apollo_keys.c', n=3)
    text = ''.join(diff)
    header = ('diff --git a/bsd/dev/apollo_keys.c b/bsd/dev/apollo_keys.c\n'
              '--- a/bsd/dev/apollo_keys.c\n'
              '+++ b/bsd/dev/apollo_keys.c\n')
    # difflib already emits ---/+++ lines; drop them and use our own header.
    body = ''.join(l for l in text.splitlines(True)
                   if not l.startswith(('--- ', '+++ ')))
    open(OUT, 'w', encoding='utf-8', newline='\n').write(header + body)
    os.makedirs(os.path.join(os.environ.get('TEMP', '.'), 'keysdiag'), exist_ok=True)
    print('wrote', OUT, len(body.splitlines()), 'diff lines')


if __name__ == '__main__':
    main()
