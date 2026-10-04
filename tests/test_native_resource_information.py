"""Opt-in player-visible resource facts through the real engine/controller seam."""
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


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_RESOURCE_CONFIG'),
                     'requires an explicit private native resource fixture on macOS')
class NativeResourceInformationTest(unittest.TestCase):
    def capture(self, amount, abandoned_resource='gems'):
        source = Path(os.environ['VCMI_NATIVE_RESOURCE_CONFIG']).resolve()
        config = json.loads(source.read_text())
        for key in ('engine', 'profile_template'):
            config[key] = str((source.parent / config[key]).resolve())
        config['engine_sources'] = [str((source.parent / p).resolve())
                                    for p in config.get('engine_sources', [])]
        evidence = ROOT / '.build/playtests'
        evidence.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix='resource-info-', dir=evidence))
        print('\nNative resource evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture)
        data = copy.deepcopy(variants()['base'])
        for item in data['objects.json'].values():
            if item['type'] == 'resource' and item['subtype'] == 'wood' and item['x'] < 18:
                item['options']['amount'] = amount
            if item['type'] == 'mine' and item['x'] < 18:
                item.update(x=9, y=15) if item['subtype'] == 'sawmill' else item.update(x=9, y=7)
        ore_mine = next(o for o in data['objects.json'].values() if o['type'] == 'mine'
                        and o['subtype'] == 'orePit' and o['x'] < 18)
        abandoned = copy.deepcopy(ore_mine)
        abandoned.update(subtype='abandoned', x=4, y=7,
                         options={'possibleResources': [abandoned_resource]})
        data['objects.json']['mine_1000'] = abandoned
        with zipfile.ZipFile(fixture / DATA / 'Maps/ResourceInfo.vmap', 'x') as archive:
            for name, value in data.items():
                info = zipfile.ZipInfo(name, (2026, 10, 4, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, json.dumps(value))
        config.update(profile_template=str(fixture), map_resource='Maps/ResourceInfo.vmap',
                      controller=[sys.executable, str(ROOT / 'tests/fixtures/resource_probe.py')],
                      controller_sources=[], references={}, purpose='integration', case_id='resource-info',
                      headless=True, max_seconds=15, decision_timeout_seconds=5, seed=42,
                      players={'red': 'ExternalAI', 'blue': 'EmptyAI'})
        config.pop('save_resource', None)
        path = output / 'config.json'
        path.write_text(json.dumps(config))
        run = output / 'run'
        cli = ROOT / 'scripts/playtest.py'
        subprocess.run([sys.executable, str(cli), 'prepare', '--config', str(path), '--out', str(run)],
                       check=True, capture_output=True)
        requests = {}
        with (output / 'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(cli), 'run', '--run', str(run)],
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while child.poll() is None and time.monotonic() < deadline:
                    for saved in run.glob('decisions/*/request.json'):
                        try:
                            request = json.loads(saved.read_text())
                            requests[request['request_id']] = request
                        except (ValueError, KeyError):
                            continue
                    if '0:1:1' in requests:
                        break
                    time.sleep(.05)
            finally:
                (run / 'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        launch = json.loads((run / 'launch.json').read_text())
        self.assertEqual(child.returncode, 0, (output / 'driver.log').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue({'0:1:0', '0:1:1'} <= requests.keys(), str(output))
        for home in (fixture, run / 'profile'):
            assets = home / DATA / 'Data'
            if assets.is_dir():
                shutil.rmtree(assets)
        return requests

    def test_types_yields_and_post_collection_amount_without_pre_collection_leak(self):
        requests = self.capture(7)
        before, after = requests['0:1:0'], requests['0:1:1']
        self.assertEqual(before['memory'].get('schema'), 2)
        self.assertEqual(after['memory'].get('schema'), 2)
        objects = before['observation']['visible_objects']
        wood = next(o for o in objects if o['kind'] == 'resource' and o['position'][1] == 13)
        self.assertEqual(wood['resource_type'], 'wood')
        self.assertIsNone(wood['resource_amount'])
        self.assertEqual(wood['resource_amount_visibility'], 'revealed_on_collection')
        mines = [o for o in objects if o['kind'] == 'mine']
        known_mines = [o for o in mines if o['resource_type'] is not None]
        self.assertEqual({o['resource_type'] for o in known_mines}, {'wood', 'ore'})
        self.assertTrue(all(o['production_per_day'] == 2 for o in known_mines))
        self.assertTrue(all(o['production_basis'] == 'base_before_bonuses_and_handicap' for o in known_mines))
        abandoned = next(o for o in mines if o['resource_type'] is None)
        self.assertIsNone(abandoned['production_per_day'])
        self.assertEqual(abandoned['resource_visibility'], 'hidden_until_captured')
        for obj in [wood, *known_mines]:
            offers = [a for a in before['actions'] if a.get('object_id') == obj['id']]
            self.assertTrue(offers, 'fixture must expose a route to this object')
            self.assertTrue(all(a['resource_type'] == obj['resource_type'] for a in offers))
        notice = next(n for n in after['memory']['resource_notifications'] if n['resource_type'] == 'wood')
        self.assertEqual(notice['amount'], 7)
        self.assertEqual(notice['source'], 'player_info_dialog')
        self.assertEqual(after['observation']['resources'][0] - before['observation']['resources'][0], 7)

        changed = self.capture(70)['0:1:0']
        for request in (before, changed):
            request['memory'].pop('experience_id')
        self.assertEqual(before, changed, 'uncollected visible pile quantity is hidden even on a visible tile')
        hidden_mine_changed = self.capture(7, 'sulfur')['0:1:0']
        hidden_mine_changed['memory'].pop('experience_id')
        self.assertEqual(before, hidden_mine_changed, 'neutral abandoned mine production is hidden')


if __name__ == '__main__':
    unittest.main()
