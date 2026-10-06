"""Opt-in real-engine turn boundaries, continuation and ordinary save loading."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from playtesting.runs import copy_snapshot_file

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_TURN_REVIEW_CONFIG'),
                     'requires an explicit private native game fixture')
class NativeTurnReviewTest(unittest.TestCase):
    def test_three_days_pause_continue_and_load_without_review(self):
        config = json.loads(Path(os.environ['VCMI_TURN_REVIEW_CONFIG']).read_text())
        config.update(players={'red': 'ExternalAI', 'blue': 'EmptyAI'},
                      controller=[sys.executable, str(ROOT / 'tests/fixtures/end_turn.py')],
                      controller_sources=[], references={}, experience_mode='off',
                      review_interval_days=3, headless=True, max_seconds=45,
                      purpose='integration', case_id='native-turn-review')
        config.pop('nk3_mode', None)
        config.pop('save_resource', None)
        output = Path(tempfile.mkdtemp(prefix='turn-review-', dir=ROOT / '.build/playtests'))
        print('\nTurn review evidence:', output, flush=True)

        def prepare(name):
            path = output / (name + '.json')
            path.write_text(json.dumps(config))
            run = output / name
            subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path),
                            '--out', str(run)], check=True, capture_output=True)
            return run

        def wait_for(child, predicate):
            deadline = time.monotonic() + 25
            while child.poll() is None and time.monotonic() < deadline:
                result = predicate()
                if result:
                    return result
                time.sleep(.05)
            self.fail('native boundary not reached: ' + str(output))

        def status(run):
            path = run / 'turn-review/state.json'
            return json.loads(path.read_text()) if path.exists() else {}

        def requests(run):
            result = []
            for path in run.glob('decisions/*/request.json'):
                try:
                    result.append(json.loads(path.read_text()))
                except json.JSONDecodeError:
                    pass
            return result

        def start(run):
            log = (run / 'driver.log').open('w')
            child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                     stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'VCMI_TURN_REVIEW_INTERVAL_DAYS': 'bad',
                                          'VCMI_TURN_REVIEW_DIRECTORY': '/missing',
                                          'VCMI_TURN_REVIEW_RUN_ID': 'bad'})
            return child, log

        def stop(run, child, log):
            (run / 'STOP').touch(exist_ok=True)
            child.wait(timeout=15)
            log.close()
            self.assertEqual(child.returncode, 0, (run / 'driver.log').read_text())
            launch = json.loads((run / 'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete'])
            self.assertTrue(launch['protected_files_unchanged'])

        first = prepare('review')
        child, log = start(first)
        try:
            checkpoint = wait_for(child, lambda: status(first) if status(first).get('status') == 'paused' else None)
            self.assertEqual(checkpoint['completed_day'], 3)
            self.assertEqual(checkpoint['next_day'], 4)
            self.assertTrue(checkpoint['save_sha256'])
            before = (first / 'turn-review/turns.jsonl').read_bytes()
            time.sleep(.5)
            self.assertEqual((first / 'turn-review/turns.jsonl').read_bytes(), before)
            turns = [json.loads(line) for line in before.splitlines()]
            ends = [(t['day'], t['player']) for t in turns if t['phase'] == 'end']
            self.assertEqual(ends, [(1, 0), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)])
            self.assertFalse(any(r['observation']['day'] >= 4 for r in requests(first)))
            result = subprocess.run([sys.executable, str(CLI), 'continue', '--run', str(first),
                                     '--completed-day', '2'], capture_output=True)
            self.assertNotEqual(result.returncode, 0, 'stale review must not release another block')
            subprocess.run([sys.executable, str(CLI), 'continue', '--run', str(first),
                            '--completed-day', '3'], check=True, capture_output=True)
            second = wait_for(child, lambda: status(first) if status(first).get('completed_day') == 6 else None)
            self.assertEqual(second['status'], 'paused')
            self.assertEqual(second['next_day'], 7)
        finally:
            stop(first, child, log)

        config.update(profile_template=str(first / 'profile'),
                      save_resource=checkpoint['save_resource'], review_interval_days=0)
        ordinary = prepare('ordinary-load')
        child, log = start(ordinary)
        try:
            wait_for(child, lambda: any(r['observation']['day'] >= 5 for r in requests(ordinary)))
            resumed = min(requests(ordinary), key=lambda r: r['observation']['day'])
            self.assertEqual(resumed['observation']['day'], 4)
            self.assertFalse((ordinary / 'turn-review').exists())
        finally:
            stop(ordinary, child, log)

        config.update(review_interval_days=3)
        resumed_run = prepare('review-load')
        child, log = start(resumed_run)
        try:
            resumed = wait_for(child, lambda: status(resumed_run) if status(resumed_run).get('status') == 'paused' else None)
            self.assertEqual(resumed['completed_day'], 6)
            self.assertEqual(resumed['next_day'], 7)
            loaded = min(requests(resumed_run), key=lambda r: r['observation']['day'])
            for field in ('heroes', 'towns', 'resources'):
                self.assertEqual(loaded['observation'][field],
                                 min(requests(ordinary), key=lambda r: r['observation']['day'])['observation'][field])
        finally:
            stop(resumed_run, child, log)

        # A completed round must remain paused when its save cannot be written.
        failed_fixture = output / 'read-only-saves'
        original = json.loads(Path(os.environ['VCMI_TURN_REVIEW_CONFIG']).read_text())
        shutil.copytree(original['profile_template'], failed_fixture, copy_function=copy_snapshot_file)
        saves = failed_fixture / 'Library/Application Support/vcmi/Saves'
        saves.mkdir(exist_ok=True)
        saves.chmod(0o555)
        config.update(profile_template=str(failed_fixture), review_interval_days=1)
        config.pop('save_resource', None)
        failed = prepare('failed-save')
        child, log = start(failed)
        try:
            wait_for(child, lambda: status(failed).get('status') == 'save_failed')
            before = (failed / 'turn-review/turns.jsonl').read_bytes()
            time.sleep(.5)
            self.assertEqual((failed / 'turn-review/turns.jsonl').read_bytes(), before)
            result = subprocess.run([sys.executable, str(CLI), 'continue', '--run', str(failed),
                                     '--completed-day', '1'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        finally:
            stop(failed, child, log)
            saves.chmod(0o700)
            (failed / 'profile/Library/Application Support/vcmi/Saves').chmod(0o700)


if __name__ == '__main__':
    unittest.main()
