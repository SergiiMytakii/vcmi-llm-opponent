"""Opt-in timeout/retry/save proof on an existing private map or checkpoint."""
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
DATA = Path('Library/Application Support/vcmi')


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_TIMEOUT_CONFIG'),
                     'requires an explicit private native game fixture on macOS')
class NativeTimeoutTest(unittest.TestCase):
    def test_timeout_retries_without_losing_turn_and_save_preserves_retry_budget(self):
        source = Path(os.environ['VCMI_NATIVE_TIMEOUT_CONFIG']).resolve()
        config = json.loads(source.read_text())
        for key in ('engine', 'profile_template'):
            config[key] = str((source.parent / config[key]).resolve())
        config['engine_sources'] = [str((source.parent / p).resolve())
                                    for p in config.get('engine_sources', [])]
        probe = ROOT / 'tests/fixtures/timeout_probe.py'
        config.update(controller=[sys.executable, str(probe), 'recover'],
                      controller_sources=[], references={}, purpose='integration',
                      case_id='timeout-save-regression', headless=False, max_seconds=180,
                      decision_timeout_seconds=18)
        config.pop('experience_database', None)
        output = Path(tempfile.mkdtemp(prefix='timeout-retry-', dir=ROOT / '.build/playtests'))
        print('\nNative timeout evidence:', output, flush=True)

        def prepare(name):
            path = output / (name + '.json')
            path.write_text(json.dumps(config))
            run = output / name
            subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path),
                            '--out', str(run)], check=True, capture_output=True)
            return run

        def requests(run):
            result = []
            for path in sorted(run.glob('decisions/*/request.json'), key=lambda p: p.stat().st_mtime):
                try:
                    result.append(json.loads(path.read_text()))
                except json.JSONDecodeError:
                    pass
            return result

        def drive(run, saving):
            with (run / 'driver.log').open('w') as log:
                child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                         stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
                sent = reached = False
                try:
                    deadline = time.monotonic() + 185
                    while child.poll() is None and time.monotonic() < deadline:
                        observed = requests(run)
                        if saving:
                            if not sent and len(observed) >= 3:
                                child.stdin.write(b'save Saves/TimeoutRetryProbe\n')
                                child.stdin.flush()
                                sent = True
                            native_log = run / 'engine-logs/VCMI_Client_log.txt'
                            reached = (native_log.is_file() and 'Game has been successfully saved!'
                                       in native_log.read_text(errors='replace'))
                        else:
                            reached = len(observed) >= 2 and observed[-1]['observation']['day'] > observed[0]['observation']['day']
                        if reached:
                            break
                        time.sleep(.1)
                finally:
                    (run / 'STOP').touch(exist_ok=True)
                    child.wait(timeout=15)
                    child.stdin.close()
                self.assertEqual(child.returncode, 0, (run / 'driver.log').read_text())
                self.assertTrue(reached, str(run))
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'])
                self.assertTrue(launch['protected_files_unchanged'])
            return requests(run)

        first = prepare('save')
        before = drive(first, True)
        self.assertEqual(len(before), 3)
        self.assertEqual({r['observation']['day'] for r in before}, {before[0]['observation']['day']})
        self.assertTrue(any(r['outcome'] in ('completed', 'progress_observed')
                            for r in before[2]['memory']['recent_results']
                            if r['sequence'] > before[0]['memory']['result_sequence']))
        timeout_record = next(p for p in first.glob('decisions/*/result.json')
                              if json.loads(p.read_text()).get('status') == 'timeout')
        self.assertEqual((timeout_record.parent / 'stdout.bin').read_bytes(), b'')
        config.update(profile_template=str(first / 'profile'),
                      save_resource='Saves/TimeoutRetryProbe.vsgm1',
                      controller=[sys.executable, str(probe), 'exhaust'],
                      headless=True)  # This stage loads but never uses the GUI console save command.
        after = drive(prepare('load'), False)
        day = after[0]['observation']['day']
        self.assertEqual([r['request_id'] for r in after if r['observation']['day'] == day],
                         [after[0]['request_id']], 'load replenished the spent retry budget')
        self.assertEqual(after[0]['observation']['turn_actions_remaining'],
                         before[2]['observation']['turn_actions_remaining'] - 1)
        self.assertEqual(after[0]['memory']['recent_results'], before[2]['memory']['recent_results'])


if __name__ == '__main__':
    unittest.main()
