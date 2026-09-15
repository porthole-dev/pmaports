#!/bin/sh -e
# crossdirect wrapper for rustc: run the native compiler, for the right target.
#
# Which architecture an invocation is for depends on who calls it:
#
# - cargo, through our cargo wrapper (CROSSDIRECT_CARGO is set). The wrapper
#   passes --target, so cargo passes it for crates of the target. Every other
#   crate is a build script, a proc-macro or a dependency of one of those, and
#   is compiled for the native architecture.
#
# - Anything else: meson (mesa's nouveau, asahi and rusticl drivers), make, or a
#   plain rustc call. The build believes it is native and passes no --target
#   for any crate. A proc-macro is loaded into the compiler, so it is built for
#   the native architecture; every other crate is built for the target. The
#   rlibs a proc-macro links (syn, quote, ...) are needed for the native
#   architecture too, but only the proc-macro's command line says so. So each
#   rlib compiled for the target records its command line next to it
#   (<rlib>.crossdirect), and a proc-macro compile rebuilds the rlibs it links
#   for the native architecture from that record, on demand, into
#   .crossdirect-native/ beside the target ones.

if [ -n "$CROSSDIRECT_DEBUG" ]; then
	set -x
fi

# return the correct host architecture when cargo requests it
if [ "$*" = "-vV" ] || [ "$*" = "-V" ]; then
	exec /usr/bin/rustc "$*"
fi

# Options are split into words below, never globbed
set -f

# pmbootstrap installs sccache when building a rust program, unless --no-ccache
# is set. In that case it also sets CCACHE_DISABLE.
SCCACHE=/native/usr/bin/sccache
if ! [ -e "$SCCACHE" ] || [ -n "$CCACHE_DISABLE" ]; then
	SCCACHE=""
fi

NATIVE_DIR=.crossdirect-native

run_target() {
	# Not using sccache when building for foreign architecture, as it
	# doesn't cache the output with "Non-cacheable reasons: --sysroot"
	LD_LIBRARY_PATH=/native/lib:/native/usr/lib \
		/native/usr/bin/rustc \
		-Clinker=/native/usr/lib/crossdirect/rust-qemu-linker \
		--sysroot=/usr \
		"$@"
}

run_native() {
	PATH=/native/usr/bin:/native/bin \
	LD_LIBRARY_PATH=/native/lib:/native/usr/lib \
		$SCCACHE \
		/native/usr/bin/rustc \
		-Clink-arg=-Wl,-rpath,/native/lib:/native/usr/lib \
		"$@"
}

# $1: path -> the same file in $NATIVE_DIR of its directory
native_path() {
	echo "$(dirname "$1")/$NATIVE_DIR/$(basename "$1")"
}

quote() {
	printf "'%s' " "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# Print the file that a compile writes the crate to, if it can be told
target_output() {
	crate_name=""
	link=""
	out_dir=""
	prev=""
	for arg; do
		case "$prev" in
		--crate-name) crate_name=$arg ;;
		-o) link=$arg ;;
		--out-dir) out_dir=$arg ;;
		--emit) arg="--emit=$arg" ;;
		esac
		case "$arg" in
		--crate-name=*) crate_name=${arg#--crate-name=} ;;
		--out-dir=*) out_dir=${arg#--out-dir=} ;;
		--emit=*link=*)
			link=${arg##*link=}
			link=${link%%,*}
			;;
		esac
		prev=$arg
	done
	if [ -n "$link" ]; then
		echo "$link"
	elif [ -n "$out_dir" ] && [ -n "$crate_name" ]; then
		echo "$out_dir/lib$crate_name.rlib"
	fi
}

# Record how an rlib is compiled for the target, see the top of this file
record() {
	output=$(target_output "$@")
	if [ -z "$output" ]; then
		return
	fi
	{
		printf 'cd '
		quote "$PWD"
		printf '\nset -- '
		for arg; do
			quote "$arg"
		done
		printf '\n'
	} > "$output.crossdirect"
}

