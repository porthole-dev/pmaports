#!/usr/bin/env python3
"""Exercise the real executable ZIP with fake fastboot; no device writes."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

spec = importlib.util.spec_from_file_location('bundle', '.github/scripts/bundle.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    policy = json.loads(Path('.github/image-devices.json').read_text())['google-taimen']
    files = {'google-taimen.img.gz': gzip.compress(b'rootfs'), 'boot.img': b'boot',
             'device.json': json.dumps(dict(device='google-taimen', dtbo_sha256=policy['dtbo_sha256'])).encode(),
             'INSTALL.md': b'instructions', 'pmaports.commit': b'a' * 40, 'pmbootstrap.commit': b'b' * 40}
    # Fixture uses a reviewed overlay checksum, so temporarily copy policy/script.
    old = Path.cwd()
    (root / '.github/scripts').mkdir(parents=True)
    fixture = dict(policy, dtbo_sha256=hashlib.sha256(b'overlay').hexdigest())
    (root / '.github/image-devices.json').write_text(json.dumps({'google-taimen': fixture}))
    (root / '.github/scripts/install-bundle.py').write_bytes(Path('.github/scripts/install-bundle.py').read_bytes())
    files['device.json'] = json.dumps(dict(device='google-taimen', dtbo_sha256=fixture['dtbo_sha256'])).encode()
    files['dtbo.img'] = b'overlay'
    assets = root / 'assets'; assets.mkdir()
    for name, data in files.items(): (assets / name).write_bytes(data)
    (assets / 'SHA256SUMS').write_text(''.join(hashlib.sha256(data).hexdigest() + '  ./' + name + '\n' for name, data in files.items()))
    os.chdir(root)
    bundle = module.build(assets, 'google-taimen')
    os.chdir(old)
    fake = root / 'fastboot'
    log = root / 'writes'
    fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['devices']:
 print('fixture fastboot')
 if os.environ.get('MULTIPLE'): print('second fastboot')
elif args[2] == 'getvar':
 key = args[3]
 print('(bootloader) ' + key + ': ' + (os.environ.get('PRODUCT', 'taimen') if key == 'product' else os.environ.get('UNLOCKED', 'yes')), file=sys.stderr)
else:
 with Path(os.environ['WRITES']).open('a') as output: output.write(json.dumps(args[2:4]) + '\\n')
 if os.environ.get('FAIL') and args[2:4] == ['flash', 'boot_b']: sys.exit(1)
''')
    fake.chmod(0o755)
    def run(expected=True, text='google-taimen\n', extra=None, dry=False):
        if log.exists(): log.unlink()
        env = dict(os.environ, WRITES=str(log)); env.update(extra or {})
        command = [sys.executable, str(bundle), '--fastboot', str(fake)] + (['--dry-run'] if dry else [])
        result = subprocess.run(command, input=text, text=True, capture_output=True, env=env)
        assert (result.returncode == 0) == expected, result.stderr
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert run(dry=True) == []
    assert run() == [['flash', 'userdata'], ['flash', 'boot_b'], ['flash', 'dtbo_b'], ['set_active', 'b'], ['reboot']]
    for extra in [{'PRODUCT': 'walleye'}, {'UNLOCKED': 'no'}, {'MULTIPLE': '1'}]:
        assert run(False, extra=extra) == []
    assert run(False, text='cancel\n') == []
    assert run(False, extra={'FAIL': '1'}) == [['flash', 'userdata'], ['flash', 'boot_b']]
    corrupt = root / 'corrupt.zip'
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(corrupt, 'w') as target:
        for name in source.namelist(): target.writestr(name, b'bad boot' if name == 'boot.img' else source.read(name))
    bundle = corrupt
    assert run(False) == []
print('bundle controls: valid install; dry-run, wrong model, locked/multiple devices, cancellation, corrupt image and failed-write stop passed')
