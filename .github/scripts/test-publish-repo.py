#!/usr/bin/env python3
"""Exercise the actual publisher with local APK fixtures and fake signing tools."""
import io
import os
import pathlib
import subprocess
import tarfile
import tempfile

SCRIPT = pathlib.Path(__file__).with_name('publish-repo.sh').resolve()

def apk(path, version, payload=b'content', pkg='example', files=(), origin=None):
    with tarfile.open(path,'w:gz') as t:
        info = ('pkgname = '+pkg+'\npkgver = '+version+'\norigin = '+(origin or pkg)+'\npackager = Test\n').encode()
        for name, data in (('.PKGINFO',info),('usr/file',payload), *files):
            entry=tarfile.TarInfo(name); entry.size=len(data); t.addfile(entry,io.BytesIO(data))

with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp)
    for d in ('repo','new','keys','pubkeys','trusted','bin'): (root/d).mkdir()
    (root/'pubkeys/test.pub').touch()
    for name, text in {'apk':'#!/bin/sh\n[ "$1" != index ] || touch APKINDEX.tar.gz\nexit 0\n',
                       'abuild-sign':'#!/bin/sh\nexit 0\n'}.items():
        p=root/'bin'/name; p.write_text(text); p.chmod(0o755)
    env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH'],ARCH='aarch64',KEY='test',PACKAGER='Test',DESCRIPTION='fixture',
        **{k:str(root/v) for k,v in {'REPO_DIR':'repo','NEW_DIR':'new','KEYS_DIR':'keys','PUBKEYS_DIR':'pubkeys','TRUSTED_DIR':'trusted'}.items()})
    apk(root/'repo/example-1-r0.apk','1-r0')
    apk(root/'new/example-2-r0.apk','2-r0')
    def run(): return subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True)
    result=run(); assert result.returncode == 0,result.stderr
    assert (root/'repo/example-1-r0.apk').exists(), 'deleted an APK referenced by old indexes'
    assert not (root/'repo/.remove').read_text()
    apk(root/'new/example-2-r0.apk','2-r0',b'changed bytes')
    result=run(); assert result.returncode != 0 and 'different bytes' in result.stderr
    (root/'new/example-2-r0.apk').unlink()
    apk(root/'new/firmware-google-taimen-1-r0.apk','1-r0',pkg='firmware-google-taimen')
    result=run(); assert result.returncode != 0 and 'firmware grant not enabled' in result.stderr
    env['FIRMWARE_GRANT_TAIMEN']='approved'
    result=run(); assert result.returncode == 0,result.stderr
    (root/'new/firmware-google-taimen-1-r0.apk').unlink()
    apk(root/'new/firmware-google-taimen-fingerprint-1-r0.apk','1-r0',
        pkg='firmware-google-taimen-fingerprint',origin='firmware-google-taimen',
        files=(('lib/firmware/qcom/fingerprint.mdt',b'blob'),))
    result=run(); assert result.returncode == 0,result.stderr
    (root/'new/firmware-google-taimen-fingerprint-1-r0.apk').unlink()
    apk(root/'new/firmware-other-1-r0.apk','1-r0',pkg='firmware-other')
    result=run(); assert result.returncode != 0 and 'firmware grant not enabled' in result.stderr
    (root/'new/firmware-other-1-r0.apk').unlink()
    apk(root/'new/example-3-r0.apk','3-r0',files=(('usr/lib/firmware/vendor/blob',b'blob'),))
    result=run(); assert result.returncode != 0 and 'lib/firmware' in result.stderr
print('publisher: immutable APKs; Taimen firmware gated; other firmware refused')
