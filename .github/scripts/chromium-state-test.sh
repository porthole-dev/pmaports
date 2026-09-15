#!/bin/bash
# chromium-state-test.sh -- chromium-state.sh against a fake gh and a fake
# work directory: prep, two stages, restore, and a corrupted part. Runs in a
# second, so the layering can be checked without a 6 hour build.
#
#   sh .github/scripts/chromium-state-test.sh
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
mkdir -p "$t/bin" "$t/rel" "$t/work/chromium"
out=$t/work/chroot_native/home/pmos/build/src/chromium-1/out/bld
mkdir -p "$out" "$t/work/cache_apk_aarch64"

# gh: releases are directories under $t/rel. sudo: not needed here.
cat > "$t/bin/gh" <<EOF
#!/bin/bash
rel=$t/rel
case "\$1 \$2" in
"release view") [ -d "\$rel/\$3" ] ;;
"release create") mkdir -p "\$rel/\$3"; echo "https://example/\$3" >&2 ;;
"release upload") cp "\$4" "\$rel/\$3/" ;;
"release download")
	tag=\$3; shift 3
	while [ \$# -gt 0 ]; do case \$1 in -p) p=\$2; shift ;; -O) o=\$2; shift ;; esac; shift; done
	[ -f "\$rel/\$tag/\$p" ] || exit 1
	if [ "\$o" = - ]; then cat "\$rel/\$tag/\$p"; else cp "\$rel/\$tag/\$p" "\$o"; fi ;;
"release delete-asset") rm -f "\$rel/\$3/\$4" ;;
*) echo "fake gh: \$*" >&2; exit 1 ;;
esac
EOF
printf '#!/bin/sh\nexec "$@"\n' > "$t/bin/sudo"
chmod +x "$t/bin/gh" "$t/bin/sudo"
export PATH=$t/bin:$PATH GITHUB_REPOSITORY=test/repo GITHUB_SERVER_URL=https://example \
	GITHUB_RUN_ID=1 RUNNER_TEMP=$t/tmp PART_SIZE=1M

result() { # mode records_after done stopped
	cat > "$t/work/chromium/result.json" <<EOF
{"mode": "$1", "records_before": 0, "rebuilt": 0, "ok": true, "returncode": 0,
 "stopped": $4, "done": $3, "records_after": $2,
 "out_dir": "chroot_native/home/pmos/build/src/chromium-1/out/bld"}
EOF
}
state() { bash "$here/chromium-state.sh" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

# prep: a work directory with a cache to leave out and a source tree to keep
head -c 3000000 /dev/urandom > "$t/work/chroot_native/toolchain"
head -c 1000000 /dev/urandom > "$t/work/cache_apk_aarch64/junk.apk"
echo 'source' > "$t/work/chroot_native/home/pmos/build/src/chromium-1/BUILD.gn"
printf '# ninja log v7\n0\t0\t1\ta.o\t1\n' > "$out/.ninja_log"
result prep 1 false null
state save TAG "$t/work" > /dev/null

# two stages, each with one more record
printf '0\t0\t2\tb.o\t2\n' >> "$out/.ninja_log"
result build 2 false '"stage deadline"'
state save TAG "$t/work" > /dev/null
printf '0\t0\t3\tc.o\t3\n' >> "$out/.ninja_log"
result build 3 true null
state save TAG "$t/work" > /dev/null

[ "$(state manifest TAG | jq -r '.stage, .records, .done')" = "$(printf '2\n3\ntrue')" ] ||
	fail "the manifest does not describe two stages"
[ ! -e "$t/rel/TAG/out-1.tar.zst.000" ] || fail "the superseded out layer is still there"
[ -e "$t/rel/TAG/out-2.tar.zst.000" ] || fail "the newest out layer is missing"

# restore into an empty directory
state restore TAG "$t/restored" > /dev/null
cmp "$t/work/chroot_native/toolchain" "$t/restored/chroot_native/toolchain" ||
	fail "the restored chroot differs"
cmp "$out/.ninja_log" "$t/restored/${out#"$t/work/"}/.ninja_log" ||
	fail "the restored ninja log differs"
[ ! -s "$t/restored/cache_apk_aarch64/junk.apk" ] || fail "a cache was stored"
[ -d "$t/restored/cache_apk_aarch64" ] || fail "the cache directory is gone"
[ ! -f "$t/restored/chromium/result.json" ] || fail "a stale result was restored"

# a damaged part is refused
printf 'x' | dd of="$(ls "$t"/rel/TAG/prep.tar.zst.000)" bs=1 seek=100 conv=notrunc status=none
if state restore TAG "$t/damaged" > /dev/null 2>&1; then
	fail "a corrupted part was restored"
fi

echo "chromium-state.sh: prep, two stages, restore and corruption all behave"
