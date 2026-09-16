/* Copyright 2020 Zhuowei Zhang, Oliver Smith
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * This program gets built to a set of wrapper executables, which launch native
 * cross compilers inside foreign arch chroots. Speeds up cross compilation a
 * lot, compared to using just qemu user mode emulation or using the previous
 * distcc-based methods.
 *
 * How this program gets called:
 * - pmbootstrap creates one native arch chroot and one foreign arch chroot.
 * - The native chroot gets mounted as /native in the foreign chroot.
 * - When calling "abuild", pmbootstrap sets PATH to:
 *   /native/usr/lib/crossdirect/<ARCH>:$PATH
 * - That crossdirect directory contains a crossdirect-<ARCH> binary built with
 *   the matching HOSTSPEC (e.g. crossdirect-aarch64 binary with HOSTSPEC
 *   aarch64-alpine-linux-musl). This binary is symlinked to:
 *	- <HOSTSPEC>-c++
 *	- <HOSTSPEC>-cc
 *	- <HOSTSPEC>-clang
 *	- <HOSTSPEC>-clang++
 *	- <HOSTSPEC>-cpp
 *	- <HOSTSPEC>-g++
 *	- <HOSTSPEC>-gcc
 *	- c++
 *	- cc
 *	- clang
 *	- clang++
 *	- cpp
 *	- g++
 *	- gcc
 */

#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define NATIVE_BIN_DIR "/native/usr/lib/ccache/bin"
#define NATIVE_LLD "/native/usr/bin/ld.lld"
#define NATIVE_LINK_MARKER "/native/etc/crossdirect-native-link"

// Is native linking turned on? Two ways in, because they serve different
// callers. The environment variable is for a compiler invocation run by hand.
// The marker file is for a real package build: pmbootstrap builds abuild's
// environment from an explicit dict (pmb/build/backend.py) and forwards
// nothing from the host, so an exported variable never reaches this process
// during a build. The file lives in the native chroot, which outlives a
// buildroot zap.
//
// Only ever called after notCompile && isClang have already passed, so the
// stat happens on the handful of invocations that are not compiles, and not on
// the ~113k compiles of a large package.
bool native_link_enabled()
{
	return getenv("PMB_CROSSDIRECT_NATIVE_LINK") != NULL
	       || access(NATIVE_LINK_MARKER, F_OK) == 0;
}

void exit_userfriendly()
{
	fprintf(stderr, "Please report this at: https://gitlab.postmarketos.org/postmarketOS/pmaports/issues\n");
	fprintf(stderr, "As a workaround, you can compile without crossdirect with options=\"!pmb:crossdirect\".\n");
	exit(1);
}

bool argv_has_arg(int argc, char **argv, const char *arg)
{
	size_t arg_len = strlen(arg);

	for (int i = 1; i < argc; i++) {
		if (strlen(argv[i]) < arg_len)
			continue;

		if (!memcmp(argv[i], arg, arg_len))
			return true;
	}
	return false;
}

// argv_has_arg() matches on prefix, which is right for "-fuse-ld=" and wrong
// for a bare mode flag: "-E" would also match "-Efoo". These need equality.
bool argv_has_exact(int argc, char **argv, const char *arg)
{
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], arg))
			return true;
	}
	return false;
}

