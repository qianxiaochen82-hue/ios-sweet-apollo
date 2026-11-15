#!/usr/bin/env python3
"""Generate 0130: opt-in PM8150 GPIO6 pull-up write (boot-arg sweetkeys_cfg=1).

    python tools/mk-keys-cfg-patch.py <apollo_keys.c as built by CI> [out.patch]

The input is the CI build tree's file (0082/0083/0084/0106 applied); 0128 and
0129 are stacked on top of it in a temp copy and the result is diffed, so the
patch applies after them.
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
OUT = os.path.join(ROOT, 'xnu', 'patches', '0130-apollo-keys-pullup.patch')

HELPER = '''/*
 * Write one aligned word through the same observer channel keys_read uses:
 * EXT_WRITEL (opcode 0) takes the data from WDATA and reports via STATUS.  The
 * wait is capped at about a millisecond and never retried, so a wedged arbiter
 * only costs the write instead of hanging the boot.
 */
static bool
keys_write32(uint16_t apid, uint16_t addr, uint32_t value)
{
	if (apid == KEYS_NO_APID || (addr & 3u)) {
		return false;
	}
	uint32_t off = 0x80u * apid;
	*(volatile uint32_t *)(keys_obs + off + 0x10u) = value;
	__asm__ volatile("dmb oshst" ::: "memory");
	*(volatile uint32_t *)(keys_obs + off) = (uint32_t)(addr & 0xffu) << 4;
	__asm__ volatile("dsb osh" ::: "memory");
	for (unsigned i = 0; i < 2; ++i) {
		keys_last_status = keys_rd(keys_obs, off + 0x08u);
		if (keys_last_status & 1u) {
			return (keys_last_status & 0x0eu) == 0;
		}
		delay(1);
	}
	return false;
}

/*
 * Boot-arg sweetkeys_cfg=1: the pin is enabled and its level tracks the key,
 * but DIG_PULL_CTL is 0 (no bias), so the released state floats.  Set the
 * pull-up and nothing else: one aligned 4-byte EXT_WRITEL over MODE/VIN/PULL/IN
 * with the values just read back.  Validate the identity first and give up
 * loudly on any mismatch.
 */
static int keys_cfg;

static void
keys_gpio6_pullup(void)
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
	if (!ok[0] || v[0] != 0x10u || !ok[1] || (v[1] != 0x10u && v[1] != 0x11u)) {
		printf("SWEET KEYS(apollo): cfg skip type=%#x/%d sub=%#x/%d\\n",
		    v[0], ok[0], v[1], ok[1]);
		return;
	}
	if (!ok[7] || !(v[7] & 0x80u)) {
		printf("SWEET KEYS(apollo): cfg skip not enabled en=%#x/%d\\n",
		    v[7], ok[7]);
		return;
	}
	if (!ok[2] || !ok[3] || !ok[4] || !ok[5]) {
		printf("SWEET KEYS(apollo): cfg skip mode/vin/pull/in unreadable\\n");
		return;
	}
	if (v[4] != 0) {
		printf("SWEET KEYS(apollo): cfg pull already %#x, nothing to do\\n",
		    v[4]);
		return;
	}
	uint32_t word = (uint32_t)v[2] | ((uint32_t)v[3] << 8) |
	    (0x03u << 16) | ((uint32_t)v[5] << 24);
	bool wok = keys_write32(keys_gpio_apid, (uint16_t)(KEYS_GPIO6 + 0x40u), word);
	printf("SWEET KEYS(apollo): cfg write 0x40=%#x ok=%d status=%#x\\n",
	    word, wok, keys_last_status);
	uint8_t again[7];
	bool aok[7];

	for (unsigned i = 0; i < 7; ++i) {
		again[i] = 0;
		aok[i] = keys_read(keys_gpio_apid,
		    (uint16_t)(KEYS_GPIO6 + 0x40u + i), &again[i]);
	}
	printf("SWEET KEYS(apollo): cfg after mode=%#x/%d vin=%#x/%d pull=%#x/%d "
	    "in=%#x/%d out=%#x/%d en=%#x/%d\\n",
	    again[0], aok[0], again[1], aok[1], again[2], aok[2], again[3],
	    aok[3], again[5], aok[5], again[6], aok[6]);
}

'''

ANCHOR = '''/*
 * Debug aid (boot-arg sweetkeydebug=1)'''


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else OUT
    tmp = tempfile.mkdtemp(prefix='keys-cfg-')
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

    assert old.count(ANCHOR) == 1
    new = old.replace(ANCHOR, HELPER + ANCHOR, 1)

    a = '''	(void)PE_parse_boot_argn("sweetkeydebug", &keys_debug, sizeof(keys_debug));
'''
    b = '''	(void)PE_parse_boot_argn("sweetkeydebug", &keys_debug, sizeof(keys_debug));
	(void)PE_parse_boot_argn("sweetkeys_cfg", &keys_cfg, sizeof(keys_cfg));
'''
    assert new.count(a) == 1
    new = new.replace(a, b, 1)

    a = '''	keys_dump_gpio6(gpio);
'''
    b = '''	keys_dump_gpio6(gpio);
	if (keys_cfg) {
		keys_gpio6_pullup();
	}
'''
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
