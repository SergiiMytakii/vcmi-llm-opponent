"""Paired real-game checks for hidden-state invariance before and after movement."""
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


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_VISIBILITY_CONFIG'),
                     'requires an explicit private native game fixture on macOS')
class NativeVisibilityTest(unittest.TestCase):
    def test_hidden_objects_do_not_change_requests_before_or_after_movement(self):
        path = Path(os.environ['VCMI_NATIVE_VISIBILITY_CONFIG']).resolve()
        config = json.loads(path.read_text())
        for key in ('engine', 'profile_template'):
            config[key] = str((path.parent / config[key]).resolve())
        config['engine_sources'] = [str((path.parent / p).resolve()) for p in config.get('engine_sources', [])]
        config.update(controller=[sys.executable, str(ROOT / 'tests/fixtures/move_first.py')],
                      controller_sources=[], references={}, experience_mode='off',purpose='integration',
                      case_id='visibility-regression', headless=True, max_seconds=30,
                      decision_timeout_seconds=2, seed=42,
                      players={'red': 'ExternalAI', 'blue': 'EmptyAI'})
        config.pop('save_resource', None)
        output = Path(tempfile.mkdtemp(prefix='visibility-', dir=ROOT / '.build/playtests'))
        print('\nNative visibility evidence:', output, flush=True)
        profile = output / 'fixture'
        shutil.copytree(config['profile_template'], profile)
        config['profile_template'] = str(profile)
        observed = {}
        required = {'0:1:0', '0:1:1', '0:1:2'}
        for name, data in variants().items():
            if name not in ('base', 'hidden_insert', 'hidden_remove', 'hidden', 'same_category', 'different_category'):
                continue
            with self.subTest(variant=name):
                own_town = next(o for o in data['objects.json'].values()
                                if o['type'] == 'town' and o['options']['owner'] == 'red')
                own_town['options']['buildings']['allOf'].append('tavern')
                own_town['options']['buildings']['noneOf'].remove('tavern')
                map_path = profile / DATA / 'Maps/Visibility.vmap'
                with zipfile.ZipFile(map_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for filename, value in data.items():
                        archive.writestr(filename, json.dumps(value))
                config['map_resource'] = 'Maps/Visibility.vmap'
                config_path = output / (name + '.json')
                config_path.write_text(json.dumps(config))
                run = output / name
                subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(config_path),
                                '--out', str(run)], check=True, capture_output=True)
                requests = {}
                with (run / 'driver.log').open('w') as log:
                    child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                             stdout=log, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 40
                        while child.poll() is None and time.monotonic() < deadline:
                            for request_path in run.glob('decisions/*/request.json'):
                                try:
                                    request = json.loads(request_path.read_text())
                                except json.JSONDecodeError:
                                    continue
                                requests[request['request_id']] = request
                            if required <= requests.keys():
                                break
                            time.sleep(.05)
                    finally:
                        (run / 'STOP').touch(exist_ok=True)
                        child.wait(timeout=15)
                self.assertEqual(child.returncode, 0, (run / 'driver.log').read_text())
                self.assertTrue(required <= requests.keys(), str(run))
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'])
                self.assertTrue(launch['protected_files_unchanged'])
                identities = {requests[key]['memory']['experience_id'] for key in required}
                self.assertEqual(len(identities), 1, 'player-game identity changed between decisions')
                # Random UUIDs are map-independent metadata, not observable facts.
                for key in required:
                    requests[key]['memory'].pop('experience_id')
                observed[name] = {key: requests[key] for key in sorted(required)}
        (output / 'requests.json').write_text(json.dumps(observed, indent=2))
        self.assertEqual(set(observed), {'base', 'hidden', 'hidden_insert', 'hidden_remove', 'same_category', 'different_category'})
        before = observed['base']['0:1:0']['observation']['heroes'][0]['position']
        after = observed['base']['0:1:1']['observation']['heroes'][0]['position']
        self.assertNotEqual(before, after, 'fixture did not actually move the hero')
        self.assertTrue(any(a['kind'] == 'hire_hero' for r in observed['base'].values()
                            for a in r['actions']), 'fixture did not expose the player tavern pool')
        self.maxDiff = 4000
        for name in ('hidden', 'hidden_insert', 'hidden_remove', 'same_category'):
            with self.subTest(comparison=name):
                self.assertEqual(observed[name], observed['base'], str(output))
        self.assertNotEqual(observed['different_category']['0:1:0'], observed['base']['0:1:0'],
                            'permitted enemy quantity change must change the request')
