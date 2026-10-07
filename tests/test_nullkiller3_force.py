"""Army commitments use raw creature value, independently of hero bonuses."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from fixtures.fog_maps import variants
from test_nullkiller3_native import native_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires the private NK3 fixture')
class NativeForceTest(unittest.TestCase):
    def test_hero_bonuses_do_not_satisfy_a_raw_army_minimum(self):
        config=json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-force-units-',dir=ROOT/'.build/playtests'))
        print('\nNK3 force-units evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture)
        world=variants()['base']
        town=next(v for v in world['objects.json'].values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3ForceUnits.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        seed=dict(version=3,revision=1,approach='expansion',horizon_days=5,
                  goals=[dict(id='supply',kind='secure_resource',actor_ref='object:0',target_ref='object:4',
                              deadline_day=6,priority=80,building_id=-1,min_army_value=6000,depends_on=[],
                              required_capabilities=['land'],complete_when=dict(kind='reserve_at_least',value=1000))],
                  reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
                                           allow_helper_replacement=True,critical_towns=['object:1']))
        seed_path=output/'campaign.json';seed_path.write_text(json.dumps(seed))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3ForceUnits.vmap',players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='native',experience_mode='off',purpose='integration',
                      case_id='nk3-force-units',headless=True,max_seconds=15,references={})
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                                   env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    records=native_records(run)
                    if any(r['pass']>=1 for r in records):break
                    time.sleep(.02)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=native_records(run)
        self.assertTrue(records,'no real native proposals')
        self.assertTrue(any(r['pass']>=1 for r in records),'stopped before the strategic movement pass')
        self.assertEqual(records[0]['heroes'][0]['army'],5900,'fixture no longer distinguishes raw army from hero strength')
        for record in records:
            if any(t.get('campaign_goal')=='supply' for t in record['tasks']):
                self.assertGreaterEqual(record['heroes'][0]['army'],6000,
                                        'hero combat bonus admitted a task below its raw army commitment: '+str(run))
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
