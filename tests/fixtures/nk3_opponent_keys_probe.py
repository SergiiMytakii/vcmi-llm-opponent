"""Check privileged opponent key observations at the real engine/controller seam."""
import json
from pathlib import Path
import subprocess
import sys

raw = sys.stdin.buffer.read()
request = json.loads(raw)
world = request['observation']
keys = [o for o in world['visible_objects'] if o['kind'] in ('keymaster_tent', 'border_gate', 'border_guard')]
assert keys, 'checkpoint must expose a known key color'
for site in keys:
    access = site['opponent_key_access']
    assert access and all(k['player'] in world['enemy_players'] for k in access)
    assert all(type(k['key_owned']) is bool for k in access)
    remembered = next((o for o in world['objects'] if o['ref'] == site['ref']), None)
    if remembered is not None:
        assert remembered['opponent_key_access'] == access

# This checkpoint has a red hero beyond the unvisited white key gate.
gate = next(o for o in keys if o['ref'] == 'object:125')
assert next(k for k in gate['opponent_key_access'] if k['player'] == 0)['key_owned'] is False
approaches = [a for a in world['enemy_approaches'] if a['source_ref'] == 'object:288']
assert approaches, 'checkpoint must expose the red hero approach'
assert all(a['status'] == 'no_complete_visible_land_connection' for a in approaches)
print('Opponent keys and closed enemy approaches verified', file=sys.stderr, flush=True)

result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2]/'controller/main.py')],
                        input=raw, capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
