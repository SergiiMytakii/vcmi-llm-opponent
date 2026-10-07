"""Opt-in checks of the strategy context emitted by the actual adapter."""
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
class NativeStrategyPolicyTest(unittest.TestCase):
    def test_town_defense_reports_visible_enemy_and_actual_return_options(self):
        request, _ = self.run_policy()
        self.assertEqual(request['memory']['schema'], 2)
        self.assertIsNone(request['memory']['plan'])
        town = request['observation']['towns'][0]
        self.assertIn('defense', town, 'adapter does not expose a town-defense assessment')
        defense = town['defense']
        self.assertEqual(defense['town_army_ai_value'], town['strength'])
        self.assertEqual(defense['fort_level'], 1)
        self.assertEqual(len(defense['threats']), 1)
        threat = defense['threats'][0]
        self.assertEqual(threat['position'], [6,12,0])  # Hero sprite anchor is one tile east.
        self.assertEqual(threat['age_days'], 0)
        self.assertIsNone(threat['arrival_turn_offset'])
        self.assertTrue(defense['return_options'])
        for option in defense['return_options']:
            action = next(a for a in request['actions'] if a['id'] == option['action_id'])
            self.assertEqual(option['travel_turns'], action['travel_turns'])
            self.assertEqual(option['route_steps'], action['route_steps'])

    def test_actual_level_up_selects_archery_instead_of_the_first_offered_eagle_eye(self):
        request, native = self.run_policy(level_up=True)
        hero = request['observation']['heroes'][0]
        self.assertEqual(hero['level'], 2)
        self.assertTrue(any(s['skill'].endswith('archery') and s['level'] == 1 for s in hero['secondary_skills']))
        choices = [line for line in native.splitlines() if 'secondary skill choice=' in line]
        self.assertTrue(any('choice=1' in line and 'archery' in line for line in choices), choices)

    def run_policy(self, level_up=False):
        config = json.loads(Path(os.environ['VCMI_NATIVE_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='strategy-policy-', dir=ROOT/'.build/playtests'))
        print('\nNative strategy policy evidence:', output, flush=True)
        profile = output/'fixture'
        shutil.copytree(config['profile_template'], profile)
        data = variants()['base']
        if level_up:
            hero = next(o for o in data['objects.json'].values() if o['type'] == 'hero' and o['x'] < 18)
            hero['options'].update(experience=900, secondarySkills=[{'skill':'eagleEye','level':'basic'}])
            data['header.json']['allowedAbilities'] = {'anyOf':['core:eagleEye','core:archery']}
        else:
            hero = next(o for o in data['objects.json'].values() if o['type'] == 'hero' and o['x'] < 18)
            hero.update(x=7, y=13)
            enemy = next(o for o in data['objects.json'].values() if o['type'] == 'hero' and o['x'] > 20)
            enemy.update(x=7, y=12)
        with zipfile.ZipFile(profile/'Library/Application Support/vcmi/Maps/StrategyPolicy.vmap', 'x') as archive:
            for name, value in data.items(): archive.writestr(name, json.dumps(value))
        config.update(profile_template=str(profile), map_resource='Maps/StrategyPolicy.vmap',
                      controller=[sys.executable, str(ROOT/'tests/fixtures'/('attack_first.py' if level_up else 'invalid_reply.py'))],
                      controller_sources=[], references={}, experience_mode='off',purpose='integration', case_id='strategy-policy',
                      headless=True, max_seconds=40, decision_timeout_seconds=37, seed=42,
                      players={'red':'ExternalAI','blue':'EmptyAI'})
        config.pop('save_resource', None)
        config_path = output/'config.json'
        config_path.write_text(json.dumps(config))
        run = output/'run'
        subprocess.run([sys.executable, str(ROOT/'scripts/playtest.py'), 'prepare', '--config', str(config_path), '--out', str(run)], check=True, capture_output=True)
        with (output/'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(ROOT/'scripts/playtest.py'), 'run', '--run', str(run)], stdout=log, stderr=subprocess.STDOUT)
            request = None
            try:
                deadline = time.monotonic()+45
                while child.poll() is None and time.monotonic() < deadline:
                    for path in run.glob('decisions/*/request.json'):
                        try: candidate = json.loads(path.read_text())
                        except json.JSONDecodeError: continue
                        if candidate['request_id'] == ('0:1:1' if level_up else '0:1:0'): request = candidate
                    if request: break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        self.assertEqual(child.returncode, 0, (output/'driver.log').read_text())
        launch = json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertIsNotNone(request, str(output))
        return request, (run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')


if __name__ == '__main__': unittest.main()
