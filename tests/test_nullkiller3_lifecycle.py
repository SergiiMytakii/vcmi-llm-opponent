"""Save and graceful shutdown during a real strategic wait, then restore."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a separate NK3 build and private game profile')
class StrategicLifecycleTest(unittest.TestCase):
    def test_save_while_waiting_quit_cancels_and_load_does_not_replay_unknown_request(self):
        config = json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-lifecycle-', dir=ROOT / '.build/playtests'))
        print('\nNK3 lifecycle evidence:', output, flush=True)
        probe = ROOT / 'tests/fixtures/nk3_strategy_probe.py'
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'}, nk3_mode='model', references={},
                      controller=[sys.executable,str(probe)], controller_sources=[str(probe)],
                      purpose='integration', case_id='nk3-lifecycle', headless=False,
                      max_seconds=45, decision_timeout_seconds=65, experience_mode='off')
        config.pop('save_resource', None)

        def prepare(name):
            path = output / (name+'.json'); path.write_text(json.dumps(config)); run = output / name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],
                           check=True,capture_output=True)
            return run

        first = prepare('waiting')
        with (first/'driver.log').open('w') as log:
            env = dict(os.environ, NK3_PROBE_MODE='slow'); env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            child = subprocess.Popen([sys.executable,str(CLI),'run','--run',str(first)],
                                     stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,env=env)
            try:
                deadline = time.monotonic()+20
                while not list((first/'decisions').glob('*/request.json')) and time.monotonic()<deadline:
                    self.assertIsNone(child.poll()); time.sleep(.03)
                self.assertTrue(list((first/'decisions').glob('*/request.json')))
                child.stdin.write(b'save Saves/NK3WaitingProbe\n'); child.stdin.flush()
                logfile = first/'engine-logs/VCMI_Client_log.txt'
                while 'Game has been successfully saved!' not in logfile.read_text(errors='replace') and time.monotonic()<deadline:
                    self.assertIsNone(child.poll()); time.sleep(.03)
                self.assertIn('Game has been successfully saved!',logfile.read_text(errors='replace'))
                started = time.monotonic()
                child.stdin.write(b'die, fool\n'); child.stdin.flush()
                child.wait(timeout=8)
                self.assertLess(time.monotonic()-started,5,'shutdown waited for the model deadline')
                text = logfile.read_text(errors='replace')
                self.assertTrue('strategic_exchange_cancelled' in text,'no gateway cancellation trace: '+str(first))
                self.assertNotIn('"accepted" : true',text)
            finally:
                (first/'STOP').touch(exist_ok=True)
                child.wait(timeout=15); child.stdin.close()
        launch = json.loads((first/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']); self.assertTrue(launch['protected_files_unchanged'])
        config.update(profile_template=str(first/'profile'), save_resource='Saves/NK3WaitingProbe.vsgm1',
                      headless=True,max_seconds=8)
        restored = prepare('restored')
        env = dict(os.environ,NK3_PROBE_MODE='valid'); env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        subprocess.run([sys.executable,str(CLI),'run','--run',str(restored)],env=env,
                       check=True,capture_output=True,timeout=25)
        for path in (restored/'decisions').glob('*/request.json'):
            request = json.loads(path.read_text())
            self.assertFalse(any(s['question']=='opening' for s in request['signals']),
                             'loaded game replayed the unknown pre-save opening request')
        text = (restored/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertIn('NK3_NATIVE',text,'restored budget blocked useful native play')
        launch = json.loads((restored/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']); self.assertTrue(launch['protected_files_unchanged'])


if __name__ == '__main__': unittest.main()
