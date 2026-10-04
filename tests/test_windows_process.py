"""Real Windows process ownership checks; never emulate Win32 calls on macOS."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


@unittest.skipUnless(os.name == 'nt', 'requires Windows process Jobs')
class WindowsProcessTest(unittest.TestCase):
    def test_client_exit_removes_surviving_descendants_and_preserves_unicode(self):
        from windows_process import run
        with tempfile.TemporaryDirectory(prefix='game Зов ') as directory:
            root = Path(directory)
            marker = root / 'descendant survived'
            descendant = 'import time,pathlib; time.sleep(.8); pathlib.Path(' + repr(str(marker)) + ').touch()'
            code = ('import subprocess,sys,os; subprocess.Popen([sys.executable,"-c",' + repr(descendant) + ']); '
                    'print(os.environ["GAME_TEST_UNICODE"],flush=True); sys.exit(7)')
            with (root / 'log').open('wb') as log:
                result = run([sys.executable, '-c', code], cwd=root,
                             env={**os.environ, 'PYTHONUTF8': '1', 'GAME_TEST_UNICODE': 'Зов героя'},
                             log=log, cleanup_path=root / 'cleanup.json')
            self.assertEqual(result, 7)
            self.assertEqual((root / 'log').read_text(encoding='utf-8').strip(), 'Зов героя')
            self.assertTrue(json.loads((root / 'cleanup.json').read_text())['cleanup_complete'])
            time.sleep(1)
            self.assertFalse(marker.exists(), 'descendant survived the client exit')

    def test_killing_launcher_closes_its_job_and_removes_descendants(self):
        with tempfile.TemporaryDirectory(prefix='launcher Зов ') as directory:
            root = Path(directory)
            ready, survivor = root / 'ready', root / 'survivor'
            grandchild = ('import pathlib,time; pathlib.Path(' + repr(str(ready)) + ').touch(); '
                         'time.sleep(1); pathlib.Path(' + repr(str(survivor)) + ').touch()')
            child = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(grandchild) + ']); time.sleep(30)'
            helper = root / 'launch.py'
            helper.write_text('import sys,os\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\n'
                              'from windows_process import run\n'
                              'with open(' + repr(str(root / 'log')) + ',"wb") as log:\n'
                              ' run(' + repr([sys.executable, '-c', child]) + ', cwd=' + repr(str(root)) + ', env=os.environ.copy(), '
                              'log=log, cleanup_path=' + repr(str(root / 'cleanup.json')) + ')\n', encoding='utf-8')
            launcher = subprocess.Popen([sys.executable, str(helper)], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and launcher.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists(), 'launcher failed before descendant started')
                launcher.kill()
                launcher.wait(timeout=5)
                time.sleep(1.2)
                self.assertFalse(survivor.exists(), 'descendant survived a killed launcher')
            finally:
                if launcher.poll() is None:
                    launcher.kill()
                    launcher.wait(timeout=5)
