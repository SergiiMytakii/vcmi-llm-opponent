"""Turn-review configuration and control through the public tester CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


class TurnReviewTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'macOS tester launch boundary')
    def test_checkpoint_during_last_poll_waits_for_review_past_deadline(self):
        # This process implements the external engine control contract. Real game
        # turn ordering and save compatibility are covered by the native test.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'fixture/Library/Application Support/vcmi'
            (data / 'Maps').mkdir(parents=True)
            (data / 'config').mkdir()
            (data / 'Maps/Trial.h3m').write_bytes(b'fixture')
            (data / 'config/settings.json').write_text('{}')
            engine = root / '.build/vcmiclient'
            engine.parent.mkdir()
            engine.write_text('#!' + sys.executable + '\n' + '''
import json, os, pathlib, sys, time
profile = pathlib.Path(os.environ['VCMI_PROFILE_DIR'])
if '--help' in sys.argv:
    print('VCMI_PROFILE_DIR VCMI_TURN_REVIEW_INTERVAL_DAYS')
    sys.exit(0)
if '--version' in sys.argv:
    for label, suffix in [('data',''),('cache','cache'),('config','config'),('logs','logs'),
                          ('saves','Saves'),('extracted','cache/extracted')]:
        print('user ' + label + ': ' + str(profile / suffix))
    sys.exit(0)
run = pathlib.Path(os.environ['VCMI_PLAYTEST_RUN'])
launch = run / 'launch.json'
while not launch.exists(): time.sleep(.005)
deadline = launch.stat().st_mtime + 1
while time.time() < deadline - .05: time.sleep(.005)
(profile / 'Saves').mkdir(exist_ok=True)
(profile / 'Saves/probe.vsgm1').write_bytes(b'completed checkpoint')
state = dict(status='paused', completed_day=3, next_day=4, interval_days=3,
             save_resource='Saves/probe.vsgm1')
review = run / 'turn-review'
(review / 'native-state.tmp').write_text(json.dumps(state))
os.replace(review / 'native-state.tmp', review / 'native-state.json')
while True: time.sleep(.05)
''')
            engine.chmod(0o700)
            config = root / 'config.json'
            config.write_text(json.dumps(dict(version=1, case_id='deadline-review', purpose='integration',
                engine=str(engine), profile_template=str(root / 'fixture'), map_resource='Maps/Trial.h3m',
                controller=[sys.executable], players={'red':'EmptyAI','blue':'EmptyAI'},
                difficulty='normal', max_seconds=1, review_interval_days=3, headless=True)))
            run = root / 'run'
            subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(config),
                            '--out', str(run)], check=True, capture_output=True)
            with (root / 'driver.log').open('w') as log:
                child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                         stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 10
                    while child.poll() is None and not (run / 'turn-review/native-state.json').exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue((run / 'turn-review/native-state.json').exists())
                    time.sleep(.5)
                    self.assertIsNone(child.poll(), 'review pause was terminated at the gameplay deadline')
                    self.assertTrue((run / 'turn-review/state.json').exists(),
                                    'gameplay deadline skipped the completed checkpoint')
                    self.assertEqual(json.loads((run / 'turn-review/state.json').read_text())['status'], 'paused')
                finally:
                    if child.poll() is None:
                        (run / 'STOP').touch(exist_ok=True)
                    child.wait(timeout=15)

    def test_invalid_review_interval_cannot_prepare_a_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / 'fixture'
            data = profile / 'Library/Application Support/vcmi'
            (data / 'Maps').mkdir(parents=True)
            (data / 'config').mkdir()
            (data / 'Maps/Trial.h3m').write_bytes(b'fixture')
            (data / 'config/settings.json').write_text('{}')
            config = dict(version=1, case_id='review', purpose='integration',
                          engine=sys.executable, profile_template=str(profile),
                          map_resource='Maps/Trial.h3m', controller=[sys.executable],
                          players={'red': 'EmptyAI', 'blue': 'EmptyAI'},
                          difficulty='normal', max_seconds=10)
            for index, interval in enumerate((-1, True, 1.5, '3')):
                with self.subTest(interval=interval):
                    config['review_interval_days'] = interval
                    source = root / 'config.json'
                    source.write_text(json.dumps(config))
                    result = subprocess.run([sys.executable, str(CLI), 'prepare',
                                             '--config', str(source), '--out', str(root / str(index))],
                                            capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('review_interval_days', result.stderr)
                    self.assertFalse((root / str(index)).exists())


if __name__ == '__main__':
    unittest.main()