int main(int argc, char **argv)
{
	// we have a max of five extra args ("-target", "HOSTSPEC", "--sysroot=/"
	// and "--ld-path=..." or "-B/usr/lib/gcc/", "-B/usr/lib/"), plus one
	// ending null
	char *newargv[argc + 6];
	char *executableName = basename(argv[0]);
	char newExecutable[PATH_MAX];
	bool isClang = (strcmp(executableName, "clang") == 0 || strcmp(executableName, "clang++") == 0);
	bool startsWithHostSpec = (strncmp(HOSTSPEC, executableName, sizeof(HOSTSPEC) - 1) == 0);

	// Upstream's test: no -c means "the linker is involved". It is what gates
	// the qemu detour and must keep gating it exactly, so the default path is
	// bit-for-bit what it was.
	bool notCompile = !argv_has_arg(argc, argv, "-c");

	// ...but it is too coarse to decide whether to pass a LINKER flag. -E
	// (preprocess only) and -S (compile to assembly) also lack -c and also
	// produce nothing to link. Measured on one webkit build: 3591 invocations
	// took the native path and only 214 were real links, so 3377 preprocessor
	// runs collected a --ld-path they had no use for -- 3568 "argument unused
	// during compilation" warnings, which is noise here and a build failure in
	// any package that compiles with -Werror.
	bool isLink = notCompile
		      && !argv_has_exact(argc, argv, "-E")
		      && !argv_has_exact(argc, argv, "-S");

	// A link step normally goes to the qemu binary to avoid a broken cross-ld
	// (pmaports#227). That does not describe lld, which is multi-target and
	// cross-links to aarch64 from x86_64 without any emulation.
	//
	// Opt-in, because qemu is the safe default for every other toolchain, and
	// narrow on purpose: clang only, and only when the caller either asked for
	// lld or expressed no preference. An explicit -fuse-ld=<anything else> is
	// respected by falling through to qemu rather than silently substituting a
	// linker the package did not choose.
	//
	// Routing and flagging are separate decisions, and conflating them was the
	// bug. Everything eligible runs natively -- preprocessing under qemu is
	// pure waste, and skipping it is part of the measured win -- but only a
	// real link gets --ld-path. On anything else clang warns "argument unused
	// during compilation", which takes any -Werror package down with it, and
	// it keeps the line below out of the log for every compile in a package
	// the size of webkit.
	bool nativeRun = notCompile
			 && isClang
			 && (argv_has_arg(argc, argv, "-fuse-ld=lld")
			     || !argv_has_arg(argc, argv, "-fuse-ld="))
			 && native_link_enabled();
	bool nativeLink = nativeRun && isLink;

	// A GCC link runs the cross toolchain natively too: its collect2, ld and,
	// with -flto, lto-wrapper and lto1, which under qemu make an LTO link take
	// minutes instead of seconds. pmaports#227 ("ld: cannot find -lz") was
	// the cross ld not searching the target's library directories; the cross
	// binutils are configured with a sysroot now, so with --sysroot=/ ld
	// searches /lib and /usr/lib, DT_RUNPATH and all, like the target's ld.
	//
	// -B/usr/lib/gcc/ and -B/usr/lib/ make the driver pick the target's own
	// GCC runtime -- crtbegin*.o, libgcc.a, libgcc_s.so, libstdc++.so and the
	// libgomp.spec style spec files -- ahead of the copies in the cross
	// toolchain, so the output is byte-for-byte what the target's GCC links
	// under qemu. (The driver tries a -B directory with and without
	// <machine>/<version>/, so no version is spelled out here; a target GCC
	// of another version is not found and the cross toolchain's is used.)
	//
	// Everything that is not a link keeps going to qemu: -E, -S and -M
	// preprocess, and queries answer for the target's GCC. "-print-prog-name=ld"
	// matters most: libtool runs the path it prints directly, and the cross
	// ld cannot run without crossdirect's LD_LIBRARY_PATH. So does -v, which
	// libtool parses for the target's runtime objects and search paths. Under
	// fakeroot (a link in package(), like libtool's relink on install) the
	// native binaries cannot run, so that stays in qemu as well.
	char *ldPreload = getenv("LD_PRELOAD");
	bool underFakeroot = ldPreload && strstr(ldPreload, "libfakeroot.so");
	bool isCpp = strcmp(executableName, "cpp") == 0
		     || strcmp(executableName, HOSTSPEC "-cpp") == 0;
	bool gccLink = notCompile
		       && !isClang
		       && !isCpp
		       && !underFakeroot
		       && !argv_has_exact(argc, argv, "-E")
		       && !argv_has_exact(argc, argv, "-S")
		       && !argv_has_exact(argc, argv, "-M")
		       && !argv_has_exact(argc, argv, "-MM")
		       && !argv_has_exact(argc, argv, "-v")
		       && !argv_has_exact(argc, argv, "-###")
		       && !argv_has_exact(argc, argv, "--version")
		       && !argv_has_arg(argc, argv, "--help")
		       && !argv_has_arg(argc, argv, "-print-")
		       && !argv_has_arg(argc, argv, "-dump");
	nativeRun = nativeRun || gccLink;

	// Say so on stderr: a build log is otherwise the only place the two paths
	// can be told apart, and they differ by hours.
	if (nativeLink)
		fprintf(stderr, "crossdirect: linking natively (%s)\n", executableName);

	// With CROSSDIRECT_DRY_RUN set, print the command that would run instead
	// of running it. That is what test-routing.sh drives: which compiler an
	// invocation goes to, and with which added arguments, without a chroot,
	// a cross toolchain or a foreign binary to run.
	bool dryRun = getenv("CROSSDIRECT_DRY_RUN") != NULL;

	// linker is involved: just use qemu binary (to avoid broken cross-ld, pmaports#227)
	if (notCompile && !nativeRun) {
		snprintf(newExecutable, sizeof(newExecutable), "/usr/bin/%s", executableName);
		if (dryRun) {
			printf("qemu %s", newExecutable);
			for (int i = 1; i < argc; i++)
				printf(" %s", argv[i]);
			printf("\n");
			return 0;
		}
		if (execv(newExecutable, argv) == -1) {
			fprintf(stderr, "ERROR: crossdirect: failed to execute %s: %s\n", newExecutable, strerror(errno));
			fprintf(stderr, "NOTE: this is a foreign arch binary that would run with qemu (linker is involved).\n");
			exit_userfriendly();
		}
	}

	// Translate "cc" to "gcc": /usr/bin/cc is a symlink to /usr/bin/gcc,
	// but there is no <HOSTSPEC>-cc symlink (pmaports#732)
	if (strcmp(executableName, "cc") == 0)
		executableName = "gcc";

	// prepend the HOSTSPEC to GCC binaries
	if (isClang || startsWithHostSpec) {
		snprintf(newExecutable, sizeof(newExecutable), NATIVE_BIN_DIR "/%s", executableName);
	} else {
		snprintf(newExecutable, sizeof(newExecutable), NATIVE_BIN_DIR "/" HOSTSPEC "-%s", executableName);
	}

	// prepare new arguments for GCC / clang
	char **newArgsPtr = newargv;
	*newArgsPtr++ = newExecutable;
	if (isClang) {
		// clang does not use a HOSTSPEC prefix for the cross compiler
		// binary, but instead have a -target argument
		*newArgsPtr++ = "-target";
		*newArgsPtr++ = HOSTSPEC;

		// ld.lld lives in /native/usr/bin, but the clang driver resolves
		// through /native/usr/lib/llvm*/bin, and the execve below passes no
		// PATH -- so a bare -fuse-ld=lld cannot find it. Name it outright.
		// -B/native/usr/bin would also make it findable and is wrong: it puts
		// the native x86_64-only /native/usr/bin/ld ahead of the cross one,
		// which fails as "unrecognised emulation mode: aarch64linux" and reads
		// exactly like the broken cross-ld this branch exists to avoid.
		if (nativeLink)
			*newArgsPtr++ = "--ld-path=" NATIVE_LLD;
	} else if (gccLink) {
		*newArgsPtr++ = "-B/usr/lib/gcc/";
		*newArgsPtr++ = "-B/usr/lib/";
	}
	*newArgsPtr++ = "--sysroot=/";

	// add all arguments passed to this executable to GCC / clang and set
	// the last arg in newargv to NULL to mark its end
	memcpy(newArgsPtr, argv + 1, sizeof(char *) * (argc - 1));
	newArgsPtr += (argc - 1);
	*newArgsPtr = NULL;

	// new arguments prepared; now setup environmental vars
	char *env[] = { "LD_PRELOAD=",
		"LD_LIBRARY_PATH=/native/lib:/native/usr/lib",
		"CCACHE_PATH=/native/usr/bin",
		NULL };
	if (ldPreload) {
		if (strstr(ldPreload, "libfakeroot.so")) {
			fprintf(stderr, "============================================================================================\n");
			fprintf(stderr, "ERROR: crossdirect was called with: LD_PRELOAD=%s\n", ldPreload);
			fprintf(stderr, "This means your package tried to run a compiler during package().\n");
			fprintf(stderr, "This is not supported by crossdirect, and usually not a good idea.\n");
			fprintf(stderr, "* Try to fix your APKBUILD so it does not run the compiler during package(), only in build()\n");
			fprintf(stderr, "  * If you're using 'meson install', try to add '--no-rebuild'\n");
			fprintf(stderr, "* If this is not possible, you can work around it by setting options=\"!pmb:crossdirect\"\n");
			fprintf(stderr, "  (compilation will be slower!)\n");
			fprintf(stderr, "============================================================================================\n");
			exit(1);
		}
	}

	if (dryRun) {
		printf("native");
		for (char **arg = newargv; *arg; arg++)
			printf(" %s", *arg);
		printf("\n");
		return 0;
	}

	// finally exec GCC / clang
	if (execve(newExecutable, newargv, env) == -1) {
		fprintf(stderr, "ERROR: crossdirect: failed to execute %s: %s\n", newExecutable, strerror(errno));
		fprintf(stderr, "Maybe the target arch is missing in the ccache-cross-symlinks package?\n");
		exit_userfriendly();
	}
	return 1;
}
