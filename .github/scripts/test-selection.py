#!/usr/bin/env python3
"""Run the production selector with deterministic repository/index inputs."""
import ast
import json
import os
import pathlib
import re
import tempfile
import types
import io
import tarfile
from unittest.mock import patch

source = pathlib.Path(__file__).with_name('packages.py').read_text()
excluded_node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'excluded')
gate = dict(os=os)
exec(compile(ast.Module(body=[excluded_node], type_ignores=[]), 'packages.py', 'exec'), gate)
with patch.dict(os.environ, {}, clear=True):
    assert gate['excluded']('firmware-google-taimen')
    os.environ['FIRMWARE_GRANT_TAIMEN'] = 'approved'
    assert not gate['excluded']('firmware-google-taimen')
    assert not gate['excluded']('firmware-google-taimen-fingerprint')
    assert gate['excluded']('firmware-other')
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'cmd_select')
class Arch:
    aarch64 = 'aarch64'
    @staticmethod
    def from_arch_field(value):
        return value

with tempfile.TemporaryDirectory() as tmp:
    work = pathlib.Path(tmp)
    compare = lambda a, b: (int(a.rsplit("r", 1)[1]) > int(b.rsplit("r", 1)[1])) - (int(a.rsplit("r", 1)[1]) < int(b.rsplit("r", 1)[1]))
    pmb = types.SimpleNamespace(parse=types.SimpleNamespace(version=types.SimpleNamespace(compare=compare)))
    scope = dict(pmb=pmb, io=io, tarfile=tarfile, os=os, re=re, json=json, WORK=work, MAX_JOBS=200, ARCH='aarch64', Arch=Arch,
                 tiers=lambda: {}, published=lambda: {'sample': '1-r0'}, changed=lambda: {'sample'},
                 forks=lambda: {'sample'}, resolve=lambda names: [(n, n) for n in sorted(names)],
                 version=lambda d: '1-r0', apkbuild=lambda d: {'arch': ['aarch64']},
                 unavailable_source=lambda *a: False, aport_dir=lambda n: n if n == 'sample' else None,
                 excluded=lambda n: False)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'packages.py', 'exec'), scope)
    with patch.dict(os.environ, {}, clear=True):
        assert scope['cmd_select']() == 1  # changed contents cannot reuse an immutable version
        scope['version'] = lambda d: '1-r1'
        assert scope['cmd_select']() == 0
        assert json.loads((work/'matrix.json').read_text()) == ['sample']
        scope['published'] = lambda: None
        assert scope['cmd_select']() == 1  # no surprise rebuild on index failure
        scope['published'] = lambda: {}
        scope['unavailable_source'] = lambda *a: True
        assert scope['cmd_select']() == 1
        scope['unavailable_source'] = lambda *a: False
        os.environ['PACKAGES'] = 'missing'
        assert scope['cmd_select']() == 1
        os.environ['PACKAGES'] = 'sample'
        scope['published'] = lambda: {'sample': '1-r1'}
        assert scope['cmd_select']() == 0
        assert json.loads((work/'matrix.json').read_text()) == []
print('selection controls passed')

# Retained APK versions may appear in any index order.
index_node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'read_index')
exec(compile(ast.Module(body=[index_node], type_ignores=[]), 'packages.py', 'exec'), scope)
for data in (b'P:sample\nV:1-r10\n\nP:sample\nV:1-r2\n', b'P:sample\nV:1-r2\n\nP:sample\nV:1-r10\n'):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        info = tarfile.TarInfo('APKINDEX'); info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    assert scope['read_index'](stream.getvalue()) == {'sample': '1-r10'}
print('retained versions: highest version independent of index order')

patch_node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'cmd_check_patches')
exec(compile(ast.Module(body=[patch_node], type_ignores=[]), 'packages.py', 'exec'), scope)
calls = []
scope.update(is_systemd=lambda d: False, use_systemd=lambda value: None,
             pmbootstrap=lambda *args: calls.append(args),
             apkbuild=lambda d: {key: [] for key in ('makedepends','makedepends_build','makedepends_host','checkdepends')})
with patch.dict(os.environ, {}, clear=True):
    scope['unavailable_source'] = lambda *a: True
    assert scope['cmd_check_patches'](True) == 1 and not calls
    scope['unavailable_source'] = lambda *a: False
    assert scope['cmd_check_patches'](True) == 0
    assert ('checksum', '--verify', 'sample') in calls
print('patch checks: unavailable sources fail; available source reaches verification')
