"""Opt-in save/load regression through the real isolated game and tester CLI.

VCMI_NATIVE_CAMPAIGN_CONFIG must name a working macOS playtest configuration for
LandDuel-v1.vmap. Its private profile and installed game are never modified.
"""
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


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_CAMPAIGN_CONFIG'),
                     'requires an explicit private native game fixture on macOS')
class NativeCampaignSaveLoadTest(unittest.TestCase):
    def test_campaign_profile_review_and_inflight_save_restore_without_replaying_purchase(self):
        config_path = Path(os.environ['VCMI_NATIVE_CAMPAIGN_CONFIG']).resolve()
        config = json.loads(config_path.read_text())
        # Resolve relative configuration paths before relocating this fixture.
        for key in ('engine', 'profile_template'):
            config[key] = str((config_path.parent / config[key]).resolve())
        config['engine_sources'] = [str((config_path.parent / p).resolve())
                                    for p in config.get('engine_sources', [])]
        config.update(controller=[sys.executable, str(ROOT / 'tests/fixtures/campaign_save_probe.py')],
                      controller_sources=[], references={}, experience_mode='off',purpose='integration',
                      case_id='campaign-save-load', headless=False, max_seconds=40,
                      decision_timeout_seconds=18,
                      players={'red': 'ExternalAI', 'blue': 'EmptyAI'})
        config.pop('save_resource', None)
        output = Path(tempfile.mkdtemp(prefix='save-load-', dir=ROOT / '.build/playtests'))
        print('\nNative save/load evidence:', output)

        def prepare(name, settings):
            path = output / (name + '.json')
            path.write_text(json.dumps(settings))
            run = output / name
            subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path),
                            '--out', str(run)], check=True, capture_output=True)
            return run

        def requests(run):
            result = {}
            for path in run.glob('decisions/*/request.json'):
                try:
                    request = json.loads(path.read_text())
                except json.JSONDecodeError:
                    continue
                result[request['request_id']] = request
            return result

        def drive(run, saving):
            with (run / 'driver.log').open('w') as log:
                child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                         stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
                sent = False
                reached = False
                try:
                    deadline = time.monotonic() + 50
                    while child.poll() is None and time.monotonic() < deadline:
                        observed = requests(run)
                        if saving:
                            if not sent and '0:1:1' in observed:
                                child.stdin.write(b'save Saves/ExternalAIProbe\n')
                                child.stdin.flush()
                                sent = True
                            native_log = run / 'engine-logs/VCMI_Client_log.txt'
                            reached = (native_log.is_file() and 'Game has been successfully saved!'
                                       in native_log.read_text(errors='replace'))
                        else:
                            reached = '0:2:0' in observed
                        if reached:
                            break
                        time.sleep(0.1)
                finally:
                    (run / 'STOP').touch(exist_ok=True)
                    child.wait(timeout=15)
                    child.stdin.close()
                self.assertEqual(child.returncode, 0, (run / 'driver.log').read_text())
                self.assertTrue(reached, str(run))
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'])
                self.assertTrue(launch['protected_files_unchanged'])
                self.assertIn(str(run / 'profile' / DATA / 'Saves'),
                              (run / 'preflight.stdout.log').read_text(),
                              'preflight must verify the actual native writable paths')
            return requests(run)

        first = prepare('save', config)
        initial = drive(first, saving=True)
        before = initial['0:1:1']
        self.assertEqual(before['memory']['plan']['goal'], 'Save/load integration probe')
        self.assertEqual(before['memory']['campaign']['approach'], 'economy')
        self.assertEqual(before['observation']['victory']['kind'], 'control_all_towns')
        self.assertTrue(before['observation']['victory']['supported'])
        hero = before['observation']['heroes'][0]
        self.assertIn('specialty', hero['profile'])
        self.assertIn('known_spells', hero['profile'])
        town = before['observation']['towns'][0]
        faction = before['observation']['rules']['factions'][town['faction']]
        self.assertEqual(faction['creature_lineup'][1][0]['creature'], 'core:archer')
        self.assertTrue(faction['creature_lineup'][1][0]['ranged'])
        self.assertTrue(all('cost' in b and 'requirements' in b for b in faction['buildings']))
        self.assertEqual(before['memory']['campaign_assessment']['decision'], 'revise')
        self.assertEqual(before['memory']['recent_results'][0]['outcome'], 'completed')
        config.update(profile_template=str(first / 'profile'),
                      save_resource='Saves/ExternalAIProbe.vsgm1')
        restored = drive(prepare('load', config), saving=False)
        self.assertEqual({key for key in restored if key.startswith('0:1:')}, {'0:1:2'})
        after = restored['0:1:2']
        self.assertEqual(after['observation']['turn_actions_remaining'],
                         before['observation']['turn_actions_remaining'] - 1)
        self.assertEqual(after['memory']['plan'], before['memory']['plan'])
        self.assertEqual(after['memory']['campaign'], before['memory']['campaign'])
        self.assertEqual(after['memory']['campaign_assessment'], before['memory']['campaign_assessment'])
        self.assertEqual(after['memory']['campaign_review'], before['memory']['campaign_review'])
        self.assertEqual(after['memory']['experience_id'], before['memory']['experience_id'])
        self.assertEqual(after['memory']['recent_results'], before['memory']['recent_results'])
        for key in ('resources', 'towns', 'heroes'):
            self.assertEqual(after['observation'][key], before['observation'][key])
        self.assertFalse(any(action['kind'] == 'build' for action in after['actions']))
        self.assertEqual(restored['0:2:0']['observation']['turn_actions_remaining'],
                         initial['0:1:0']['observation']['turn_actions_remaining'])


if __name__ == '__main__':
    unittest.main()
