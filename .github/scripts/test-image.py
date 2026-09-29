#!/usr/bin/env python3
"""Exercise image validation with a valid rootfs and rejected release drift."""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

import pmb.helpers.logging
import pmb.parse

pmb.helpers.logging.add_verbose_log_level()
checkout = pathlib.Path.cwd()
script = checkout / '.github/scripts/check-image.py'
configs = json.loads((checkout / '.github/image-devices.json').read_text())
for name, original in configs.items():
    with tempfile.TemporaryDirectory() as directory:
        work = pathlib.Path(directory)
        root = work / 'root'
        (work / '.github').mkdir()
        config = dict(original, dtbo_sha256=hashlib.sha256(b'overlay').hexdigest())
        (work / '.github/image-devices.json').write_text(json.dumps({name: config}))
        records = []
        for aport in config['required_aports']:
            path = work / aport
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(checkout / aport, target_is_directory=True)
            recipe = pmb.parse.apkbuild(path / 'APKBUILD', False, False)
            records.append('P:' + recipe['pkgname'] + '\nV:' + recipe['pkgver'] + '-r' + str(recipe['pkgrel']))
        records += ['P:' + package + '\nV:1-r0' for package in config['required_packages'] if not any(row.startswith('P:' + package + '\n') for row in records)]
        installed = root / 'lib/apk/db/installed'
        installed.parent.mkdir(parents=True)
        installed.write_text('\n\n'.join(records))
        for filename in config['firmware_files'] + ['boot/dtbo.img']:
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'overlay')
        command = [sys.executable, str(script), str(root), name]
        def check(expected):
            result = subprocess.run(command, cwd=work, capture_output=True)
            assert (result.returncode == 0) == expected, result.stderr.decode()
        check(True)
        installed.write_text('\n\n'.join(records).replace('-r', '-r999', 1))
        check(False)
        installed.write_text('\n\n'.join(records))
        (root / 'boot/dtbo.img').write_bytes(b'wrong overlay')
        check(False)
        (root / 'boot/dtbo.img').write_bytes(b'overlay')
        keys = root / 'home/user/.ssh/authorized_keys'
        keys.parent.mkdir(parents=True)
        keys.write_text('build-host key')
        check(False)
print('image controls: valid rootfs accepted; stale package, wrong DTBO and host key rejected')
