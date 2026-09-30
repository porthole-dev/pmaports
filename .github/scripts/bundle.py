#!/usr/bin/env python3
"""Package verified existing image assets, preserving their bytes and provenance."""
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build(directory, device):
    policy = json.loads(Path('.github/image-devices.json').read_text())[device]
    if policy.get('fastboot_product') is None or policy.get('install_slot') not in ('a', 'b'):
        raise ValueError('Device has no reviewed installation policy')
    published = json.loads((directory / 'device.json').read_text())
    if published['device'] != device or published.get('dtbo_sha256') != policy.get('dtbo_sha256'):
        raise ValueError('Release does not match the reviewed device policy')
    hashes = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name[2:] if name.startswith('./') else name
        if Path(name).name != name or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid release checksum entry')
        if sha256(directory / name) != digest:
            raise ValueError('Release checksum mismatch: ' + name)
        hashes[name] = digest
    required = {device + '.img.gz', 'boot.img', 'device.json', 'INSTALL.md', 'pmaports.commit', 'pmbootstrap.commit'}
    if policy.get('dtbo_sha256'):
        required.add('dtbo.img')
        if hashes.get('dtbo.img') != policy['dtbo_sha256']:
            raise ValueError('Wrong DTBO')
    if not required <= hashes.keys():
        raise ValueError('Incomplete release')
    installer = Path('.github/scripts/install-bundle.py')
    hashes['SHA256SUMS'] = sha256(directory / 'SHA256SUMS')
    manifest = dict(device=device, product=policy['fastboot_product'], slot=policy['install_slot'],
                    dtbo=bool(policy.get('dtbo_sha256')), sha256=hashes)
    bundle = directory / (device + '-install.zip')
    # Images are already compressed; ZIP_STORED avoids another costly compression.
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.write(installer, '__main__.py')
        archive.writestr('bundle.json', json.dumps(manifest, indent=2) + '\n')
        for name in hashes:
            archive.write(directory / name, name)
    (directory / 'BUNDLE-SHA256SUMS').write_text(sha256(bundle) + '  ' + bundle.name + '\n')
    print(bundle)
    return bundle


if __name__ == '__main__':
    build(Path(sys.argv[1]), sys.argv[2])
