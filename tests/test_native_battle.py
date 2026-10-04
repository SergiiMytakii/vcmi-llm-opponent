"""After an actual battle, ExternalAI must resume decisions in the same turn."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'
DATA = Path('Library/Application Support/vcmi')


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_BATTLE_CONFIG'),
                     'requires an explicit private native game fixture on macOS')
class NativeBattleTest(unittest.TestCase):
    def test_completed_battle_unblocks_the_next_decision(self):
        self.run_battle()

    def test_delayed_decision_survives_recorder_and_native_deadlines(self):
        self.run_battle(decision_delay=25)

    def run_battle(self, decision_delay=0):
        source = Path(os.environ['VCMI_NATIVE_BATTLE_CONFIG']).resolve()
        config = json.loads(source.read_text())
        for key in ('engine', 'profile_template'):
            config[key] = str((source.parent / config[key]).resolve())
        config['engine_sources'] = [str((source.parent / p).resolve()) for p in config.get('engine_sources', [])]
        config.update(controller=[sys.executable, str(ROOT / 'tests/fixtures/attack_first.py'), str(decision_delay)],
                      controller_sources=[], references={}, purpose='integration',
                      case_id='battle-resume-regression', headless=True, max_seconds=55,
                      decision_timeout_seconds=37, seed=42,
                      players={'red': 'ExternalAI', 'blue': 'EmptyAI'})
        config.pop('save_resource', None)
        output = Path(tempfile.mkdtemp(prefix='battle-resume-', dir=ROOT / '.build/playtests'))
        print('\nNative battle evidence:', output, flush=True)
        profile = output / 'fixture'
        shutil.copytree(config['profile_template'], profile)
        data = variants()['base']
        for object in data['objects.json'].values():
            if object['type'] == 'monster' and object['x'] < 18:
                object['options']['amount'] = 45  # A winnable fight with actual losses.
        with zipfile.ZipFile(profile / DATA / 'Maps/BattleResume.vmap', 'x', zipfile.ZIP_DEFLATED) as archive:
            for name, value in data.items():
                archive.writestr(name, json.dumps(value))
        config.update(profile_template=str(profile), map_resource='Maps/BattleResume.vmap')
        config_path = output / 'config.json'
        config_path.write_text(json.dumps(config))
        run = output / 'run'
        subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(config_path),
                        '--out', str(run)], check=True, capture_output=True)
        requests, battle_finished = {}, None
        with (run / 'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                while child.poll() is None and time.monotonic() < deadline:
                    native_log = run / 'engine-logs/VCMI_Client_log.txt'
                    if native_log.is_file() and 'Made second apply on cl: 11BattleEnded' in native_log.read_text(errors='replace'):
                        battle_finished = battle_finished or time.monotonic()
                    for path in run.glob('decisions/*/request.json'):
                        try:
                            request = json.loads(path.read_text())
                        except json.JSONDecodeError:
                            continue
                        requests[request['request_id']] = request
                    if '0:1:1' in requests or (battle_finished and time.monotonic() - battle_finished > 8):
                        break
                    time.sleep(.05)
            finally:
                (run / 'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        self.assertEqual(child.returncode, 0, (run / 'driver.log').read_text())
        launch = json.loads((run / 'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertIsNotNone(battle_finished, 'fixture did not finish a real battle')
        self.assertTrue('0:1:1' in requests, 'AI did not resume after the engine completed its battle')
        self.assertTrue(requests['0:1:1']['observation']['heroes'], 'test hero did not survive')
        before_strength = requests['0:1:0']['observation']['heroes'][0]['strength']['army_ai_value']
        after_strength = requests['0:1:1']['observation']['heroes'][0]['strength']['army_ai_value']
        self.assertLess(after_strength, before_strength, 'real battle losses must reduce own strength')
        outcome = requests['0:1:1']['memory']['recent_results'][0]
        self.assertEqual(outcome['action']['kind'], 'attack')
        self.assertEqual(outcome['outcome'], 'progress_observed')
