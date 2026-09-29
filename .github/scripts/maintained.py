"""Validate the generated maintenance inventory before an audit can say clean."""
import json
import pathlib
import re


def load(root):
    root = pathlib.Path(root)
    data = json.loads((root / '.github/maintained-aports.json').read_text())
    if data.get('schema') != 1 or not data.get('inputs') or not data.get('packages'):
        raise ValueError('empty or unsupported maintained inventory')
    names = set()
    for item in data['packages']:
        name, rel = item['name'], pathlib.PurePosixPath(item['path'])
        if (not re.fullmatch(r'[a-z0-9][a-z0-9._+-]*', name)
                or rel.is_absolute() or '..' in rel.parts or rel.name != name
                or name in names or not item.get('why') or not item.get('owners')):
            raise ValueError('invalid maintained aport: ' + name)
        if not (root / rel / 'APKBUILD').is_file():
            raise ValueError('maintained aport missing: ' + str(rel))
        names.add(name)
    return names
