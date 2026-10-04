"""Offline native recruitment proof: select only actions offered by the engine."""
import json
import sys

request = json.load(sys.stdin)
recruits = [a for a in request['actions'] if a['kind'] == 'recruit']
builds = [a for a in request['actions'] if a['kind'] == 'build']
action = max(recruits, key=lambda a: a['amount']) if recruits else (
    builds[0] if builds else next(a for a in request['actions'] if a['kind'] == 'end_turn'))
print(json.dumps({'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}))
