#!/usr/bin/env python3
"""Check the configured device rootfs before publishing an experimental image."""
import hashlib
import json
import pathlib
import sys

import pmb.parse
import pmb.helpers.logging

pmb.helpers.logging.add_verbose_log_level()

root = pathlib.Path(sys.argv[1])
installed = {}
for entry in (root / "lib/apk/db/installed").read_text().split("\n\n"):
    fields = dict(line.split(":", 1) for line in entry.splitlines() if ":" in line)
    if "P" in fields:
        installed[fields["P"]] = fields.get("V")
device = json.loads(pathlib.Path(".github/image-devices.json").read_text())[sys.argv[2]]
for aport in device["required_aports"]:
    recipe = pmb.parse.apkbuild(pathlib.Path(aport) / "APKBUILD", False, False)
    name = recipe["pkgname"]
    expected = recipe["pkgver"] + "-r" + str(recipe["pkgrel"])
    if installed.get(name) != expected:
        raise SystemExit(f"{name}: installed {installed.get(name)}, expected {expected}")
for name in device["required_packages"]:
    if name not in installed:
        raise SystemExit("missing release package: " + name)
for name in device["firmware_files"]:
    if not (root / name).is_file():
        raise SystemExit("missing firmware: " + name)
for path in list((root / "home").rglob("authorized_keys")) + list((root / "root").rglob("authorized_keys")):
    if path.stat().st_size:
        raise SystemExit("image contains a build-host SSH key")
dtbo = root / "boot/dtbo.img"
if device.get("dtbo_sha256") and hashlib.sha256(dtbo.read_bytes()).hexdigest() != device["dtbo_sha256"]:
    raise SystemExit("DTBO does not match the verified mainline overlay")
print("rootfs: release versions, NFC packages, modem firmware, SSH keys, and DTBO checked")
