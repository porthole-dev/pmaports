#!/usr/bin/env bash
# Generated with the reviewed release policy. Requires no Python.
set -euo pipefail
DEVICE='@DEVICE@'
EXPECTED_PRODUCT='@PRODUCT@'
SLOT='@SLOT@'
DTBO='@DTBO@'
FASTBOOT=${FASTBOOT:-fastboot}
dry=false
case ${1:-} in --dry-run) dry=true;; '') ;; *) echo 'Usage: bash install.sh [--dry-run]' >&2; exit 1;; esac
cd -- "$(dirname -- "$0")"
if command -v sha256sum >/dev/null; then
  sha256sum -c NATIVE-SHA256SUMS
else
  shasum -a 256 -c NATIVE-SHA256SUMS
fi
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
gzip -dc -- "$DEVICE.img.gz" > "$work/rootfs.img"
if "$dry"; then
  echo "Verified $DEVICE. Would flash userdata, boot_$SLOT, DTBO=$DTBO, select slot $SLOT and reboot. No device contacted."
  exit 0
fi
connected=$("$FASTBOOT" devices)
count=$(printf '%s\n' "$connected" | awk 'NF {n++} END {print n+0}')
[ "$count" = 1 ] || { echo 'Connect exactly one phone in bootloader fastboot mode.' >&2; exit 1; }
serial=$(printf '%s\n' "$connected" | awk '$2 == "fastboot" {print $1}')
[ -n "$serial" ] || { echo 'Phone is not in fastboot mode.' >&2; exit 1; }
getvar() {
  local output
  output=$("$FASTBOOT" -s "$serial" getvar "$1" 2>&1)
  printf '%s\n' "$output" | sed -nE "s/^(\\(bootloader\\)[[:space:]]*)?$1:[[:space:]]*([^[:space:]]+).*$/\\2/p"
}
[ "$(getvar product)" = "$EXPECTED_PRODUCT" ] || { echo 'Wrong phone model.' >&2; exit 1; }
[ "$(getvar unlocked)" = yes ] || { echo 'Unlock the bootloader using the device guide first.' >&2; exit 1; }
printf 'Experimental image. Replaces the OS and ERASES ALL USER DATA. Back up first.\nType %s to install: ' "$DEVICE"
read -r answer
[ "$answer" = "$DEVICE" ] || { echo 'Cancelled; no writes performed.' >&2; exit 1; }
"$FASTBOOT" -s "$serial" flash userdata "$work/rootfs.img"
"$FASTBOOT" -s "$serial" flash "boot_$SLOT" boot.img
if [ "$DTBO" = true ]; then "$FASTBOOT" -s "$serial" flash "dtbo_$SLOT" dtbo.img; fi
"$FASTBOOT" -s "$serial" set_active "$SLOT"
"$FASTBOOT" -s "$serial" reboot