# $1: an rlib compiled for the target. Make sure the native one is up to date.
ensure_native() {
	native=$(native_path "$1")
	if [ "$native" -nt "$1" ]; then
		return
	fi
	if ! [ -e "$1.crossdirect" ]; then
		echo "ERROR: crossdirect: a proc-macro links $1, which was not" \
			"compiled through this wrapper, so it can't be rebuilt for" \
			"the native architecture." >&2
		exit 1
	fi
	mkdir -p "$(dirname "$native")"
	(
		exec 9> "$native.lock"
		flock 9
		if ! [ "$native" -nt "$1" ]; then
			# shellcheck disable=SC1090
			case "$1" in
			/*) . "$1.crossdirect" ;;
			*) . "./$1.crossdirect" ;;
			esac
			compile_native replay "$@"
		fi
	) || exit 1
}

# Print the native replacement of one option. $1: "replay" to write outputs to
# $NATIVE_DIR, $2: option, $3: its value. The caller splits the output into
# words: rustc arguments from meson carry no spaces in these options.
native_arg() {
	case "$2" in
	--extern)
		value=$3
		case "$value" in
		*=*.rlib|*=*.rmeta)
			# set -e does not reach into command substitutions
			ensure_native "${value#*=}" || exit 1
			value="${value%%=*}=$(native_path "${value#*=}")"
			;;
		esac
		echo "--extern $value"
		;;
	-L)
		dir=${3#*=}
		kind=${3%"$dir"}
		mkdir -p "$dir/$NATIVE_DIR"
		echo "-L $kind$dir/$NATIVE_DIR -L $3"
		;;
	-o|--out-dir)
		if [ "$1" = replay ]; then
			mkdir -p "$(dirname "$(native_path "$3")")"
			echo "$2 $(native_path "$3")"
		else
			echo "$2 $3"
		fi
		;;
	--emit)
		emit=""
		for kind in $(echo "$3" | tr ',' ' '); do
			case "$1,$kind" in
			replay,*=*)
				mkdir -p "$(dirname "$(native_path "${kind#*=}")")"
				kind="${kind%%=*}=$(native_path "${kind#*=}")"
				;;
			esac
			emit="$emit${emit:+,}$kind"
		done
		echo "--emit $emit"
		;;
	esac
}

# $1: "replay" to write the outputs to $NATIVE_DIR, "direct" otherwise
# $@: rustc arguments, externs and search paths get pointed at native crates
compile_native() {
	mode=$1
	shift
	prev=""
	for arg; do
		shift
		case "$prev" in
		--extern|-L|-o|--out-dir|--emit)
			replacement=$(native_arg "$mode" "$prev" "$arg")
			# shellcheck disable=SC2086 # split into options, see native_arg
			set -- "$@" $replacement
			prev=""
			continue
			;;
		esac
		case "$arg" in
		--extern|-L|-o|--out-dir|--emit)
			;;
		--extern=*|--out-dir=*|--emit=*)
			replacement=$(native_arg "$mode" "${arg%%=*}" "${arg#*=}")
			# shellcheck disable=SC2086 # split into options, see native_arg
			set -- "$@" $replacement
			;;
		-L?*)
			replacement=$(native_arg "$mode" -L "${arg#-L}")
			# shellcheck disable=SC2086 # split into options, see native_arg
			set -- "$@" $replacement
			;;
		*)
			set -- "$@" "$arg"
			;;
		esac
		prev=$arg
	done
	run_native "$@"
}

has_target=""
crate_types=""
prev=""
for arg; do
	case "$prev" in
	--target) has_target=1 ;;
	--crate-type) crate_types="$crate_types,$arg" ;;
	esac
	case "$arg" in
	--target=*) has_target=1 ;;
	--crate-type=*) crate_types="$crate_types,${arg#--crate-type=}" ;;
	esac
	prev=$arg
done

if [ -n "$CROSSDIRECT_CARGO" ] || [ -n "$has_target" ]; then
	# Our cargo wrapper passes the right "--target" argument, so cargo
	# passes it for target crates. Without it, this is a proc-macro or a
	# build script (or one of their dependencies): native.
	if [ -n "$has_target" ]; then
		run_target "$@"
		exit
	fi
	# cargo-auditable embeds its audit data in every binary it links,
	# build scripts included, built for the architecture "rustc -vV"
	# reports: the target's. Native artifacts are never installed, so
	# they go without it.
	prev=""
	for arg; do
		shift
		case "$prev,$arg" in
		-C,link-arg=*_audit_data.o) prev=""; continue ;;
		-C,*) set -- "$@" -C "$arg" ;;
		*,-C) ;;
		*,-Clink-arg=*_audit_data.o) ;;
		*) set -- "$@" "$arg" ;;
		esac
		prev=$arg
	done
	if [ "$prev" = -C ]; then
		set -- "$@" -C
	fi
	run_native "$@"
	exit
fi

case "$crate_types," in
*,proc-macro,*)
	compile_native direct "$@"
	;;
*)
	# A target crate, or a query like --print sysroot, which must describe
	# the target too. The build may choose a linker ("-C linker=cc" from
	# meson): rust-qemu-linker runs it with the environment it needs.
	linker=gcc
	prev=""
	for arg; do
		shift
		if [ "$prev" = -C ]; then
			prev=""
			case "$arg" in
			linker=*) linker=${arg#linker=} ;;
			*) set -- "$@" -C "$arg" ;;
			esac
			continue
		fi
		case "$arg" in
		-C) prev=-C ;;
		-Clinker=*) linker=${arg#-Clinker=} ;;
		*) set -- "$@" "$arg" ;;
		esac
	done
	case "$crate_types," in
	*,rlib,*|*,lib,*) record "$@" ;;
	esac
	triple=$(/usr/bin/rustc -vV | sed -n 's/^host: //p')
	CROSSDIRECT_RUST_LINKER=$linker run_target --target="$triple" "$@"
	;;
esac
