"""Exercise real tavern hires, moving each helper out before the next hire."""
import json
import sys

request = json.load(sys.stdin)
heroes = request['observation']['heroes']
actions = request['actions']
choice = next((a for a in actions if a['kind'] == 'hire_hero' and len(heroes) < 3), None)
if choice is None and len(heroes) < 3:
    visitors = {p['hero'] for t in request['observation']['towns']
                for p in t['stationed_heroes'] if p['role'] == 'visiting'}
    choice = next((a for a in actions if a['kind'] == 'explore' and a.get('hero') in visitors), None)
choice = choice or next(a for a in actions if a['kind'] == 'end_turn')
print(json.dumps({'protocol': 1, 'request_id': request['request_id'], 'action_id': choice['id']}))
