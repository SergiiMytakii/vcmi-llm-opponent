"""Bounded engine smoke on an existing map; no hidden-state decisions or model calls."""
import json
import sys

request = json.load(sys.stdin)
observation, actions = request['observation'], request['actions']
day = observation['day']
history = [r for r in request['memory'].get('recent_results', []) if r['day'] == day]
moved = {r['action'].get('hero') for r in history if r['action']['kind'] in ('visit','explore','attack')}
spent = set()
resources = list(observation['resources'])
choices = []
if int(request['request_id'].split(':')[-1]) < 12:
    for action in actions:
        if action['kind'] == 'build' and action['town'] not in spent:
            if all(have >= cost for have, cost in zip(resources, action['cost'])):
                choices.append(action['id'])
                spent.add(action['town'])
                resources = [have-cost for have,cost in zip(resources, action['cost'])]
    for hero in observation['heroes']:
        if hero['id'] in moved: continue
        routes = [a for a in actions if a['kind'] == 'explore' and a['hero'] == hero['id']
                  and not a['route_encounters'] and not a['stop_threats']]
        if routes: choices.append(min(routes, key=lambda a: a['travel_turns'])['id'])
    if len(observation['heroes']) < 3:
        hire = next((a for a in actions if a['kind'] == 'hire_hero'
                     and all(have >= cost for have,cost in zip(resources,a['cost']))), None)
        if hire: choices.append(hire['id'])
if not choices: choices = [next(a['id'] for a in actions if a['kind'] == 'end_turn')]
limit = observation.get('batch_action_limit', 1)
choices = choices[:limit]
print(json.dumps({'protocol':1, 'request_id':request['request_id'],
                  'action_id':choices[0], 'follow_up_action_ids':choices[1:]}))
