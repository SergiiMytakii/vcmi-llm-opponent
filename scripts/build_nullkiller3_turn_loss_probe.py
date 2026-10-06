"""Install a private lifecycle probe, then restore the prepared production source.

Normal prepare_engine and normal installed bundles never include this driver.
Run only against the task-owned prepared NK3 checkout and build directory.
"""
import difflib
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='nk3-turn-loss-probe')
    parser.add_argument('--probe',choices=('turn-loss','garrison','critical-events'),default='turn-loss')
    args=parser.parse_args()
    if not args.name.startswith('nk3-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.name):
        parser.error('--name must be a lowercase nk3- name')
    source=ROOT/'.build/vcmi-nk3'
    factory=source/'lib/callback/AIFactory.cpp'
    probe_class={'turn-loss':'TurnLossProbe','garrison':'GarrisonProbe','critical-events':'CriticalEventsProbe'}[args.probe]
    fixture=ROOT/'tests/fixtures'/f'nullkiller3_{args.probe.replace("-","_")}_probe.h'
    target=source/'AI/Nullkiller3'/f'{probe_class}.h'
    original=factory.read_text()
    if target.exists() or any(name in original for name in ('TurnLossProbe','GarrisonProbe','CriticalEventsProbe')):
        raise RuntimeError('a lifecycle fixture is already present; preserve it for inspection')
    include='#  include "../../AI/Nullkiller2/AIGateway.h"'
    construction='\t\tauto ret = std::make_shared<NK2AI::AIGateway>(name == "Nullkiller3");'
    if original.count(include)!=1 or original.count(construction)!=1:
        raise RuntimeError('prepared factory does not match the pinned NK3 integration')
    changed=original.replace(include,include+f'\n#  include "../../AI/Nullkiller3/{probe_class}.h"')
    changed=changed.replace(construction,
        '\t\tif(name == "Nullkiller3")\n\t\t{\n'
        f'\t\t\tauto probe=std::make_shared<nullkiller3::{probe_class}>();\n'
        '\t\t\tprobe->dllName=name; return probe;\n\t\t}\n'+construction)
    evidence=ROOT/'.build/evidence'
    prefix=ROOT/'.build'/f'{args.name}-installed'
    if prefix.exists(): raise RuntimeError('private probe destination already exists')
    (evidence/f'{args.name}-factory.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(keepends=True),changed.splitlines(keepends=True),
        fromfile='a/lib/callback/AIFactory.cpp',tofile='b/lib/callback/AIFactory.cpp')))
    cmake=ROOT/'.venv/bin/cmake'
    try:
        shutil.copy2(fixture,target)
        factory.write_text(changed)
        with (evidence/f'{args.name}-build.log').open('w') as log:
            subprocess.run([str(cmake),'--build',str(ROOT/'.build/nk3-mac'),'-j','5'],
                           cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT)
        with (evidence/f'{args.name}-install.log').open('w') as log:
            subprocess.run([str(cmake),'--install',str(ROOT/'.build/nk3-mac'),'--prefix',str(prefix)],
                           cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT)
    finally:
        factory.write_text(original)
        target.unlink(missing_ok=True)
    (evidence/f'{args.name}-provenance.json').write_text(json.dumps(dict(
        factory_before_sha256=hashlib.sha256(original.encode()).hexdigest(),
        factory_restored_sha256=hashlib.sha256(factory.read_bytes()).hexdigest(),
        fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
        installed_bundle=str(prefix/'VCMI.app'),probe=args.probe,test_only=True),indent=2)+'\n')
    print(prefix/'VCMI.app')


if __name__=='__main__': main()
