"""The strategic request preserves the same public victory text as the lobby."""
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
from playtesting.runs import copy_snapshot_file

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'
DATA = Path('Library/Application Support/vcmi')


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an ordinary private NK3 bundle')
class PublicVictoryTest(unittest.TestCase):
    def test_special_public_victory_description_reaches_the_model_with_explicit_capability_limit(self):
        config = json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-public-victory-', dir=ROOT / '.build/playtests'))
        print('\nNK3 public-victory evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture, copy_function=copy_snapshot_file)
        world = variants()['base']
        public_text = 'Accumulate 50000 gold to win. Capturing a town alone does not win.'
        header = world['header.json']
        header['victoryMessage'] = public_text
        header['triggeredEvents']['captureTowns']['condition'] = ['haveResources', {'type': 'gold', 'value': 50000}]
        with zipfile.ZipFile(fixture / DATA / 'Maps/NK3PublicVictory.vmap', 'w') as archive:
            for name, value in world.items():
                archive.writestr(name, json.dumps(value))
        probe = ROOT / 'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture), map_resource='Maps/NK3PublicVictory.vmap',
                      players={'red': 'Nullkiller3', 'blue': 'EmptyAI'}, nk3_mode='model',
                      controller=[sys.executable, str(probe)], controller_sources=[str(probe)],
                      purpose='integration', case_id='nk3-public-victory', headless=True,
                      max_seconds=15, experience_mode='off', references={})
        config.pop('save_resource', None)
        path = output / 'config.json'
        path.write_text(json.dumps(config))
        run = output / 'game'
        subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path), '--out', str(run)],
                       check=True, capture_output=True)
        env = dict(os.environ)
        env.pop('VCMI_NK3_SEED_CAMPAIGN', None)
        with (output / 'driver.log').open('w') as log:
            child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)], env=env,
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while child.poll() is None and time.monotonic() < deadline:
                    if list((run / 'decisions').glob('*/request.json')):
                        break
                    time.sleep(.03)
            finally:
                (run / 'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        launch = json.loads((run / 'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run / 'report.json').read_text())['assignment_matches'])
        requests = [json.loads(p.read_text()) for p in (run / 'decisions').glob('*/request.json')]
        self.assertTrue(requests, 'no model request: ' + str(run))
        victory = requests[0]['observation']['victory']
        self.assertEqual(victory['kind'], 'unsupported_special', 'fixture is not a special public condition')
        self.assertFalse(victory['supported'], 'unsupported special-event execution became supported')
        self.assertEqual(victory.get('public_description'), public_text,
                         'model lost the lobby-visible victory condition: ' + str(run))


if __name__ == '__main__':
    unittest.main()
