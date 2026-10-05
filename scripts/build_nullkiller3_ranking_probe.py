"""Build a private observer of real native choices; restore ordinary source.

Use only a task-owned prepared checkout and its task-owned CMake build.
The observer permutes generated alternatives and records the unchanged NK2
evaluator's preference. It creates no tasks or commands in the live planner.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--prefix',type=Path,required=True)
    args=parser.parse_args()
    source,build,prefix=(p.resolve() for p in (args.source,args.build,args.prefix))
    if any(not p.is_relative_to(ROOT/'.build') for p in (source,build,prefix)):
        parser.error('source, build and prefix must be private workspace .build paths')
    if prefix.exists():parser.error('prefix already exists; choose a fresh destination')
    cache=(build/'CMakeCache.txt').read_text()
    if f'CMAKE_HOME_DIRECTORY:INTERNAL={source}\n' not in cache:
        parser.error('build belongs to another source checkout')
    cpp=source/'AI/Nullkiller2/Engine/Nullkiller.cpp'
    header=source/'AI/Nullkiller3/RankingProbe.h'
    original=cpp.read_text()
    if header.exists() or 'RankingProbe' in original:
        parser.error('an observer is already present; preserve it')
    include='#include "../../Nullkiller3/NativeCampaign.h"'
    contexts='\t\tconst auto evaluationContexts = buildEvaluationContexts(tasks);'
    selected='\t\tif(strategicMode) nullkiller3::traceNative(*cc, selectedTasks, pass);'
    if any(original.count(a)!=1 for a in (include,contexts,selected)):
        parser.error('prepared planner does not match the NK3 integration')
    contracts=(source/'AI/Nullkiller3/TaskRanking.h').is_file()
    changed=original.replace(include,include+'\n'+('#define NK3_RANK_CONTRACT_PROBE\n' if contracts else '')+
                             '#include "../../Nullkiller3/RankingProbe.h"')
    changed=changed.replace(contexts,contexts+'\n\t\tif(strategicCampaign) nullkiller3::observeRankingChoices(*this,tasks,evaluationContexts,pass);')
    changed=changed.replace(selected,selected+'\n\t\tif(strategicCampaign) nullkiller3::observeRankingSelection(selectedTasks,pass);')
    cmake=ROOT/'.venv/bin/cmake'
    fixture=ROOT/'tests/fixtures/nullkiller3_ranking_probe.h'
    build_log=prefix.with_suffix('.build.log');install_log=prefix.with_suffix('.install.log')
    try:
        shutil.copy2(fixture,header);cpp.write_text(changed)
        with build_log.open('w') as log:
            subprocess.run([str(cmake),'--build',str(build),'--target','vcmiclient','vcmiserver','-j','5'],
                           check=True,stdout=log,stderr=subprocess.STDOUT)
        with install_log.open('w') as log:
            subprocess.run([str(cmake),'--install',str(build),'--prefix',str(prefix)],
                           check=True,stdout=log,stderr=subprocess.STDOUT)
    finally:
        cpp.write_text(original);header.unlink(missing_ok=True)
    prefix.with_suffix('.provenance.json').write_text(json.dumps(dict(test_only=True,ranking_contracts=contracts,
        ordinary_source_sha256=hashlib.sha256(original.encode()).hexdigest(),
        restored_source_sha256=hashlib.sha256(cpp.read_bytes()).hexdigest(),
        fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
        bundle=str(prefix/'VCMI.app')),indent=2)+'\n')
    print(prefix/'VCMI.app')


if __name__=='__main__':main()
