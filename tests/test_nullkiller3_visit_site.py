"""A known scholar must be identifiable and executable through the own DTO."""
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


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_SITE_CONFIG'),
                     'requires isolated native build and the private day69 save')
class NativeVisitSiteTest(unittest.TestCase):
    def test_known_scholar_is_offered_and_its_visit_is_confirmed_for_the_actor(self):
        self.run_site(reload=True)

    def test_known_chest_visit_is_confirmed(self):
        self.run_site('treasure_chest')

    def test_known_obelisk_visit_is_confirmed(self):
        self.run_site('obelisk')

    def run_site(self,kind='scholar',reload=False):
        config=json.loads(Path(os.environ['VCMI_NK3_SITE_CONFIG']).read_text())
        out=Path(tempfile.mkdtemp(prefix='nk3-visit-site-',dir=ROOT/'.build/playtests'))
        print('\nKnown site evidence:',out,flush=True)
        probe=ROOT/'tests/fixtures/nk3_visit_site_probe.py'
        config.update(controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-visit-site',nk3_mode='model',experience_mode='off',
            review_interval_days=3,max_seconds=25,decision_timeout_seconds=2)
        path=out/'config.json';path.write_text(json.dumps(config));run=out/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        with (out/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                   env=dict(os.environ,NK3_SITE_KIND=kind),stdout=log,stderr=subprocess.STDOUT)
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
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(requests,'no actual strategy request after restored goals exhausted')
        opening=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))['observation']
        if kind=='scholar':
            scholar=next(o for o in opening['objects'] if o['ref']=='object:15')
            self.assertEqual(scholar['kind'],'scholar','a known scholar was reduced to an unselectable generic other object')
            self.assertTrue(scholar['visible'])
        records=campaign_records(run)
        completed=[x for x in records if x['statuses'].get('learn-site',{}).get('state')=='completed']
        self.assertTrue(completed,'the offered scholar visit never received native confirmation')
        replies=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/stdout.bin') if p.stat().st_size]
        goal=next(x['plan']['goals'][0] for x in replies if x['decision']=='revise')
        site=next(o for o in opening['objects'] if o['ref']==goal['target_ref'])
        self.assertEqual(site['kind'],kind)
        self.assertTrue(site['visible']);self.assertFalse(site['visited'])
        self.assertTrue(any(r['goal']==goal and r['day']==completed[0]['day'] for r in completed[0]['confirmed_site_visits']))
        actor=next(h for h in completed[0]['heroes'] if h['ref']==goal['actor_ref'])
        before=next(h for h in opening['heroes'] if h['ref']==goal['actor_ref'])
        self.assertGreaterEqual(actor['army_value'],before['army_value'],'safe site visit consumed its helper army')
        self.assertLessEqual(completed[0]['day'],goal['deadline_day'])

        if reload:
            state=json.loads((run/'turn-review/state.json').read_text());self.assertEqual(state['completed_day'],72)
            resumed=out/'resumed';config.update(profile_template=str(run/'profile'),save_resource=state['save_resource'],
                nk3_mode='native',review_interval_days=1)
            path.write_text(json.dumps(config))
            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(resumed)],
                           check=True,capture_output=True)
            with (out/'resume-driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(resumed)],
                                       stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+30
                    while child.poll() is None and time.monotonic()<deadline:
                        state_path=resumed/'turn-review/state.json'
                        if state_path.exists() and json.loads(state_path.read_text()).get('status')=='paused':break
                        time.sleep(.03)
                finally:
                    (resumed/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            after=campaign_records(resumed);self.assertTrue(after)
            self.assertEqual(after[0]['statuses']['learn-site']['completed_day'],completed[0]['day'])
            self.assertEqual(after[0]['statuses']['learn-site']['state'],'completed')
            self.assertEqual(after[0]['revision'],completed[0]['revision'])
            launch=json.loads((resumed/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
