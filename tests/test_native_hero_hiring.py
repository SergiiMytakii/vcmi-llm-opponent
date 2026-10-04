"""Opt-in real-engine proof of tavern hires in a disposable private profile."""
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
class NativeHeroHiringTest(unittest.TestCase):
    def test_two_helpers_spawn_and_cost_gold_without_weakening_main_army(self):
        config = json.loads(Path(os.environ['VCMI_NATIVE_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='hero-hiring-', dir=ROOT/'.build/playtests'))
        print('\nNative hero hiring evidence:', output, flush=True)
        fixture = output/'fixture'
        shutil.copytree(config['profile_template'], fixture)
        data = variants()['base']
        town = next(o for o in data['objects.json'].values() if o['type'] == 'town' and o['options']['owner'] == 'red')
        town['options']['buildings']['allOf'].append('tavern')
        town['options']['buildings']['noneOf'].remove('tavern')
        hero = next(o for o in data['objects.json'].values() if o['type'] == 'hero' and o['options']['owner'] == 'red')
        hero.update(x=6, y=13)
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/HeroHiring.vmap', 'x') as archive:
            for name, value in data.items(): archive.writestr(name, json.dumps(value))
        config.update(profile_template=str(fixture), map_resource='Maps/HeroHiring.vmap',
                      controller=[sys.executable, str(ROOT/'tests/fixtures/hire_helpers.py')],
                      controller_sources=[], references={}, purpose='integration', case_id='hero-hiring',
                      headless=True, max_seconds=35, decision_timeout_seconds=30, seed=42,
                      players={'red':'ExternalAI','blue':'EmptyAI'})
        config.pop('save_resource', None)
        path = output/'config.json'
        path.write_text(json.dumps(config))
        run = output/'run'
        subprocess.run([sys.executable, str(ROOT/'scripts/playtest.py'), 'prepare', '--config', str(path), '--out', str(run)], check=True, capture_output=True)
        requests = []
        with (output/'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(ROOT/'scripts/playtest.py'), 'run', '--run', str(run)], stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+40
                while child.poll() is None and time.monotonic() < deadline:
                    requests = []
                    for request_path in sorted(run.glob('decisions/*/request.json')):
                        try: requests.append(json.loads(request_path.read_text()))
                        except json.JSONDecodeError: continue
                    if any(len(r['observation']['heroes']) == 3 for r in requests): break
                    if any(r['observation']['day'] > 2 for r in requests): break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        launch = json.loads((run/'launch.json').read_text())
        self.assertEqual(child.returncode, 0, (output/'driver.log').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        # Large licensed fixture copies are dispensable; keep all execution evidence.
        for home in (fixture, run/'profile'):
            assets = home/'Library/Application Support/vcmi/Data'
            if assets.is_dir(): shutil.rmtree(assets)
        first = next(r for r in requests if r['request_id'] == '0:1:0')
        offers = [a for a in first['actions'] if a['kind'] == 'hire_hero']
        self.assertTrue(offers, 'owned free tavern does not offer hero hiring')
        self.assertTrue(all(a['cost'] == [0,0,0,0,0,0,2500] for a in offers))
        final = next(r for r in requests if len(r['observation']['heroes']) == 3)
        main = first['observation']['heroes'][0]
        self.assertEqual(next(h for h in final['observation']['heroes'] if h['id'] == main['id'])['army'], main['army'])
        hired = [result for result in final['memory']['recent_results'] if result['action']['kind'] == 'hire_hero']
        self.assertEqual(len(hired), 2)
        self.assertTrue(all(r['outcome'] == 'completed' for r in hired))
        day1 = next(r for r in requests if r['request_id'] == '0:1:1')
        self.assertEqual(first['observation']['resources'][6] - day1['observation']['resources'][6], 2500)
        self.assertFalse(any(a['kind'] == 'hire_hero' for a in day1['actions']), 'occupied town must not offer a second hire')


if __name__ == '__main__': unittest.main()
