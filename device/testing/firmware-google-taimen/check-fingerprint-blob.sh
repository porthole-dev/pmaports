#!/bin/sh
# Assert the fingerprint subpackage ships the trustlet, whole.
# Usage: check-fingerprint-blob.sh <path to firmware-google-taimen-fingerprint apk>
set -e
apk="$1"
[ -f "$apk" ] || { echo "FAIL: no apk at $apk"; exit 1; }
dir=$(mktemp -d)
tar -xzf "$apk" -C "$dir" 2>/dev/null || true
fw="$dir/lib/firmware/qcom/msm8998/taimen"
total=0
for f in mdt b00 b01 b02 b03 b04 b05 b06 b07; do
	p="$fw/fpctzappfingerprint.$f"
	[ -f "$p" ] || { echo "FAIL: missing fpctzappfingerprint.$f"; exit 1; }
	total=$((total + $(stat -c %s "$p")))
done
[ "$total" = 603649 ] || { echo "FAIL: trustlet is $total bytes, want 603649"; exit 1; }
head -c 4 "$fw/fpctzappfingerprint.mdt" | grep -q 'ELF' || \
	{ echo "FAIL: .mdt is not an ELF"; exit 1; }
echo "OK: trustlet ships whole, 603649 bytes"
