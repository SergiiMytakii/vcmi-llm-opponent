"""The same native subprocess boundary on Mac and Windows, with a scripted reply."""
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def codex_fixture(folder, source, expand_context=True):
    suffix = '.exe' if os.name == 'nt' else ''
    driver = Path(os.environ.get('FAKE_CODEX_DRIVER', ROOT / ('.build/transport/fake-codex-driver' + suffix)))
    if not driver.is_file():
        raise RuntimeError('Build tests/ with CMake and set FAKE_CODEX_DRIVER to fake-codex-driver' + suffix)
    cli = folder / ('codex fixture Зов' + suffix)
    shutil.copy2(driver, cli)
    script = folder / 'codex fixture Зов.py'
    if expand_context:
        # Existing scripted models operate on logical game facts. Interpret the
        # documented wire format independently of the production encoder.
        source = '''
import io, json, sys
if sys.argv[1:2] == ['exec']:
    wire = json.load(sys.stdin)
    if set(wire) == {'reference_key', 'shared', 'request'}:
        marker, definitions = wire['reference_key'], wire['shared']
        def expand(value):
            if isinstance(value, dict):
                if list(value) == [marker]:
                    return expand(definitions[value[marker]])
                return {key:expand(item) for key,item in value.items()}
            if isinstance(value, list):
                return [expand(item) for item in value]
            return value
        wire = expand(wire['request'])
    sys.stdin = io.StringIO(json.dumps(wire))
''' + source
    script.write_text(source, encoding='utf-8')
    return {'VCMI_CODEX_EXECUTABLE': str(cli), 'CODEX_TEST_PYTHON': sys.executable,
            'CODEX_TEST_SCRIPT': str(script), 'PYTHONUTF8': '1'}
