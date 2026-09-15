#!/bin/sh -e
# Run bindgen natively when the native chroot has it. It generates bindings for
# a C header through libclang, which gets the target's triple here; the
# target's headers are the ones in this chroot, where the native libclang looks
# anyway. Otherwise the foreign arch bindgen runs, with its libclang, in QEMU.
# @HOSTSPEC@ is replaced when crossdirect gets built.

if [ -e /native/usr/bin/bindgen ] && [ -e /native/usr/lib/libclang.so ] \
		&& [ -z "$LD_PRELOAD" ]; then
	# libclang can't work out its resource dir (stddef.h, stdatomic.h, ...)
	# from /native, so name the one next to it
	libclang=$(readlink -f /native/usr/lib/libclang.so)
	resource=$(ls -d "${libclang%/*}"/clang/* | tail -n 1)
	export BINDGEN_EXTRA_CLANG_ARGS="--target=@HOSTSPEC@ -resource-dir=$resource $BINDGEN_EXTRA_CLANG_ARGS"
	export LIBCLANG_PATH=/native/usr/lib
	LD_LIBRARY_PATH=/native/lib:/native/usr/lib exec /native/usr/bin/bindgen "$@"
fi

exec /usr/bin/bindgen "$@"
