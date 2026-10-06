"""Compare a conditional build forecast with real prerequisite spending."""
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

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires separate NK3 build and private economic fixture')
class NativeEconomyTest(unittest.TestCase):
    def test_native_schedule_builds_income_prerequisites_and_protects_defense_budget(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-economy-',dir=ROOT/'.build/playtests'))
        print('\nNK3 economy evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture)
        world=variants()['base']
        for item in world['objects.json'].values():
            if item['type']=='town':item['options']['buildings']['noneOf'].remove('tavern')
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Economy.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Economy.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
                      purpose='integration',case_id='nk3-economy',headless=True,max_seconds=40,
                      decision_timeout_seconds=1,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='economy');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+45
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['statuses'].get('income',{}).get('state')=='completed' for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        completed=next((r for r in records if r['statuses'].get('income',{}).get('state')=='completed'),None)
        self.assertIsNotNone(completed,'income objective never built: '+str(run))
        forecasts=[r['forecasts'] for r in records if isinstance(r.get('forecasts'),dict)]
        self.assertTrue(forecasts,'no accepted-plan forecast')
        # The accepted forecast includes the new defense reserve and the same
        # prerequisite chain that the native builder actually executes.
        initial=next(a for a in forecasts[0]['commitments'] if a['goal_id']=='income')
        self.assertEqual(initial['status'],'unfunded_at_deadline','forecast assumed unowned future wood')
        economy=next(a for forecast in forecasts for a in forecast['commitments']
                     if a['goal_id']=='income' and a['status']=='conditional')
        expected=[s['building_id'] for s in economy['schedule']]
        self.assertIn(12,expected,'forecast did not include City Hall')
        self.assertEqual(completed['statuses']['income']['completed_day'],economy['build_day'])
        built=completed['towns'][0]['buildings']
        self.assertTrue(all(b in built for b in expected))
        for record in records:
            self.assertGreaterEqual(record['resources'][6],1000,'construction spent defense reserve')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])


if __name__=='__main__':unittest.main()
