"""Blocked strategic scouting is corrected and executed before the turn ends."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from test_nullkiller3_campaign import campaign_records

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a separate NK3 build and private native fixture')
class IdleCorrectionTest(unittest.TestCase):
    def test_blocked_scout_is_corrected_and_moves_during_the_same_turn(self):
        config = json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-idle-', dir=ROOT / '.build/playtests'))
        print('\nIdle correction evidence:', output, flush=True)
        probe = ROOT / 'tests/fixtures/nk3_idle_probe.py'
        config.update(players={'red':'Nullkiller3', 'blue':'EmptyAI'}, nk3_mode='model',
                      controller=[sys.executable, str(probe)], controller_sources=[str(probe)],
                      references={}, purpose='integration', case_id='nk3-idle', headless=True,
                      max_seconds=15, decision_timeout_seconds=2, experience_mode='off')
        config.pop('save_resource', None)
        path = output / 'config.json'; path.write_text(json.dumps(config))
        run = output / 'game'
        subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path), '--out', str(run)],
                       check=True, capture_output=True)
        env = dict(os.environ); env.pop('VCMI_NK3_SEED_CAMPAIGN', None)
        with (output / 'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)], env=env,
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    records = campaign_records(run)
                    if any(r['statuses'].get('pickup', {}).get('state')=='completed' for r in records):
                        break
                    time.sleep(.05)
            finally:
                (run / 'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        launch = json.loads((run / 'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run / 'report.json').read_text())['assignment_matches'])
        requests = sorted((json.loads(p.read_text()) for p in (run / 'decisions').glob('*/request.json')),
                          key=lambda r: (r['identity']['day'], r['identity']['revision']))
        opening = next(r for r in requests if not r.get('campaign'))
        correction = next((r for r in requests if r.get('campaign')
                           and r['identity']['day']==opening['identity']['day']
                           and any(s['question'].startswith('idle_army:') for s in r['signals'])), None)
        self.assertIsNotNone(correction, 'blocked scout ended its turn without a corrective request')
        self.assertEqual(correction['observation']['goal_statuses']['blocked_scout']['state'], 'blocked')
        self.assertTrue(any(s['question'].startswith('idle_army:') for s in correction['signals']))
        self.assertTrue(correction['observation']['offensive_preparation']['frontiers'])
        completed = next((r for r in campaign_records(run) if r['statuses'].get('pickup', {}).get('state')=='completed'), None)
        self.assertIsNotNone(completed, 'corrected resource target did not execute')
        self.assertEqual(completed['day'], opening['identity']['day'])
        hero = opening['observation']['heroes'][0]
        moved = next(h for h in completed['heroes'] if h['ref']==hero['ref'])
        self.assertNotEqual(moved['position'], hero['position'])
        text = (run / 'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertRegex(text, r'NK3_EXECUTION [\s\S]*?"outcome"\s*:\s*"effects_observed"')


if __name__=='__main__': unittest.main()
