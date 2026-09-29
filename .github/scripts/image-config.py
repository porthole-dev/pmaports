#!/usr/bin/env python3
"""Resolve a reviewed device image configuration into shell-safe values."""
import json
import pathlib
import shlex
import sys

config = json.loads(pathlib.Path(".github/image-devices.json").read_text())
device = config[sys.argv[1]]
for field in ("kernel", "ui", "init", "install_guide", "boot_dtb", "boot_kernel"):
    print("IMAGE_" + field.upper() + "=" + shlex.quote(device[field]))
print("IMAGE_EXTRA=" + shlex.quote(",".join(device["extra_packages"])))
print("IMAGE_DTBO_SHA256=" + shlex.quote(device.get("dtbo_sha256", "")))
pathlib.Path("/work/image-config.json").write_text(json.dumps(dict(device=sys.argv[1], **device), indent=2) + "\n")
