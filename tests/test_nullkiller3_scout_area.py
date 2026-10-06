"""A safe known viewpoint can reveal fog beyond inaccessible frontier tiles."""
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


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_SCOUT_AREA_CONFIG'),
                     'requires an isolated native build and the private day-57 regression save')
class NativeScoutAreaTest(unittest.TestCase):
    def test_known_viewpoint_reveals_its_area_when_frontier_routes_are_blocked(self):
        self.run_area()

    def test_unoffered_area_is_rejected(self):
        self.run_area('unknown')

    def test_radius_above_the_actors_sight_is_rejected(self):
        self.run_area('radius')

    def test_observed_area_and_committed_radius_survive_native_save_load(self):
        self.run_area(reload=True)

    def run_area(self,mode='valid',reload=False):
        config=json.loads(Path(os.environ['VCMI_NK3_SCOUT_AREA_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-scout-area-',dir=ROOT/'.build/playtests'))
        print('\nNK3 scouting area evidence:',output,flush=True)
        probe=ROOT/'tests/fixtures/nk3_scout_area_probe.py'
        config.update(controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-scout-area',nk3_mode='model',experience_mode='off',
            max_seconds=25,decision_timeout_seconds=2,review_interval_days=3)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                   env=dict(os.environ,NK3_SCOUT_AREA_MODE=mode),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    state=run/'turn-review/state.json'
                    if state.exists() and json.loads(state.read_text()).get('status')=='paused':
                        checkpoint=json.loads(state.read_text())
                        if checkpoint['completed_day']==60 and not list((run/'decisions').glob('*/request.json')):
                            # Repaired town entry completes both old obligations
                            # on day60. Exhaustion is reviewed on the next own
                            # turn; the private harness must cross that boundary.
                            self.assertTrue(records)
                            self.assertTrue(all(v['state']=='completed' for v in records[-1]['statuses'].values()))
                            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'continue',
                                            '--run',str(run),'--completed-day','60'],check=True,capture_output=True)
                            while json.loads(state.read_text()).get('status')=='paused' and child.poll() is None and time.monotonic()<deadline:
                                time.sleep(.03)
                        else:break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(requests,'no actual player strategy request')
        opening=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))['observation']
        self.assertFalse(any(f['own_arrivals'] for f in opening['frontier_options']),
                         'regression save no longer represents blocked frontier routes')
        offered=[(a,p) for a in opening.get('scouting_options',[]) for p in a['own_arrivals']
                 if p['hero_ref']=='object:0' and p['expected_new_tiles']>0 and p['army_loss_estimate']==0]
        self.assertTrue(offered,'known safe viewpoints were omitted from the public observation')
        records=campaign_records(run)
        completed=[r for r in records if r['statuses'].get('observe-area',{}).get('state')=='completed']
        if mode!='valid':
            self.assertFalse(completed,'unoffered area or unsupported radius falsely completed')
            results=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/result.json')]
            self.assertTrue(any(r['status']=='invalid_reply' and r.get('action_count')==0 for r in results),
                            'unoffered target or radius passed the public reply contract')
            return
        self.assertTrue(completed,'offered scouting area did not execute and reveal its fog: '+str(run))
        reply=next(json.loads(p.read_text()) for p in (run/'decisions').glob('*/stdout.bin')
                   if p.stat().st_size and json.loads(p.read_text()).get('decision')=='revise')
        goal=reply['plan']['goals'][0]
        area=next(a for a in opening['scouting_options'] if a['ref']==goal['target_ref'])
        hero=next(h for h in completed[0]['heroes'] if h['ref']==goal['actor_ref'])
        self.assertEqual(hero['position'],area['position'])
        self.assertGreaterEqual(hero['army_value'],266477,'zero-loss scouting spent the strike army')
        if reload:
            state=json.loads((run/'turn-review/state.json').read_text())
            self.assertIn(state['completed_day'],(60,63))
            resumed=output/'resumed';config.update(profile_template=str(run/'profile'),save_resource=state['save_resource'],
                case_id='nk3-scout-area-restored',nk3_mode='native',review_interval_days=1)
            path.write_text(json.dumps(config))
            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(resumed)],
                           check=True,capture_output=True)
            with (output/'resume-driver.log').open('w') as log:
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
            after=campaign_records(resumed)
            self.assertTrue(after,'saved area plan was not restored')
            self.assertEqual(after[0]['statuses']['observe-area']['state'],'completed')
            self.assertEqual(after[0]['statuses']['observe-area']['completed_day'],completed[0]['day'])
            self.assertEqual(after[0]['revision'],reply['plan']['revision'])
            launch=json.loads((resumed/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
