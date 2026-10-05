"""One strategic exchange creates a goal and native play continues on rejection."""
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
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a separate NK3 build and private strategic fixture')
class NativeStrategicExchangeTest(unittest.TestCase):
    def test_strategy_goal_and_invalid_reply_fallback_through_recorder(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-strategy-',dir=ROOT/'.build/playtests'))
        print('\nNK3 strategy evidence:',output,flush=True)
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      controller_sources=[str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      purpose='integration',case_id='nk3-strategy',headless=True,max_seconds=25,
                      decision_timeout_seconds=1,experience_mode='off')
        config.pop('save_resource',None)
        for mode in ['valid','resource','stale','invalid','timeout']:
            with self.subTest(mode=mode):
                goal_id='supply' if mode=='resource' else 'guild'
                path=output/(mode+'.json');path.write_text(json.dumps(config));run=output/mode
                subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
                env=dict(os.environ,NK3_PROBE_MODE=mode);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
                with (run/'driver.log').open('w') as log:
                    child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        deadline=time.monotonic()+30
                        while child.poll() is None and time.monotonic()<deadline:
                            records=campaign_records(run)
                            if mode in ('valid','resource') and any(r['statuses'].get(goal_id,{}).get('state')=='completed' for r in records):break
                            logpath=run/'engine-logs/VCMI_Client_log.txt'
                            if mode not in ('valid','resource') and logpath.exists():
                                text=logpath.read_text(errors='replace')
                                if 'NK3_STRATEGY' in text and 'Player 0 (red) ends turn' in text:break
                            time.sleep(.03)
                    finally:
                        (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
                decisions=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/result.json')),key=lambda d:d['started_at'])
                self.assertTrue(decisions,'no actual strategic exchange')
                first=decisions[0]
                self.assertEqual(first['protocol'],2)
                self.assertEqual(first['action_count'],0)
                request=json.loads((run/'decisions'/first['decision_id']/'request.json').read_text())
                self.assertNotIn('actions',request)
                text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
                if mode in ('valid','resource'):
                    self.assertEqual(first['status'],'reply_valid')
                    self.assertTrue(any(r['statuses'].get(goal_id,{}).get('state')=='completed' for r in campaign_records(run)),
                                    'structured goal did not execute')
                    if mode=='valid':self.assertIn('will build building.core.castle.mageGuild1.name',text)
                    else:self.assertEqual(campaign_records(run)[0]['statuses']['supply']['state'],'ready','existing gold bypassed actual pickup')
                    self.assertGreaterEqual(len(request['observation']['forecasts']['alternatives']),2)
                else:
                    self.assertNotEqual(first['status'],'reply_valid')
                    self.assertFalse(campaign_records(run),'invalid model policy was partially installed')
                    self.assertIn('NK3_NATIVE',text)
                    self.assertIn('will build ',text,'fallback lost useful native work')
                    openings=0
                    for decision in decisions:
                        entry=json.loads((run/'decisions'/decision['decision_id']/'request.json').read_text())
                        openings+=any(s['question']=='opening' for s in entry['signals'])
                    self.assertEqual(openings,1,'same failed opening question retried')
                launch=json.loads((run/'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
                self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])


if __name__=='__main__':unittest.main()
