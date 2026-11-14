/*
 * First userspace program for SWEET bring-up: it is /sbin/launchd on the
 * HFS+ RAM disk, so it is PID 1. It proves that exec, the user/kernel
 * boundary, devfs, HFS file reads, a writable root and the console all work,
 * then stays alive (init exiting panics the kernel).
 *
 * tools/mkinit.py wraps the assembled __text into a static Mach-O, so this
 * must stay position independent with no relocations and no writable data:
 * every reference is adr (PC-relative), buffers live on the stack.
 *
 * Raw XNU syscalls: number in x16, svc #0x80, carry set on error (x0 = errno).
 */
#define SYS_read	3
#define SYS_write	4
#define SYS_open	5
#define SYS_close	6
#define SYS_getpid	20
#define SYS_select	93
#define SYS_mmap	197
#define SYS_sysctl	202
#define O_RDONLY	0
#define O_WRONLY	1
#define O_CREAT		0x0200
#define PROT_RW		3

	.text
	.globl	_start
	.p2align 2
_start:
	/*
	 * The kernel enters a static binary with sp at argc, aligned only to
	 * what the argument/apple strings happened to need. Using a misaligned
	 * sp as a base register raises an SP alignment fault (SIGBUS) on real
	 * hardware (QEMU does not check), so align it like crt0/dyld do.
	 */
	mov	x9, sp
	and	x9, x9, #~15
	mov	sp, x9

	adr	x0, path_console
	mov	x1, #O_WRONLY
	mov	x2, #0
	mov	x16, #SYS_open
	svc	#0x80
	b.cs	hang			/* no console: nothing to report to */
	mov	x19, x0

	adr	x1, hello
	adr	x2, hello_tail
	sub	x2, x2, x1
	bl	write_console

	mov	x16, #SYS_getpid
	svc	#0x80
	add	w0, w0, #'0'		/* PID 1 expected: one digit */
	sub	sp, sp, #16
	strb	w0, [sp]
	mov	x1, sp
	mov	x2, #1
	bl	write_console
	add	sp, sp, #16

	adr	x1, hello_tail
	adr	x2, hello_end
	sub	x2, x2, x1
	bl	write_console

	/* --- probe 1: read a file off the HFS+ root --- */
	adr	x1, msg_read
	adr	x2, msg_read_end
	sub	x2, x2, x1
	bl	write_console

	adr	x0, path_readme
	mov	x1, #O_RDONLY
	mov	x2, #0
	mov	x16, #SYS_open
	svc	#0x80
	b.cs	read_fail

	mov	x20, x0
	sub	sp, sp, #64
	mov	x0, x20
	mov	x1, sp
	mov	x2, #63
	mov	x16, #SYS_read
	svc	#0x80
	b.cs	read_fail_buf
	mov	x21, x0

	mov	x0, x20
	mov	x16, #SYS_close
	svc	#0x80

	mov	x1, sp
	mov	x2, x21
	bl	write_console
	add	sp, sp, #64
	b	probe_write

read_fail_buf:
	add	sp, sp, #64
read_fail:
	bl	fail_line
	b	probe_write

	/* --- probe 2: the root is writable (launchd needs /var/run) --- */
probe_write:
	adr	x1, msg_create
	adr	x2, msg_create_end
	sub	x2, x2, x1
	bl	write_console

	adr	x0, path_vartest
	mov	x1, #0x201			/* O_WRONLY | O_CREAT */
	mov	x2, #0x1a4			/* 0644 */
	mov	x16, #SYS_open
	svc	#0x80
	b.cs	write_fail

	mov	x20, x0
	adr	x1, oktext
	adr	x2, oktext_end
	sub	x2, x2, x1
	mov	x0, x20
	mov	x16, #SYS_write
	svc	#0x80
	b.cs	write_fail

	mov	x0, x20
	mov	x16, #SYS_close
	svc	#0x80

	bl	ok_line
	b	probe_mmap

write_fail:
	bl	fail_line
	b	probe_mmap

	/* --- probe 3: anonymous mmap + store/load (dyld maps everything) --- */
