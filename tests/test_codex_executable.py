"""Executable selection must not launch a shell wrapper that outlives cancellation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'controller'))
from codex import resolve_executable


class CodexExecutableTest(unittest.TestCase):
    def test_explicit_native_executable_is_preserved(self):
        self.assertEqual(resolve_executable(sys.executable), str(Path(sys.executable).resolve()))

    def test_npm_windows_wrapper_resolves_to_its_native_binary(self):
        with tempfile.TemporaryDirectory(prefix='codex npm Зов ') as directory:
            root = Path(directory)
            wrapper = root / 'codex.cmd'
            wrapper.write_text('@echo off\nexit /b 99\n', encoding='utf-8')
            native = root / 'node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
            native.parent.mkdir(parents=True)
            native.write_bytes(b'fixture executable location')
            self.assertEqual(resolve_executable(str(wrapper)), str(native.resolve()))

    def test_missing_native_binary_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'codex.cmd'
            wrapper.write_text('@echo off\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'native.*codex.exe'):
                resolve_executable(str(wrapper))

    def test_environment_override_is_used_without_shell_evaluation(self):
        with patch.dict(os.environ, {'VCMI_CODEX_EXECUTABLE': sys.executable}):
            self.assertEqual(resolve_executable(), str(Path(sys.executable).resolve()))
