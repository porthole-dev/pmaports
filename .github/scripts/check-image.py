#!/usr/bin/env python3
"""Check the packaged Taimen rootfs before publishing an experimental image."""
import hashlib
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
installed = {}
for entry in (root / "lib/apk/db/installed").read_text().split("\n\n"):
    fields = dict(line.split(":", 1) for line in entry.splitlines() if ":" in line)
    if "P" in fields:
        installed[fields["P"]] = fields.get("V")
for aport in ("device/testing/device-google-taimen", "device/testing/firmware-google-taimen",
              "device/testing/linux-postmarketos-qcom-msm8998-7.2", "temp/gnome-control-center"):
    text = (pathlib.Path(aport) / "APKBUILD").read_text()
    version = re.search(r"(?m)^pkgver=(\S+)", text)[1]
    release = re.search(r"(?m)^pkgrel=(\d+)", text)[1]
    name = pathlib.Path(aport).name
    expected = version + "-r" + release
    if installed.get(name) != expected:
        raise SystemExit(f"{name}: installed {installed.get(name)}, expected {expected}")
for name in ("neard", "phosh-nfc-quick-setting", "tap", "obscura"):
    if name not in installed:
        raise SystemExit("missing release package: " + name)
for name in ("mba.mbn", "modem.mbn", "modemr.jsn"):
    if not (root / "lib/firmware/qcom/msm8998/wahoo" / name).is_file():
        raise SystemExit("missing modem firmware: " + name)
for path in list((root / "home").rglob("authorized_keys")) + list((root / "root").rglob("authorized_keys")):
    if path.stat().st_size:
        raise SystemExit("image contains a build-host SSH key")
dtbo = root / "boot/dtbo.img"
if hashlib.sha256(dtbo.read_bytes()).hexdigest() != "fd9752b381403312bcdeda8bb8555f0ad964f3464e7bc4ed307e3cef018362da":
    raise SystemExit("DTBO does not match the verified mainline overlay")
print("rootfs: release versions, NFC packages, modem firmware, SSH keys, and DTBO checked")
