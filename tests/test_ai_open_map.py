"""Real player visibility for both AIs, with the default and explicit opt-out."""
import json
import os
from pathlib import Path
import re
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


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_OPEN_MAP_CONFIG'),
                     'requires the private compiled engine and game fixture')
class OpenMapTest(unittest.TestCase):
    def test_both_ais_reveal_every_tile_by_default_and_opt_out_keeps_fog(self):
        config = json.loads(Path(os.environ['VCMI_OPEN_MAP_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='ai-open-map-', dir=ROOT / '.build/playtests'))
        print('\nOpen-map evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture)
        with zipfile.ZipFile(fixture / DATA / 'Maps/OpenMap.vmap', 'w') as archive:
            for name, value in variants()['base'].items():
                archive.writestr(name, json.dumps(value))
        probe = ROOT / 'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture), map_resource='Maps/OpenMap.vmap',
                      players={'red': 'Nullkiller3', 'blue': 'Nullkiller2'}, nk3_mode='model',
                      controller=[sys.executable, str(probe)], controller_sources=[str(probe)],
                      references={}, purpose='integration', case_id='open-map',
                      experience_mode='off', headless=True, max_seconds=20,
                      decision_timeout_seconds=2)
        config.pop('save_resource', None)
        for mode in ('default', 'fog'):
            with self.subTest(mode=mode):
                path = output / (mode + '.json')
                path.write_text(json.dumps(config))
                run = output / mode
                subprocess.run([sys.executable, str(ROOT / 'scripts/playtest.py'), 'prepare',
                                '--config', str(path), '--out', str(run)], check=True, capture_output=True)
                env = dict(os.environ, NK3_PROBE_MODE='valid')
                env.pop('VCMI_NK3_SEED_CAMPAIGN', None)
                env.pop('VCMI_AI_OPEN_MAP', None)
                if mode == 'fog':
                    env['VCMI_AI_OPEN_MAP'] = '0'
                with (run / 'driver.log').open('w') as log:
                    child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/playtest.py'),
                                              'run', '--run', str(run)], env=env,
                                             stdout=log, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 25
                        while child.poll() is None and time.monotonic() < deadline:
                            log_path = run / 'engine-logs/VCMI_Client_log.txt'
                            text = log_path.read_text(errors='replace') if log_path.exists() else ''
                            turn_lines = '\n'.join(line for line in text.splitlines() if 'makingTurn]' in line)
                            readings = re.findall(r'AI_MAP_VISIBILITY player=(\d+) visible=(\d+) total=(\d+)', turn_lines)
                            if {p for p, _, _ in readings} >= {'0', '1'}:
                                break
                            time.sleep(.05)
                    finally:
                        (run / 'STOP').touch(exist_ok=True)
                        child.wait(timeout=15)
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'], str(run))
                self.assertTrue(launch['protected_files_unchanged'], str(run))
                self.assertTrue(json.loads((run / 'report.json').read_text())['assignment_matches'])
                requests = [json.loads(p.read_text()) for p in (run / 'decisions').glob('*/request.json')]
                self.assertTrue(requests, 'no real model observation: ' + str(run))
                distant = [o for o in requests[0]['observation']['objects'] if o['position'][0] > 20]
                self.assertEqual(bool(distant), mode == 'default', str(run))
                self.assertGreaterEqual(len(readings), 2, 'missing player visibility: ' + str(run))
                for player in ('0', '1'):
                    visible, total = next((int(v), int(t)) for p, v, t in readings if p == player)
                    self.assertGreater(total, 0)
                    if mode == 'default':
                        self.assertEqual(visible, total, 'AI sees partial map: ' + player)
                    else:
                        self.assertLess(visible, total, 'opt-out still reveals map: ' + player)
        # The runner already recorded cleanup/protection evidence. Licensed
        # profile copies are expendable after these bounded games have stopped.
        shutil.rmtree(fixture)
        for mode in ('default', 'fog'):
            shutil.rmtree(output / mode / 'profile')


if __name__ == '__main__':
    unittest.main()
