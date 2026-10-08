"""Validate exact visible neutral observations through the real controller seam."""
import json
from pathlib import Path
import subprocess
import sys

raw = sys.stdin.buffer.read()
request = json.loads(raw)
monsters = [o for o in request['observation']['visible_objects'] if o['kind'] == 'monster']
assert monsters, 'fixture must expose neutral creatures'
for monster in monsters:
    interval = monster['army_interval']
    assert interval['status'] == 'exact_observed', 'neutral count is still categorical'
    assert interval['lower'] == interval['estimate'] == interval['upper'] == monster['army_value']
    assert interval['stacks'], 'exact neutral creature counts must reach the model'
    for stack in interval['stacks']:
        assert type(stack['count']) is int and stack['count'] > 0
        assert type(stack['creature_id']) is int and stack['creature_id'] >= 0

result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2]/'controller/main.py')],
                        input=raw, capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
