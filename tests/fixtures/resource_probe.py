"""Collect the fixture's visible wood pile, then end; no model or hidden-state read."""
import json
import sys

request = json.load(sys.stdin)
choices = [a for a in request['actions'] if a['kind'] == 'visit'
           and a.get('object_type') == 79 and a.get('target', [0, 0])[1] == 13]
action = min(choices, key=lambda a: a['travel_turns']) if choices else next(
    a for a in request['actions'] if a['kind'] == 'end_turn')
print(json.dumps({'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}))
