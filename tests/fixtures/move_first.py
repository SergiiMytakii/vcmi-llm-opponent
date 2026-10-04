"""Offline movement proof, independent of model strategy quality."""
import json
import sys

request = json.load(sys.stdin)
actions = request['actions']
moves = [a for a in actions if a['kind'] in ('explore', 'visit', 'attack')]
action = min(moves, key=lambda a: (a['kind'] == 'attack', a['travel_turns'])) if moves else next(
    a for a in actions if a['kind'] == 'end_turn')
print(json.dumps({'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}))
