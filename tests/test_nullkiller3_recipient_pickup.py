"""An owned recipient can collect a guarded donor's compatible surplus."""
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
@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_PICKUP_CONFIG') and os.environ.get('VCMI_NK3_PICKUP_REPLY'),
                     'requires isolated build and private saved guarded-delivery reproduction')
class NativeRecipientPickupTest(unittest.TestCase):
    def test_recipient_collects_surplus_before_deadline_without_breaking_donor_preservation(self):
        config=json.loads(Path(os.environ['VCMI_NK3_PICKUP_CONFIG']).read_text())
        reply_path=Path(os.environ['VCMI_NK3_PICKUP_REPLY']).resolve();reply=json.loads(reply_path.read_text())
        goal=next(g for g in reply['plan']['goals'] if g['kind']=='reinforce_hero')
        hold=next(g for g in reply['plan']['goals'] if g['kind']=='preserve_force')
        out=Path(tempfile.mkdtemp(prefix='nk3-recipient-pickup-',dir=ROOT/'.build/playtests'))
        print('Recipient pickup evidence:',out,flush=True)
        probe=ROOT/'tests/fixtures/nk3_recipient_pickup_probe.py'
        config.update(controller=[sys.executable,str(probe),str(reply_path)],controller_sources=[str(probe),str(reply_path)],
            purpose='integration',case_id='nk3-recipient-pickup',nk3_mode='model',experience_mode='off',
            review_interval_days=3,max_seconds=30,decision_timeout_seconds=2)
        path=out/'config.json';path.write_text(json.dumps(config));run=out/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        with (out/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                   stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35;released=False
                while child.poll() is None and time.monotonic()<deadline:
                    state_path=run/'turn-review/state.json'
                    if state_path.exists():
                        state=json.loads(state_path.read_text())
                        if state.get('status')=='paused':
                            if state['completed_day']==84 and not released:
                                subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'continue','--run',str(run),
                                                '--completed-day','84'],check=True,capture_output=True)
                                released=True
                            elif state['completed_day']>=87:break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        for result in (run/'decisions').glob('*/result.json'):
            self.assertEqual(json.loads(result.read_text())['status'],'reply_valid')
        records=campaign_records(run)
        completed=[r for r in records if r['statuses'].get(goal['id'],{}).get('state')=='completed']
        self.assertTrue(completed,'no confirmed handoff before the recorded delivery deadline')
        self.assertLessEqual(completed[0]['statuses'][goal['id']]['completed_day'],goal['deadline_day'])
        self.assertTrue(any(v['goal']==goal and v['source_ref']==goal['target_ref']
                            and v['recipient_after']>=goal['complete_when']['value'] for v in completed[0]['confirmed_deliveries']))
        for r in records:
            if 83<=r['day']<=hold['complete_when']['value'] and r['statuses'].get(hold['id'],{}).get('state')!='completed':
                donor=next(h for h in r['heroes'] if h['ref']==goal['target_ref'])
                self.assertGreaterEqual(donor['army_value'],hold['min_army_value'])
        preserved=[r for r in records if r['statuses'].get(hold['id'],{}).get('state')=='completed']
        self.assertTrue(preserved,'the compatible source did not return to its promised refuge')
        self.assertEqual(preserved[0]['statuses'][hold['id']]['completed_day'],hold['complete_when']['value'])

if __name__=='__main__':unittest.main()
