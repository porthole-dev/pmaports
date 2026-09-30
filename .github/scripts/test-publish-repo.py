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
    verifier=root/'bin/apk'
    verifier.write_text(verifier.read_text().replace('exit 0',
        '[ "$1" != verify ] || [ -z "${REJECT_APK:-}" ] || exit 1\nexit 0'))
    env['REJECT_APK']='1'
    apk(root/'new/bad-1-r0.apk','1-r0',pkg='bad')
    def rejected(): return subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True)
    assert rejected().returncode != 0
    assert not (root/'repo/bad-1-r0.apk').exists()
    env.pop('REJECT_APK')
    (root/'new/bad-1-r0.apk').unlink()
    # A retained malformed candidate must leave the index, while valid history stays.
    apk(root/'repo/bad-1-r0.apk','1-r0',pkg='bad')
    text=verifier.read_text().replace('[ -z "${REJECT_APK:-}" ]',
        '[ "${3##*/}" != bad-1-r0.apk ]')
    verifier.write_text(text)
    assert rejected().returncode == 0
    assert not (root/'repo/bad-1-r0.apk').exists()
    assert 'bad-1-r0.apk' in (root/'repo/.remove').read_text()
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

# Every publishing lane must use the same fail-closed download/payload checks.
workflows = SCRIPT.parents[1] / 'workflows'
for name in ('build.yml', 'chromium.yml'):
    workflow = (workflows / name).read_text()
    assert 'sh .github/scripts/publish.sh "$RUNNER_TEMP/packages"' in workflow, name
    assert "subject-checksums: ${{ runner.temp }}/uploaded.sha256" in workflow, name
    assert "2>/dev/null || true" not in workflow, name
print('core and Chromium share the verified publisher and attestation contract')

# Exercise the actual index/assets comparison: matching, orphaned and empty.
outer = SCRIPT.with_name('publish.sh').read_text()
comparison = outer.split('# that orphaned-asset state even when every retried APK is identical.\n', 1)[1]
comparison = comparison.split('\t\tfor origin in ', 1)[0]
with tempfile.TemporaryDirectory() as tmp:
    check = pathlib.Path(tmp)
    def index(records):
        with tarfile.open(check/'APKINDEX.tar.gz', 'w:gz') as archive:
            data=records.encode(); member=tarfile.TarInfo('APKINDEX'); member.size=len(data)
            archive.addfile(member, io.BytesIO(data))
    index('P:example\nV:2-r0\n\n')
    for assets, expected in [('APKINDEX.tar.gz\nexample-2-r0.apk\n', ''),
                              ('APKINDEX.tar.gz\nexample-2-r0.apk\nexample-3-r0.apk\n', '1')]:
        (check/'before').write_text(assets)
        result=subprocess.run(['sh','-ec', comparison+'\nprintf %s "$reindex"'],
            env=dict(os.environ,check=str(check),reindex=''),capture_output=True,text=True,check=True)
        assert result.stdout == expected
    index(''); (check/'before').write_text('APKINDEX.tar.gz\n')
    result=subprocess.run(['sh','-ec',comparison+'\nprintf %s "$reindex"'],
        env=dict(os.environ,check=str(check),reindex=''),capture_output=True,text=True,check=True)
    assert result.stdout == ''
print('publication retry: matching/empty indexes retained; orphaned assets reindexed')
