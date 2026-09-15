#!/bin/sh -e

if [ -n "$CROSSDIRECT_DEBUG" ]; then
	set -x
fi

native_version=$(LD_LIBRARY_PATH=/native/lib:/native/usr/lib /native/usr/bin/rustc -V)
target_version=$(/usr/bin/rustc -V)

if [ "$target_version" != "$native_version" ]; then
	echo "ERROR: crossdirect: rustc version mismatch between native and build chroot. Please update your chroots and try again." >&2
	exit 1
fi

triplet=$(/usr/bin/rustc -vV | sed -n 's/host: //p')
cmd=$1
shift

# "cargo auditable build" (Alpine's Rust aports) is "cargo build" with a
# rustc wrapper that embeds the dependency list: same handling
auditable=""
if [ "$cmd" = auditable ] && [ $# -gt 0 ]; then
	auditable=auditable
	cmd=$1
	shift
fi

case "$cmd" in
	build|test|run)
		;;
	*)
		echo "WARNING: crossdirect: 'cargo ${auditable:+$auditable }$cmd $*' command not supported, running in QEMU (slow!)" >&2
		export PATH="$(echo "$PATH" | sed 's,/native/usr/lib/crossdirect/[^:]*:,,')"
		exec /usr/bin/cargo ${auditable:+"$auditable"} "$cmd" "$@"
		;;
esac

# Tell rustc.sh that cargo passes --target for target crates
export CROSSDIRECT_CARGO=1

target_dir=${CARGO_TARGET_DIR:-target}
target_already_specified=${CARGO_BUILD_TARGET:+1}

if [ -z "$target_specified" ]; then
	for arg in "$@"; do
		if [ "$arg_target_dir" = 1 ]; then
			target_dir=$arg
			arg_target_dir=0
		fi
		case "$arg" in
			--target|--target=*)
				target_already_specified=1
				break
				;;
			--target-dir)
				arg_target_dir=1
				;;
			--target-dir=*)
				target_dir=${arg##--target-dir=}
				;;
		esac
	done
fi

if [ -n "$target_already_specified" ]; then
	exec /usr/bin/cargo ${auditable:+"$auditable"} "$cmd" "$@"
fi

/usr/bin/cargo ${auditable:+"$auditable"} "$cmd" --target=$triplet "$@"

# copy target/$triplet/{release,debug,...} to target/{release,debug,...}
if [ -d "$target_dir/$triplet" ]; then
	for dir in "$target_dir/$triplet"/*/; do
		build=$(basename "$dir")
		rm -rf "$target_dir/$build"
		cp -r "$target_dir/$triplet/$build" "$target_dir/$build"
	done
fi
