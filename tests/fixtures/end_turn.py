"""A legal no-op controller for turn-boundary and save/load checks."""
import json
import sys

request = json.load(sys.stdin)
action = next(a for a in request['actions'] if a['kind'] == 'end_turn')
print(json.dumps(dict(protocol=1, request_id=request['request_id'], action_id=action['id'])))
