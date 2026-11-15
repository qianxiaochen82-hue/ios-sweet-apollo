#!/usr/bin/env python3
"""Generate 0132: address each PM8150 GPIO pin through its own SPMI peripheral.

    python tools/mk-keys-pin-apid-patch.py <apollo_keys.c as built by CI> [out.patch]

Vendor pinctrl-spmi-gpio.c gives every pin its own 0x100 window
(`pad->base = start + i * PMIC_GPIO_ADDRESS_RANGE`) and maps the DT number
through `pad->gpio_idx = i + 1`.  So "gpio6" in xiaomi-sm8250-common.dtsi is
the *sixth* window, 0xc500, whose peripheral id is 0xc5 - not the block base
0xc0.  The arbiter command only carries the low byte of the address, so
0xc610 was silently read as register 0x10 of ppid 0xc0 = gpio1, and every
pin in the dump resolved to that same register (hence "01" twelve times).
"""
import difflib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STACK = ['0128-apollo-keys-gpio-diag.patch', '0129-apollo-keys-echo.patch',
         '0131-apollo-keys-rt-status.patch']
OUT = os.path.join(ROOT, 'xnu', 'patches', '0132-apollo-keys-pin-apid.patch')


def sub(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    base = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else OUT
    tmp = tempfile.mkdtemp(prefix='keys-pin-')
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

    # 1. pin -> peripheral id
    new = sub(new,
              '#define KEYS_GPIO_STRIDE 0x100u\n'
              '#define KEYS_GPIO6       (6u * KEYS_GPIO_STRIDE)  /* 0xc600 */\n',
              '/*\n'
              ' * Every PM8150 GPIO pin is its own SPMI peripheral: pin i (0-based)\n'
              ' * sits at 0xc000 + i*0x100 and is resolved by ppid 0xc0 + i.  DT\n'
              ' * gpio<n> is pin n (vendor pinctrl uses gpio_idx = i + 1), so the\n'
              ' * volume-up key is ppid 0xc5 at 0xc500 - reading the block base\n'
              ' * 0xc0 instead was reading gpio1, the finger-detect pin.\n'
              ' */\n'
              '#define KEYS_GPIO_PIN_PPID(i) (0x0c0u + (i))\n'
              '#define KEYS_GPIO6_PPID  KEYS_GPIO_PIN_PPID(5u)  /* 0xc500 */\n'
              '#define KEYS_GPIO_PINS   10u   /* reg 0xa00 / 0x100 */\n')

    # 2. per-pin APID table
    new = sub(new,
              'static uint16_t keys_pon_apid = KEYS_NO_APID, keys_gpio_apid = KEYS_NO_APID;\n',
              'static uint16_t keys_pon_apid = KEYS_NO_APID, keys_gpio_apid = KEYS_NO_APID;\n'
              'static uint16_t keys_pin_apid[KEYS_GPIO_PINS];\n')

    # 3. accessor
    new = sub(new,
              '/*\n'
              ' * Debug aid (boot-arg sweetkeydebug=1): snapshot every PM8150 GPIO so a key\n',
              '/* One register of one pin, through that pin\'s own peripheral. */\n'
              'static bool\n'
              'keys_pin_read(uint32_t pin, uint16_t reg, uint8_t *out)\n'
              '{\n'
              '\tif (pin >= KEYS_GPIO_PINS) {\n'
              '\t\treturn false;\n'
              '\t}\n'
              '\treturn keys_read(keys_pin_apid[pin], reg, out);\n'
              '}\n'
              '\n'
              '/*\n'
              ' * Debug aid (boot-arg sweetkeydebug=1): snapshot every PM8150 GPIO so a key\n')

    # 4. dump loop
    new = sub(new,
              '\t\tok[p] = keys_read(keys_gpio_apid,\n'
              '\t\t    (uint16_t)(p * KEYS_GPIO_STRIDE + KEYS_GPIO_RT), &cur[p]);\n',
              '\t\tok[p] = keys_pin_read((uint32_t)p - 1u, KEYS_GPIO_RT, &cur[p]);\n')

    # 5. gpio6 config dump
    new = sub(new,
              '\t\tok[i] = keys_read(keys_gpio_apid,\n'
              '\t\t    (uint16_t)(KEYS_GPIO6 + off[i]), &v[i]);\n',
              '\t\tok[i] = keys_pin_read(5u, off[i], &v[i]);\n')

    # 6. thread poll
    new = sub(new,
              '\t\tbool gok = keys_read(keys_gpio_apid, KEYS_GPIO6 + KEYS_GPIO_RT, &gpio);\n',
              '\t\tbool gok = keys_pin_read(5u, KEYS_GPIO_RT, &gpio);\n')

    # 7. APID discovery for every pin
    new = sub(new,
              '\tkeys_pon_apid = keys_find_apid(KEYS_PON_PPID, count);\n'
              '\tkeys_gpio_apid = keys_find_apid(KEYS_GPIO_PPID, count);\n'
              '\tif (keys_gpio_apid == KEYS_NO_APID) {\n'
              '\t\t/* PM8150 GPIO may be decoded one slot higher (see PM6150L: 0xc1). */\n'
              '\t\tkeys_gpio_apid = keys_find_apid(KEYS_GPIO_PPID + 1u, count);\n'
              '\t}\n',
              '\tkeys_pon_apid = keys_find_apid(KEYS_PON_PPID, count);\n'
              '\tfor (uint32_t i = 0; i < KEYS_GPIO_PINS; ++i) {\n'
              '\t\tkeys_pin_apid[i] = keys_find_apid(KEYS_GPIO_PIN_PPID(i), count);\n'
              '\t\tif (keys_pin_apid[i] != KEYS_NO_APID) {\n'
              '\t\t\tprintf("SWEET KEYS(apollo): pin%u ppid=%#x apid=%u\\n",\n'
              '\t\t\t    i + 1u, KEYS_GPIO_PIN_PPID(i), keys_pin_apid[i]);\n'
              '\t\t}\n'
              '\t}\n'
              '\tkeys_gpio_apid = keys_pin_apid[5];\n'
              '\tif (keys_gpio_apid == KEYS_NO_APID) {\n'
              '\t\tkeys_gpio_apid = keys_find_apid(KEYS_GPIO_PPID, count);\n'
              '\t}\n')

    # 8. boot banner pub the real pin
    new = sub(new,
              '\tbool gok = keys_read(keys_gpio_apid, KEYS_GPIO6 + KEYS_GPIO_RT, &gpio);\n'
              '\tbool aok = keys_read(keys_gpio_apid, KEYS_GPIO6 + 0x10u, &gpio_alt);\n'
              '\tprintf("SWEET KEYS(apollo): arb=%#x apids=%u pon-apid=%u gpio-apid=%u pon=%#x/%d gpio6[0x0a]=%#x/%d gpio6[0x10]=%#x/%d\\n",\n'
              '\t    keys_version, count, keys_pon_apid, keys_gpio_apid,\n'
              '\t    pon, pok, gpio, gok, gpio_alt, aok);\n',
              '\tbool gok = keys_pin_read(5u, KEYS_GPIO_RT, &gpio);\n'
              '\tbool aok = keys_pin_read(5u, 0x40u, &gpio_alt);\n'
              '\tprintf("SWEET KEYS(apollo): arb=%#x apids=%u pon-apid=%u pin6-apid=%u pon=%#x/%d gpio6[mode]=%#x/%d gpio6[rt]=%#x/%d\\n",\n'
              '\t    keys_version, count, keys_pon_apid, keys_gpio_apid,\n'
              '\t    pon, pok, gpio_alt, aok, gpio, gok);\n')

    assert 'KEYS_GPIO_STRIDE' not in new and 'KEYS_GPIO6 +' not in new

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
