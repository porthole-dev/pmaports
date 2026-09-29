#!/usr/bin/env python3
import json
import pathlib
import tempfile
from maintained import load

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    (root/'.github').mkdir()
    (root/'temp/example').mkdir(parents=True)
    (root/'temp/example/APKBUILD').touch()
    data = {'schema':1, 'inputs':{'profile':'hash'}, 'packages':[
        {'name':'example','path':'temp/example','owners':['test'],'why':'test fork'}]}
    file = root/'.github/maintained-aports.json'
    file.write_text(json.dumps(data))
    assert load(root) == {'example'}  # no .git and no upstream network needed
    for path in ('../example','/example','temp/missing'):
        data['packages'][0]['path'] = path
        file.write_text(json.dumps(data))
        try:
            load(root)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted bad inventory')
print('maintained inventory: validates checkout without git ancestry')
