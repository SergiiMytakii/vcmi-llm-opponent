"""Opt-in real executable check; never launch a GUI or write the installed profile."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless((sys.platform == 'darwin' or os.name == 'nt') and os.environ.get('VCMI_NATIVE_PROFILE_ENGINE'),
                     'requires an explicit developer executable on Mac or Windows')
class NativeProfileTest(unittest.TestCase):
    def test_explicit_profile_owns_all_writable_paths_with_unicode_and_spaces(self):
        from playtesting.runs import snapshot
        engine = Path(os.environ['VCMI_NATIVE_PROFILE_ENGINE']).resolve()
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            shell = ctypes.WinDLL('shell32', use_last_error=True)
            get_documents = shell.SHGetSpecialFolderPathW
            get_documents.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int, wintypes.BOOL]
            get_documents.restype = wintypes.BOOL
            documents = ctypes.create_unicode_buffer(260)
            self.assertTrue(get_documents(None, documents, 5, False))  # Same CSIDL as VCMI.
            protected = [Path(documents.value) / 'My Games/vcmi']
        else:
            protected = [Path.home() / 'Library/Application Support/vcmi',
                         Path.home() / 'Library/Logs/vcmi']
        before = [snapshot(p) for p in protected]
        with tempfile.TemporaryDirectory(prefix='vcmi профіль ') as folder:
            root = Path(folder).resolve()
            profile = root / 'Game profile'
            env = {**os.environ, 'VCMI_PROFILE_DIR': str(profile)}
            env.pop('DYLD_INSERT_LIBRARIES', None)
            # Help exits before directory initialization: reject stock binaries.
            help_result = subprocess.run([str(engine), '--help'], env=env, cwd=engine.parent,
                                         capture_output=True, timeout=10)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn(b'VCMI_PROFILE_DIR', help_result.stdout)
            command = [str(engine), '--version']
            if sys.platform == 'darwin':
                sandbox = root / 'protect.sb'
                sandbox.write_text('(version 1)\n(allow default)\n' + ''.join(
                    f'(deny file-write* (subpath {json.dumps(str(p))}))\n' for p in protected))
                command = ['/usr/bin/sandbox-exec', '-f', str(sandbox), *command]
            result = subprocess.run(command, env=env, cwd=engine.parent, capture_output=True,
                                    text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            for label, suffix in (('user data', ''), ('user cache', 'cache'), ('user config', 'config'),
                                  ('user logs', 'logs'), ('user saves', 'Saves'),
                                  ('user extracted', 'cache/extracted')):
                line = next(line for line in result.stdout.splitlines() if label + ':' in line)
                self.assertEqual(line.split(':', 1)[1].strip(), str(profile / suffix))
            for suffix in ('', 'cache', 'config', 'logs', 'Saves'):
                self.assertTrue((profile / suffix).is_dir())
        self.assertEqual([snapshot(p) for p in protected], before)
