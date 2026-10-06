"""An assigned defender must enter an owned town occupied by two own heroes."""
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


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_DEFENDER_CONFIG'),
                     'requires isolated native build and private occupied-town day-60 save')
class NativeTownDefenderTest(unittest.TestCase):
    def test_defender_enters_occupied_town_without_spending_any_own_army(self):
        self.run_defender(reload=True)

    def test_defender_enters_after_a_new_visitor_is_hired(self):
        if not os.environ.get('VCMI_NK3_DEFENDER63_CONFIG'):self.skipTest('requires original day63 newly hired visitor fixture')
        self.run_defender(start=64)

    def run_defender(self,start=61,reload=False):
        config=json.loads(Path(os.environ['VCMI_NK3_DEFENDER_CONFIG' if start==61 else 'VCMI_NK3_DEFENDER63_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-town-defender-',dir=ROOT/'.build/playtests'))
        print('\nTown defender evidence:',output,flush=True)
        config.update(case_id='nk3-town-defender',purpose='integration',nk3_mode='native',
                      experience_mode='off',review_interval_days=1,max_seconds=25)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
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
        state=json.loads((run/'turn-review/state.json').read_text());self.assertEqual(state['completed_day'],start)
        records=campaign_records(run);self.assertTrue(records,'no restored own campaign state')
        first,last=records[0],records[-1]
        self.assertEqual(first['revision'],49 if start==61 else 51,'fixture did not restore original occupied-town plan')
        opening={h['ref']:h for h in first['heroes']};final={h['ref']:h for h in last['heroes']}
        self.assertEqual(opening['object:46']['position'],[20,6,0])
        self.assertEqual(opening['object:13']['position'],[20,5,0])
        self.assertEqual(opening['object:85' if start==61 else 'object:87']['position'],[20,5,0])
        for ref,hero in opening.items():
            self.assertIn(ref,final,'town occupancy repair dismissed an owned hero')
            self.assertGreaterEqual(final[ref]['army_value'],hero['army_value'],
                                    'town occupancy repair spent a committed own force: '+ref)
        self.assertEqual(final['object:46']['position'],[20,5,0],
                         'defender repeatedly met the visiting hero without entering the town: '+str(run))
        self.assertEqual(last['statuses']['renew-home-defense' if start==61 else 'hold-home-next']['state'],'ready',
                         'entry fabricated held-until completion before day63')

        if reload:
            resumed=output/'resumed'
            config.update(profile_template=str(run/'profile'),save_resource=state['save_resource'])
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
            after=campaign_records(resumed);self.assertTrue(after)
            stationed=next(h for h in after[-1]['heroes'] if h['ref']=='object:46')
            self.assertEqual(stationed['position'],[20,5,0])
            self.assertEqual(stationed['movement'],2000,'stationed defender repeatedly revisited the town after load')
            self.assertGreaterEqual(stationed['army_value'],8855)
            launch=json.loads((resumed/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