probe_mmap:
	adr	x1, msg_mmap
	adr	x2, msg_mmap_end
	sub	x2, x2, x1
	bl	write_console

	mov	x0, #0
	mov	x1, #16384
	mov	x2, #PROT_RW
	mov	x3, #0x1002			/* MAP_PRIVATE | MAP_ANON */
	movn	x4, #0				/* fd = -1 */
	mov	x5, #0
	mov	x16, #SYS_mmap
	svc	#0x80
	b.cs	mmap_fail

	mov	x20, x0
	mov	x21, #0x5aa5
	str	x21, [x20]
	ldr	x22, [x20]
	cmp	x21, x22
	b.ne	mmap_fail

	bl	ok_line
	b	probe_sysctl

mmap_fail:
	bl	fail_line
	b	probe_sysctl

	/* --- probe 4: sysctl kern.osrelease (dyld reads it for quirks) --- */
probe_sysctl:
	adr	x1, msg_sysctl
	adr	x2, msg_sysctl_end
	sub	x2, x2, x1
	bl	write_console

	sub	sp, sp, #48
	mov	x9, #32
	str	x9, [sp, #32]		/* oldlenp */
	adr	x0, sysctl_name
	mov	x1, #2
	mov	x2, sp
	add	x3, sp, #32
	mov	x4, #0
	mov	x5, #0
	mov	x16, #SYS_sysctl
	svc	#0x80
	b.cs	sysctl_fail

	ldr	x2, [sp, #32]
	mov	x1, sp
	bl	write_console
	add	sp, sp, #48
	b	tick

sysctl_fail:
	add	sp, sp, #48
	bl	fail_line

tick:
	/* select(0, NULL, NULL, NULL, &5s) as a portable sleep */
	mov	x0, #0
	mov	x1, #0
	mov	x2, #0
	mov	x3, #0
	adr	x4, five_sec
	mov	x16, #SYS_select
	svc	#0x80

	adr	x1, alive
	adr	x2, alive_end
	sub	x2, x2, x1
	bl	write_console
	b	tick

/* write(x19, x1, x2) */
write_console:
	mov	x0, x19
	mov	x16, #SYS_write
	svc	#0x80
	ret

/* print w0 as three decimal digits (errno <= 255, leading zeros fine) */
print_num:
	sub	sp, sp, #16
	mov	w10, #100
	udiv	w12, w0, w10
	msub	w13, w12, w10, w0
	add	w12, w12, #'0'
	strb	w12, [sp]
	mov	w10, #10
	udiv	w14, w13, w10
	msub	w15, w14, w10, w13
	add	w14, w14, #'0'
	strb	w14, [sp, #1]
	add	w15, w15, #'0'
	strb	w15, [sp, #2]
	mov	x1, sp
	mov	x2, #3
	bl	write_console
	add	sp, sp, #16
	ret

/* w0 = errno -> "ERR <nnn>\n" */
fail_line:
	mov	x20, x0
	adr	x1, err_prefix
	adr	x2, err_prefix_end
	sub	x2, x2, x1
	bl	write_console
	mov	x0, x20
	bl	print_num
	adr	x1, nl
	adr	x2, nl_end
	sub	x2, x2, x1
	bl	write_console
	ret

ok_line:
	adr	x1, okmsg
	adr	x2, okmsg_end
	sub	x2, x2, x1
	bl	write_console
	ret

hang:
	b	hang

	.p2align 3
five_sec:
	.quad	5			/* tv_sec */
	.quad	0			/* tv_usec (int32 + padding) */
sysctl_name:
	.word	1, 2			/* CTL_KERN, KERN_OSRELEASE */
path_console:
	.asciz	"/dev/console"
path_readme:
	.asciz	"/README.txt"
path_vartest:
	.asciz	"/var/run/swtest"
hello:
	.ascii	"\n*** SWEET userspace: init running as PID "
hello_tail:
	.ascii	" ***\n"
hello_end:
msg_read:
	.ascii	"probe: read /README.txt = "
msg_read_end:
msg_create:
	.ascii	"probe: create /var/run/swtest = "
msg_create_end:
msg_mmap:
	.ascii	"probe: mmap 16K RW = "
msg_mmap_end:
msg_sysctl:
	.ascii	"probe: sysctl kern.osrelease = "
msg_sysctl_end:
okmsg:
	.ascii	"OK\n"
okmsg_end:
oktext:
	.ascii	"ok\n"
oktext_end:
err_prefix:
	.ascii	"ERR "
err_prefix_end:
nl:
	.ascii	"\n"
nl_end:
alive:
	.ascii	"SWEET init: still alive\n"
alive_end:
