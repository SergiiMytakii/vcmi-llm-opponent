"""Opt-in native telemetry proof using only a new private fixture."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
import zipfile

from codex_fixture import codex_fixture
from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]
ANALYST = '''
import json,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
assert r['analysis_version']==1 and 'actions' not in r
answers=[];assessments=[]
for e in r['episodes']:
 ids=[s['id'] for s in e['signals'] if s.get('stage')!='before']
 answers.append(dict(episode_id=e['id'],outcome='unknown',decision_quality='uncertain',responsibility='unknown',
  before_evidence_ids=[],after_evidence_ids=ids[:1],alternative_evidence_id=None,
  explanation='Own observations recorded; no causal claim.',uncertainty='No proven better alternative.',impact='Unconfirmed.'))
 assessments.append(dict(episode_id=e['id'],lesson_id=None,verdict='uncertain',rule='Retain own evidence before drawing conclusions.',
  conditions=['tempo'],evidence_ids=ids[:1],explanation='Insufficient causal evidence.',exceptions=[],mechanism='Avoid hindsight.'))
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(dict(evaluations=answers,assessments=assessments)))
print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=8,output_tokens=5))))
'''


def run_fixture(test, config_path, *, battle_loss=False, battle_win=False, two_players=False):
    from playtesting.runs import copy_snapshot_file
    config = json.loads(Path(config_path).read_text())
    (ROOT / '.build/playtests').mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='separate-learning-', dir=ROOT / '.build/playtests'))
    print('\nNative learning evidence:', output, flush=True)
    profile = output / 'fixture'
    shutil.copytree(config['profile_template'], profile, copy_function=copy_snapshot_file)
    data = variants()['base']
    if battle_loss or battle_win:
        for name in [k for k,v in data['objects.json'].items() if v['type'] in ('monster','mine','resource')]:
            del data['objects.json'][name]
        hero = next(v for v in data['objects.json'].values() if v['type']=='hero' and v['options']['owner']=='red')
        hero['options']['army'] = [dict(type='core:pikeman' if battle_loss else 'core:archangel', amount=1 if battle_loss else 1000)]
        enemy = next(v for v in data['objects.json'].values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=9 if battle_loss else 11,y=13 if battle_loss else 11)
        enemy['options']['army'] = [dict(type='core:archangel' if battle_loss else 'core:pikeman',amount=1000 if battle_loss else 1)]
        if battle_win:
            town = next(v for v in data['objects.json'].values() if v['type']=='town' and v['options']['owner']=='blue')
            town.update(x=12,y=11)
    else:
        data['header.json']['triggeredEvents'] = {'proofEnd':{'condition':['daysPassed',{'value':2}],
            'effect':{'type':'defeat','messageToSend':'Fixture ended.'},'message':'Fixture ended.'}}
    map_path = profile / 'Library/Application Support/vcmi/Maps/ExperienceProof.vmap'
    with zipfile.ZipFile(map_path, 'x') as archive:
        for name,value in data.items():archive.writestr(name,json.dumps(value))
    config.update(profile_template=str(profile), map_resource='Maps/ExperienceProof.vmap',
        controller=[sys.executable,str(ROOT/'controller/main.py')],controller_sources=[], references={},
        players={'red':'Nullkiller3','blue':'Nullkiller3' if two_players or battle_loss else 'EmptyAI'},
        nk3_mode='native',experience_mode='learn',experience_database=str(output/'run/experience.sqlite3'),
        purpose='integration',case_id='separate-learning',
        headless=True,max_seconds=25,review_interval_days=0,
        analysis_max_calls=8,analysis_timeout_seconds=3,analysis_interval_seconds=.2)
    config.pop('save_resource',None)
    path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
    cli=ROOT/'scripts/playtest.py'
    subprocess.run([sys.executable,str(cli),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
    env={**os.environ,**codex_fixture(output,ANALYST)}
    env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
    with (output/'driver.log').open('w') as stream:
        process=subprocess.run([sys.executable,str(cli),'run','--run',str(run)],env=env,
                               stdout=stream,stderr=subprocess.STDOUT,timeout=40)
    test.assertEqual(process.returncode,0,str(output))
    launch=json.loads((run/'launch.json').read_text())
    test.assertTrue(launch['cleanup_complete'],launch)
    test.assertTrue(launch['protected_files_unchanged'],launch)
    test.assertNotIn('analysis_error',launch)
    test.assertNotIn('analysis_cleanup_error',launch)
    events=[json.loads(line) for line in (run/'learning/turns.jsonl').read_text().splitlines()]
    test.assertTrue(any(e['phase']=='begin' for e in events))
    test.assertTrue(any(e['phase']=='execution' for e in events),'no own execution telemetry')
    test.assertEqual(list((run/'decisions').iterdir()),[], 'native-only turns unexpectedly called strategy')
    players={0,1} if two_players or battle_loss else {0}
    test.assertEqual({e['player'] for e in events},players)
    for e in events:
        test.assertEqual(e['observation']['player'],e['player'])
        test.assertEqual(e['observation']['day'],e['day'])
        if e['phase']=='execution':
            action=e['own_result']['action']
            if action['kind']=='battle':test.assertEqual(action['player'],e['player'])
            else:
                test.assertEqual(action['before']['player'],e['player'])
                test.assertEqual(action['after']['player'],e['player'])
    terminal=[e for e in events if e['phase']=='terminal' and e['player']==0]
    test.assertTrue(terminal,'own terminal result was not journaled')
    if battle_loss or battle_win:
        battles=[r for e in terminal for r in e.get('results',[]) if r['action'].get('kind')=='battle']
        test.assertTrue(battles,'terminal omitted the final own battle')
        test.assertEqual(battles[-1]['outcome'],'battle_lost' if battle_loss else 'battle_won')
    else:test.assertGreaterEqual(sum(e['phase']=='end' and e['player']==0 for e in events),2)
    with closing(sqlite3.connect(run/'experience.sqlite3')) as database:
        stored=[json.loads(r[0]) for r in database.execute('SELECT payload FROM turn_events')]
        test.assertTrue(any(e['phase']=='terminal' and e['player']==0 for e in stored))
        test.assertGreater(database.execute('SELECT COUNT(*) FROM episodes').fetchone()[0],0)
        test.assertGreater(database.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0],0)
        own_ids={e['game'] for e in events}
        test.assertTrue({r[0] for r in database.execute('SELECT DISTINCT game FROM episodes')}<=own_ids)
    return output


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NATIVE_EXPERIENCE_CONFIG'),
                     'requires an explicit private native fixture on macOS')
class NativeExperienceTest(unittest.TestCase):
    def test_own_turns_and_terminal_reach_separate_analysis_without_strategy_calls(self):
        run_fixture(self,os.environ['VCMI_NATIVE_EXPERIENCE_CONFIG'])


if __name__=='__main__':unittest.main()
