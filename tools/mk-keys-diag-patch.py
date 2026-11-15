#!/usr/bin/env python3
"""Generate 0128 from the *post-0106* apollo_keys.c (not from 0082 alone).

    python tools/mk-keys-diag-patch.py <patched apollo_keys.c> [out.patch]

0082/0083/0084/0106 all touch the file, so diffing against 0082's raw content
produces a patch that no longer applies; use the file as built by CI instead
(`gh run download ... -n xnu-buildtree` then extract xnu/bsd/dev/apollo_keys.c).
"""
import difflib
import sys

OUT = 'xnu/patches/0128-apollo-keys-gpio-diag.patch'

DUMP = '''/*
 * Read-only: dump the PMIC5 GPIO6 configuration.  If the bootloader left the
 * pin disabled (EN_CTL bit7 clear) the RT status bit never follows the key, so
 * the level alone cannot tell us whether this is the right pin.
 */
static void
keys_dump_gpio6(void)
{
	static const uint8_t off[] = { 0x04u, 0x05u, 0x40u, 0x41u,
	    0x42u, 0x43u, 0x45u, 0x46u };
	uint8_t v[8];
	bool ok[8];

	for (unsigned i = 0; i < 8; ++i) {
		v[i] = 0;
		ok[i] = keys_read(keys_gpio_apid,
		    (uint16_t)(KEYS_GPIO6 + off[i]), &v[i]);
	}
	printf("SWEET KEYS(apollo): gpio6 cfg type=%#x/%d sub=%#x/%d mode=%#x/%d vin=%#x/%d pull=%#x/%d in=%#x/%d out=%#x/%d en=%#x/%d\\n",
	    v[0], ok[0], v[1], ok[1], v[2], ok[2], v[3], ok[3],
	    v[4], ok[4], v[5], ok[5], v[6], ok[6], v[7], ok[7]);
}

'''


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[3 - 1] if len(sys.argv) == 3 else OUT
    old = open(base, encoding='utf-8').read()

    anchor = 'static void\nkeys_dump_map(uint32_t count)\n'
    assert old.count(anchor) == 1, 'keys_dump_map anchor not unique'
    new = old.replace(anchor, DUMP + anchor, 1)

    init = '''	if (!pok) {
		keys_dump_map(count);
	}
'''
    init_new = '''	if (!pok || keys_gpio_apid == KEYS_NO_APID) {
		keys_dump_map(count);
	}
	keys_dump_gpio6();
'''
    assert new.count(init) == 1, 'init block anchor not unique'
    new = new.replace(init, init_new, 1)

    diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                'a/bsd/dev/apollo_keys.c',
                                'b/bsd/dev/apollo_keys.c', n=3)
    body = ''.join(l for l in diff if not l.startswith(('--- ', '+++ ')))
    header = ('diff --git a/bsd/dev/apollo_keys.c b/bsd/dev/apollo_keys.c\n'
              '--- a/bsd/dev/apollo_keys.c\n'
              '+++ b/bsd/dev/apollo_keys.c\n')
    open(out, 'w', encoding='utf-8', newline='\n').write(header + body)
    print('wrote', out, len(body.splitlines()), 'diff lines')


if __name__ == '__main__':
    main()
