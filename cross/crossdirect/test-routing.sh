#!/bin/sh
# Check where crossdirect sends an invocation, and what it adds to it.
# CROSSDIRECT_DRY_RUN makes the wrapper print the command instead of running
# it, so this needs no chroot, no cross toolchain and no foreign binary.
#
# usage: test-routing.sh <crossdirect binary> <its HOSTSPEC>

set -e
bin=$(realpath "$1")
hostspec=$2
ret=0

# The wrapper decides from its own name, so run it through the symlinks the
# package installs.
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
for name in cc gcc g++ cpp clang "$hostspec-gcc"; do
	ln -s "$bin" "$dir/$name"
done

check() { # NAME EXPECTED_GREP_PATTERN CMD ARGS... (LD_PRELOAD: set in the env)
	name=$1
	expect=$2
	cmd=$3
	shift 3
	out=$(CROSSDIRECT_DRY_RUN=1 "$dir/$cmd" "$@" 2>&1) || true
	if ! printf '%s\n' "$out" | grep -q -- "$expect"; then
		echo "FAIL: $name"
		echo "  ran:      $cmd $*"
		echo "  expected: $expect"
		echo "  got:      $out"
		ret=1
	fi
}

check "a compile runs natively" \
	"native /native/usr/lib/ccache/bin/$hostspec-gcc --sysroot=/ -O2 -c foo.c" \
	gcc -O2 -c foo.c -o foo.o
check "cc is gcc, not a missing $hostspec-cc" \
	"native /native/usr/lib/ccache/bin/$hostspec-gcc " \
	cc -c foo.c
check "a link runs natively, with the target's own GCC runtime" \
	"native /native/usr/lib/ccache/bin/$hostspec-g++ -B/usr/lib/gcc/ -B/usr/lib/ --sysroot=/ foo.o -o foo" \
	g++ foo.o -o foo
check "a compile does not get the link's -B arguments" \
	"native /native/usr/lib/ccache/bin/$hostspec-gcc --sysroot=/ -c foo.c" \
	gcc -c foo.c
check "preprocessing stays in qemu" "qemu /usr/bin/gcc -E" gcc -E foo.c
check "assembling stays in qemu" "qemu /usr/bin/gcc -S" gcc -S foo.c
check "dependency generation stays in qemu" "qemu /usr/bin/gcc -M" gcc -M foo.c
check "a query about the target's GCC stays in qemu" \
	"qemu /usr/bin/gcc -print-prog-name=ld" gcc -print-prog-name=ld
check "-dumpmachine stays in qemu" "qemu /usr/bin/gcc -dumpmachine" gcc -dumpmachine
check "--version stays in qemu" "qemu /usr/bin/gcc --version" gcc --version
check "-v stays in qemu, libtool parses it" "qemu /usr/bin/gcc -v" gcc -v foo.o -o foo
check "cpp never links" "qemu /usr/bin/cpp" cpp foo.c
check "clang keeps going to qemu to link" "qemu /usr/bin/clang" clang foo.o -o foo
check "clang still compiles natively" \
	"native /native/usr/lib/ccache/bin/clang -target $hostspec --sysroot=/ -c" \
	clang -c foo.c

# A compiler called under fakeroot, i.e. from package(): the native binaries
# cannot run with the target's libfakeroot preloaded.
LD_PRELOAD=/usr/lib/libfakeroot.so \
	check "a link under fakeroot stays in qemu" "qemu /usr/bin/gcc foo.o -o foo" \
	gcc foo.o -o foo

[ "$ret" = 0 ] && echo "test-routing.sh: all routing checks passed"
exit "$ret"
