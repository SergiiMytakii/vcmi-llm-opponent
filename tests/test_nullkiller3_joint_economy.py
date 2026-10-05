"""Multiple accepted city commitments share one treasury and income calendar."""
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
from test_nullkiller3_campaign import campaign_records
from playtesting.runs import copy_snapshot_file

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires a separate private NK3 bundle')
class NativeJointEconomyTest(unittest.TestCase):
    def test_three_city_halls_share_the_treasury_in_the_forecast_and_real_builds(self):
        config=json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-joint-economy-',dir=ROOT/'.build/playtests'))
        print('\nNK3 joint-economy evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall','blacksmith','marketplace','mageGuild1','tavern']
        town['options']['buildings']['noneOf'].remove('tavern')
        world['header.json']['allowedHeroes']={'anyOf':['core:catherine','core:roland']}
        for name,x,y in [('town_second',18,5),('town_third',28,5)]:
            objects[name]=copy.deepcopy(town);objects[name].update(x=x,y=y)
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3JointEconomy.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        goals=[dict(id=f'city{i}',kind='develop_town',actor_ref=None,target_ref=f'object:{i}',deadline_day=6,
                    priority=90-i,building_id=12,min_army_value=0,depends_on=[],required_capabilities=['build'],
                    complete_when=dict(kind='building_present',value=12)) for i in (1,2,3)]
        goals.append(dict(id='hold',kind='preserve_force',actor_ref='object:0',target_ref='object:1',deadline_day=6,
                          priority=40,building_id=-1,min_army_value=1000,depends_on=[],required_capabilities=['land'],
                          complete_when=dict(kind='force_preserved_until',value=6)))
        plan=dict(version=3,revision=1,approach='economy',horizon_days=5,goals=goals,reserves=[],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3JointEconomy.vmap',players={'red':'Nullkiller3','blue':'EmptyAI'},
                      nk3_mode='native',purpose='integration',case_id='nk3-joint-economy',headless=True,max_seconds=20,references={})
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed)),
                                   stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(all(r['statuses'].get(f'city{i}',{}).get('state')=='completed' for i in (1,2,3)) for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'campaign was not installed')
        initial=next(r for r in records if isinstance(r.get('forecasts'),dict))
        commitments={a['goal_id']:a for a in initial['forecasts']['commitments']}
        day_one_cost=sum(a['cost'][6] for a in commitments.values() if a.get('build_day')==1)
        self.assertLessEqual(day_one_cost,initial['resources'][6],'independent forecasts spend the same treasury multiple times')
        completed=next((r for r in records if all(r['statuses'][f'city{i}']['state']=='completed' for i in (1,2,3))),None)
        self.assertIsNotNone(completed,'the three actual city commitments did not finish: '+str(run))
        for i in (1,2,3):
            self.assertEqual(completed['statuses'][f'city{i}']['completed_day'],commitments[f'city{i}']['build_day'])
        self.assertGreater(commitments['city3']['build_day'],1,'shared treasury did not defer the last city')
        self.assertFalse(list((run/'decisions').glob('*/request.json')))
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
