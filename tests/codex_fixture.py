"""The same native subprocess boundary on Mac and Windows, with a scripted reply."""
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def codex_fixture(folder, source):
    suffix = '.exe' if os.name == 'nt' else ''
    driver = Path(os.environ.get('FAKE_CODEX_DRIVER', ROOT / ('.build/transport/fake-codex-driver' + suffix)))
    if not driver.is_file():
        raise RuntimeError('Build tests/ with CMake and set FAKE_CODEX_DRIVER to fake-codex-driver' + suffix)
    cli = folder / ('codex fixture Зов' + suffix)
    shutil.copy2(driver, cli)
    script = folder / 'codex fixture Зов.py'
    script.write_text(source, encoding='utf-8')
    return {'VCMI_CODEX_EXECUTABLE': str(cli), 'CODEX_TEST_PYTHON': sys.executable,
            'CODEX_TEST_SCRIPT': str(script), 'PYTHONUTF8': '1'}
