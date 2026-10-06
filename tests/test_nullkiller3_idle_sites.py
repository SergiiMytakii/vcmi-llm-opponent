"""Own native visit completion can reopen an idle agenda before helper hold expires."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_IDLE_SITE_CONFIG'),
                     'requires isolated native build and private current save')
class NativeIdleSiteTest(unittest.TestCase):
    def test_site_completion_reviews_idle_main_before_independent_hold_expires(self):
        config=json.loads(Path(os.environ['VCMI_NK3_IDLE_SITE_CONFIG']).read_text())
        out=Path(tempfile.mkdtemp(prefix='nk3-idle-sites-',dir=ROOT/'.build/playtests'))
        print('Idle site evidence:',out,flush=True)
        probe=ROOT/'tests/fixtures/nk3_idle_site_probe.py'
        config.update(controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-idle-sites',nk3_mode='model',experience_mode='off',
            review_interval_days=3,max_seconds=25,decision_timeout_seconds=2)
        path=out/'config.json';path.write_text(json.dumps(config));run=out/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        with (out/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                   stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while child.poll() is None and time.monotonic()<deadline:
                    state=run/'turn-review/state.json'
                    if state.exists() and json.loads(state.read_text()).get('status')=='paused':break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        for result in (run/'decisions').glob('*/result.json'):
            self.assertEqual(json.loads(result.read_text())['status'],'reply_valid')
        requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                        key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        self.assertTrue(requests)
        completed=[r for r in requests[1:] if r['observation']['goal_statuses'].get('main-site',{}).get('state')=='completed'
                   and any(s['question'].startswith('idle_army:') for s in r['signals'])]
        self.assertTrue(completed,'completed useful visit never reopened the main agenda')
        r=completed[0];goals={g['id']:g for g in r['campaign']['goals']}
        self.assertLess(r['observation']['day'],goals['independent-hold']['complete_when']['value'])
        self.assertLessEqual(r['observation']['day'],requests[0]['observation']['day']+2)
        self.assertNotEqual(r['observation']['goal_statuses']['independent-hold']['state'],'completed')
        actor=next(h for h in r['observation']['heroes'] if h['ref']==goals['main-site']['actor_ref'])
        self.assertGreaterEqual(actor['army_value'],goals['main-site']['min_army_value'])
        self.assertTrue(any(v['goal']==goals['main-site'] for v in r['observation']['confirmed_site_visits']))
        self.assertTrue(campaign_records(run))

if __name__=='__main__':unittest.main()
