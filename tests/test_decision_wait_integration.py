"""Real own-turn cancellation and independent courier, with unanswered review."""
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
from fixtures.background_maps import safe_map
from playtesting.runs import copy_snapshot_file
from test_background_integration import records

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get('VCMI_NK3_DECISION_CONFIG'), 'requires isolated candidate runtime')
class DecisionWaitIntegrationTest(unittest.TestCase):
    def test_completed_preparation_releases_only_hold_despite_unanswered_review(self):
        config=json.loads(Path(os.environ['VCMI_NK3_DECISION_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='decision-wait-',dir=ROOT/'.build/decision-proof'))
        fixture=output/'fixture'
        shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        data=safe_map();objects=data['objects.json']
        # The courier's promised force must stay necessary until its handoff.
        for town in (o for o in objects.values() if o['type']=='town'):
            town['options']['buildings']['allOf'].remove('dwellingLvl1')
            town['options']['buildings']['noneOf'].append('dwellingLvl1')
        main=next(o for o in objects.values() if o['type']=='hero')
        helper=copy.deepcopy(main);helper.update(x=19,y=12)
        helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=10)])
        objects['independent_courier']=helper
        data['header.json']['players']['red']['heroes']['independent_courier']={'type':'christian'}
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/DecisionWait.vmap','x') as z:
            for name,value in data.items():z.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_decision_wait.py'
        config.update(profile_template=str(fixture),map_resource='Maps/DecisionWait.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],case_id='decision-wait-native',purpose='integration',
            max_seconds=20,headless=True,experience_mode='off',review_interval_days=0)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),
            '--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+23
                while child.poll() is None and time.monotonic()<deadline:
                    campaigns=records(run/'runtime.log','NK3_CAMPAIGN')
                    if any(c.get('statuses',{}).get('independent-delivery',{}).get('state')=='completed'
                           for c in campaigns):break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch();child.wait(timeout=15)
        print('Decision wait native proof:',output,flush=True)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        accepted=[r for r in records(run/'runtime.log','NK3_STRATEGY') if r.get('accepted') is True]
        self.assertTrue(accepted,str(output))
        campaigns=records(run/'runtime.log','NK3_CAMPAIGN')
        released=[r for r in campaigns if r.get('statuses',{}).get('temporary-preparation',{}).get('state')=='cancelled']
        self.assertTrue(released,str(output))
        self.assertTrue(any(r['statuses']['independent-delivery']['state']!='cancelled'
                            for r in released),str(output))
        execution=records(run/'runtime.log','NK3_EXECUTION')
        self.assertTrue(any(e.get('action',{}).get('goal_id')=='independent-delivery'
            and e['action'].get('acknowledgment')=='acknowledged'
            and e['action']['after']['heroes'][0]['army_value']>e['action']['before']['heroes'][0]['army_value']
            for e in execution),str(output))
        self.assertTrue(any(c.get('statuses',{}).get('independent-delivery',{}).get('state')=='completed'
                            for c in campaigns),str(output))
