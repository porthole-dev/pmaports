#!/usr/bin/env python3
"""Run an executable release ZIP. No downloads, dependencies or host privilege."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='verify files and print writes; do not contact a device')
    parser.add_argument('--fastboot', default='fastboot', help='Android platform-tools fastboot executable')
    args = parser.parse_args()
    with zipfile.ZipFile(sys.argv[0]) as archive, tempfile.TemporaryDirectory(prefix='porthole-install-') as temporary:
        directory = Path(temporary)
        manifest = json.loads(archive.read('bundle.json'))
        device = manifest['device']
        product = manifest['product']
        slot = manifest['slot']
        if not re.fullmatch(r'[a-z0-9-]+', device) or not re.fullmatch(r'[a-z0-9_-]+', product) or slot not in ('a', 'b'):
            raise ValueError('Invalid reviewed device policy')
        # Stream only named, checksummed members; never extract archive paths.
        for name, expected in manifest['sha256'].items():
            if Path(name).name != name or not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ValueError('Invalid bundle checksum entry')
            digest = hashlib.sha256()
            with archive.open(name) as source, (directory / name).open('wb') as target:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
                    target.write(block)
            if digest.hexdigest() != expected:
                raise ValueError('Checksum mismatch: ' + name)
        required = {device + '.img.gz', 'boot.img'}
        if manifest['dtbo']:
            required.add('dtbo.img')
        if not required <= manifest['sha256'].keys():
            raise ValueError('Missing required installation image')
        print('Verified bundle for ' + device, flush=True)
        rootfs = directory / (device + '.img')
        with gzip.open(directory / (device + '.img.gz'), 'rb') as source, rootfs.open('wb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        writes = [['flash', 'userdata', str(rootfs)], ['flash', 'boot_' + slot, str(directory / 'boot.img')]]
        if manifest['dtbo']:
            writes.append(['flash', 'dtbo_' + slot, str(directory / 'dtbo.img')])
        writes += [['set_active', slot], ['reboot']]
        if args.dry_run:
            for command in writes:
                print('fastboot ' + ' '.join(command))
            return
        def fastboot(command, timeout=30):
            result = subprocess.run([args.fastboot] + command, capture_output=True, text=True, timeout=timeout, check=True)
            return result.stdout + result.stderr
        connected = [line.split() for line in fastboot(['devices']).splitlines() if line.strip()]
        if len(connected) != 1 or len(connected[0]) < 2 or connected[0][1] != 'fastboot':
            raise ValueError('Connect exactly one phone in bootloader fastboot mode')
        # Pin every subsequent operation to the device that passed preflight.
        serial = connected[0][0]
        def getvar(name):
            output = fastboot(['-s', serial, 'getvar', name])
            match = re.search(r'(?:^|\n)(?:\(bootloader\)\s*)?' + re.escape(name) + r':\s*(\S+)', output)
            if not match:
                raise ValueError('Bootloader did not report ' + name)
            return match.group(1)
        if getvar('product') != product:
            raise ValueError('Wrong device: expected ' + product)
        if getvar('unlocked') != 'yes':
            raise ValueError('Unlock the bootloader using the device guide first')
        print('WARNING: this replaces the operating system and ERASES ALL USER DATA. Back up first.\n'
              'Experimental image; exact-image hardware qualification is separate.\n'
              'Target: ' + device + ', reviewed slot ' + slot + '.', flush=True)
        if input('Type ' + device + ' to install: ').strip() != device:
            raise ValueError('Installation cancelled; no writes performed')
        for command in writes:
            print('Running fastboot ' + ' '.join(command[:2]), flush=True)
            # Stop immediately on a failed write. Never reboot into partial images.
            print(fastboot(['-s', serial] + command, timeout=1800), end='', flush=True)
        print('Installation complete. Change the initial password after login.')


if __name__ == '__main__':
    try:
        run()
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print('Installation stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
