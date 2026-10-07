"""Real engine proof for reinforcement effects and the movement stop forecast."""
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

@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_STRATEGY_CONFIG'),
                     'requires an explicit private native fixture on macOS')
class NativeStrategyTest(unittest.TestCase):
    def test_dwelling_does_not_upgrade_but_command_keeps_count_and_spends_exact_price(self):
        source = Path(os.environ['VCMI_NATIVE_STRATEGY_CONFIG']).resolve()
        config = json.loads(source.read_text())
        output = Path(tempfile.mkdtemp(prefix='strategy-', dir=ROOT / '.build/playtests'))
        print('\nNative strategy evidence:', output, flush=True)
        profile = output / 'fixture'
        shutil.copytree(config['profile_template'], profile)
        data = variants()['base']
        for obj in data['objects.json'].values():
            if obj['type'] == 'town':
                obj['options']['buildings']['allOf'].append('dwellingLvl2')
        with zipfile.ZipFile(profile / 'Library/Application Support/vcmi/Maps/StrategyProof.vmap', 'x') as archive:
            for name, value in data.items(): archive.writestr(name, json.dumps(value))
        config.update(profile_template=str(profile), map_resource='Maps/StrategyProof.vmap',
                      controller=[sys.executable, str(ROOT / 'tests/fixtures/reinforce_probe.py')],
                      controller_sources=[], references={}, experience_mode='off',purpose='integration', case_id='strategy-proof',
                      headless=True, max_seconds=25, decision_timeout_seconds=37,
                      players={'red': 'ExternalAI', 'blue': 'EmptyAI'})
        config.pop('save_resource', None)
        config_path = output / 'config.json'
        config_path.write_text(json.dumps(config))
        run = output / 'run'
        subprocess.run([sys.executable, str(ROOT / 'scripts/playtest.py'), 'prepare', '--config', str(config_path), '--out', str(run)], check=True, capture_output=True)
        requests = {}
        with (output / 'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/playtest.py'), 'run', '--run', str(run)], stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while child.poll() is None and time.monotonic() < deadline:
                    for path in run.glob('decisions/*/request.json'):
                        try: request = json.loads(path.read_text())
                        except json.JSONDecodeError: continue
                        requests[request['request_id']] = request
                    if {'0:1:0', '0:1:1', '0:1:2', '0:2:0', '0:2:1'} <= requests.keys(): break
                    time.sleep(.05)
            finally:
                (run / 'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        self.assertEqual(child.returncode, 0, (output / 'driver.log').read_text())
        launch = json.loads((run / 'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue({'0:1:0', '0:1:1', '0:1:2', '0:2:0', '0:2:1'} <= requests.keys(), str(output))
        first, built, upgraded, moved = [requests[k] for k in ('0:1:0', '0:1:1', '0:1:2', '0:2:0')]
        self.assertEqual(first['observation']['heroes'][0]['strength']['army_ai_value'], 5720)
        self.assertEqual(upgraded['observation']['heroes'][0]['strength']['army_ai_value'], 6880)
        self.assertEqual(first['memory']['schema'], 2)
        self.assertIsNone(first['memory']['plan'])
        self.assertFalse(any(a['kind'] == 'upgrade' and a['from_creature'] == 'core:archer' for a in first['actions']))
        self.assertEqual(first['observation']['heroes'][0]['army'], built['observation']['heroes'][0]['army'])
        self.assertEqual(built['memory']['plan']['rationale'], 'Сила 5720–6880; проверка команды')
        action = next(a for a in built['actions'] if a['kind'] == 'upgrade' and a['from_creature'] == 'core:archer')
        army = upgraded['observation']['heroes'][0]['army']
        self.assertEqual(next(s['count'] for s in army if s['creature'] == action['creature']), 20)
        self.assertFalse(any(s['creature'] == 'core:archer' for s in army))
        self.assertEqual(upgraded['observation']['resources'], [r-c for r,c in zip(built['observation']['resources'], action['cost'])])
        self.assertEqual(upgraded['memory']['recent_results'][-1]['outcome'], 'completed')
        moves = [a for a in upgraded['actions'] if a['kind'] in ('visit','explore') and a['turn_stop']['condition'] == 'unchanged_route']
        self.assertTrue(moves, 'fixture must execute movement')
        move = min(moves, key=lambda a: a['travel_turns'])
        self.assertEqual(moved['observation']['heroes'][0]['position'], move['turn_stop']['position'])
        blocking = [a for a in moved['actions'] if a['kind'] == 'visit'
                    and a.get('route_encounters') and a['route_encounters'][0].get('stops_before_tile')]
        self.assertTrue(blocking, 'fixture must execute a blocking visit')
        visit = min(blocking, key=lambda a: a['travel_turns'])
        self.assertIn(requests['0:2:1']['observation']['heroes'][0]['position'], visit['turn_stop']['possible_positions'])
        self.assertNotEqual(visit['turn_stop']['position'], visit['turn_stop']['interaction_position'])
