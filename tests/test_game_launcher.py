"""Developer launcher through its public command line, using private fixture data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/play.py'


class GameLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vcmi launcher тест ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'Original Data'
        self.data.mkdir()
        (self.data / 'H3bitmap.lod').write_bytes(b'private fixture, not game assets')
        self.profile = self.root / 'Separate profile'

    def cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True,
                              text=True, timeout=10)

    def test_new_profile_copies_data_and_creates_the_restricted_map_without_overwriting(self):
        args = ('init', '--data', self.data, '--profile', self.profile)
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.profile / 'Data/H3bitmap.lod').read_bytes(),
                         b'private fixture, not game assets')
        with zipfile.ZipFile(self.profile / 'Maps/LandDuel-v1.vmap') as archive:
            header = json.loads(archive.read('header.json'))
            self.assertEqual(set(header['players']), {'red', 'blue'})
            self.assertEqual(header['triggeredEvents']['captureTowns']['condition'],
                             ['control', {'type': 'town'}])
        settings = json.loads((self.profile / 'config/settings.json').read_text())
        self.assertEqual(settings['ai']['adventureEnemyAI'], 'ExternalAI')
        (self.profile / 'Saves').mkdir()
        saved = self.profile / 'Saves/Keep.vsgm1'
        saved.write_bytes(b'existing saved game')
        result = self.cli(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved.read_bytes(), b'existing saved game')
        self.assertEqual((self.data / 'H3bitmap.lod').read_bytes(), b'private fixture, not game assets')

    def test_run_refuses_an_engine_without_isolation_before_changing_settings(self):
        self.assertEqual(self.cli('init', '--data', self.data, '--profile', self.profile).returncode, 0)
        settings = self.profile / 'config/settings.json'
        before = settings.read_bytes()
        result = self.cli('run', '--engine', sys.executable, '--profile', self.profile,
                          '--mode', 'human', '--codex', sys.executable, '--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('native profile isolation', result.stderr)
        self.assertEqual(settings.read_bytes(), before)
