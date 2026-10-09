"""Exact visible enemy troops reach the model; fog still hides enemy armies."""
import copy
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
DATA = Path('Library/Application Support/vcmi')


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_EXACT_ENEMY_CONFIG'),
                     'requires a separate native build and private game data')
class ExactEnemyArmiesTest(unittest.TestCase):
    def test_visible_enemy_counts_are_exact_and_hidden_counts_do_not_leak(self):
        config = json.loads(Path(os.environ['VCMI_EXACT_ENEMY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='exact-enemy-', dir=ROOT / '.build/playtests'))
        print('\nExact enemy evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture)
        probe = ROOT / 'tests/fixtures/exact_enemy_probe.py'
        config.update(profile_template=str(fixture), map_resource='Maps/ExactEnemy.vmap',
                      players={'red': 'Nullkiller3', 'blue': 'EmptyAI'}, nk3_mode='model',
                      controller=[sys.executable, str(probe)], controller_sources=[str(probe)],
                      references={}, purpose='integration', case_id='exact-enemy',
                      headless=True, max_seconds=15, experience_mode='off', review_interval_days=1)
        config.pop('save_resource', None)
        observations = {}
        try:
            for name, count, hidden_count in [('base', 15, 100), ('visible', 19, 100), ('hidden', 15, 40000)]:
                world = variants()['base']
                objects = world['objects.json']
                enemy = next(o for o in objects.values() if o['type'] == 'hero' and o['options']['owner'] == 'blue')
                hidden_hero = copy.deepcopy(enemy)
                hidden_hero['options']['type'] = 'christian'
                hidden_hero['options']['army'] = [{'type': 'core:pikeman', 'amount': hidden_count}]
                objects['hero_1000'] = hidden_hero
                enemy.update(x=11, y=11)
                enemy['options']['army'] = [{'type': 'core:pikeman', 'amount': count}]
                town = next(o for o in objects.values() if o['type'] == 'town' and o['options']['owner'] == 'blue')
                hidden_town = copy.deepcopy(town)
                hidden_town['options']['army'] = [{'type': 'core:pikeman', 'amount': hidden_count}]
                objects['town_1001'] = hidden_town
                town.update(x=13, y=14)
                town['options']['army'] = [{'type': 'core:pikeman', 'amount': 17}]
                hidden = next(o for o in objects.values() if o['type'] == 'monster' and o['x'] > 20)
                hidden['options']['amount'] = hidden_count
                with zipfile.ZipFile(fixture / DATA / 'Maps/ExactEnemy.vmap', 'w') as archive:
                    for filename, value in world.items():
                        archive.writestr(filename, json.dumps(value))
                path = output / (name + '.json')
                path.write_text(json.dumps(config))
                run = output / name
                subprocess.run([sys.executable, str(ROOT / 'scripts/playtest.py'), 'prepare',
                                '--config', str(path), '--out', str(run)], check=True, capture_output=True)
                with (output / (name + '.log')).open('w') as log:
                    child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/playtest.py'), 'run', '--run', str(run)],
                                             env=dict(os.environ, VCMI_AI_OPEN_MAP='0'), stdout=log, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 25
                        requests = []
                        while child.poll() is None and time.monotonic() < deadline:
                            requests = list((run / 'decisions').glob('*/request.json'))
                            if requests:
                                break
                            time.sleep(.05)
                    finally:
                        (run / 'STOP').touch(exist_ok=True)
                        child.wait(timeout=20)
                self.assertTrue(requests, 'no model request: ' + str(run))
                request = json.loads(requests[0].read_text())
                visible = request['observation']['visible_objects']
                enemies = [o for o in visible if o.get('owner') == 1 and o['kind'] in ('hero', 'town')]
                self.assertEqual({o['kind'] for o in enemies}, {'hero', 'town'})
                for obj in enemies:
                    interval = obj['army_interval']
                    expected_count = count if obj['kind'] == 'hero' else 17
                    self.assertEqual(interval['status'], 'exact_observed')
                    self.assertEqual(interval['stacks'], [{'creature_id': 0, 'count': expected_count}])
                    self.assertEqual(interval['lower'], expected_count * 89)
                    self.assertEqual(interval['estimate'], expected_count * 89)
                    self.assertEqual(interval['upper'], expected_count * 89)
                    self.assertEqual(obj['army_value'], expected_count * 89)
                observations[name] = visible
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'])
                self.assertTrue(launch['protected_files_unchanged'])
            self.assertEqual(observations['base'], observations['hidden'])
            self.assertNotEqual(observations['base'], observations['visible'])
        finally:
            # Retain requests/receipts, remove only this test's licensed data copies.
            shutil.rmtree(fixture, ignore_errors=True)
            for run in output.iterdir():
                receipt = run / 'launch.json'
                if receipt.is_file() and json.loads(receipt.read_text()).get('cleanup_complete'):
                    shutil.rmtree(run / 'profile', ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
