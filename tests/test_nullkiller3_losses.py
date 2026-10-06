"""Strategic policy survives real ownership changes outside named goals."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import variants
from playtesting.runs import copy_snapshot_file
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an ordinary private NK3 bundle')
class NativeLossTest(unittest.TestCase):
    def test_loss_of_a_policy_critical_town_outside_named_goals_receives_one_critical_review(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-critical-town-loss-',dir=ROOT/'.build/playtests'))
        print('\nNK3 critical-town-loss evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['army']=[]
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{p}{i}' for p in ('dwellingLvl','dwellingUpLvl') for i in range(1,8)]
        spare=copy.deepcopy(town);spare['y']=25;objects['town_spare']=spare
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        hero['y']=25;hero['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=9,y=13);enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3CriticalTownLoss.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        goal=dict(id='spare',kind='develop_town',actor_ref=None,target_ref='object:2',deadline_day=6,
            priority=80,building_id=12,min_army_value=0,depends_on=[],required_capabilities=['build'],
            complete_when=dict(kind='building_present',value=12))
        seed=dict(version=3,revision=1,approach='economy',horizon_days=5,goals=[goal],reserves=[],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
        seed_path=output/'campaign.json';seed_path.write_text(json.dumps(seed))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3CriticalTownLoss.vmap',
            players={'red':'Nullkiller3','blue':'Nullkiller2'},nk3_mode='model',purpose='integration',
            case_id='nk3-critical-town-loss',headless=True,max_seconds=20,references={},experience_mode='off',
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path),NK3_PROBE_MODE='retain_seed'),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=4 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'seed campaign was not installed')
        self.assertEqual(len(records[0]['towns']),2,'fixture did not own both towns initially')
        lost=[r for r in records if 'object:1' not in [t['ref'] for t in r['towns']]]
        self.assertTrue(lost,'the real NK2 opponent did not capture the policy critical town')
        self.assertTrue(any('object:2' in [t['ref'] for t in r['towns']] for r in lost),'the spare town did not survive')
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        reviews=[r for r in requests if any(s['question']=='critical_town_lost:object:1' for s in r['signals'])]
        self.assertEqual(len(reviews),1,'policy town loss was not critically reviewed exactly once: '+str(run))
        self.assertTrue(any(s['critical'] for s in reviews[0]['signals'] if s['question']=='critical_town_lost:object:1'))
        self.assertNotIn('object:1',[t['ref'] for t in reviews[0]['observation']['towns']])
        self.assertTrue(all(g['target_ref']!='object:1' for g in reviews[0]['campaign']['goals']))
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
