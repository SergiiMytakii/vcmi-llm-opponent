"""Exercise a legal own-hero encounter, closing its dialog without transfers."""
import json
import sys
request = json.load(sys.stdin)
actions = request['actions']
heroes = request['observation']['heroes']
choice = None
if len(heroes) == 1:
    choice = next((a for a in actions if a['kind'] == 'hire_hero'), None)
elif request['request_id'].split(':')[1:] == ['1', '1']:
    main, helper = heroes[0], heroes[1]
    choice = next((a for a in actions if a.get('hero') == main['id']
                   and a['kind'] == 'visit'
                   and a.get('target') == helper['position']), None)
choice = choice or next(a for a in actions if a['kind'] == 'end_turn')
print(json.dumps({'protocol':1,'request_id':request['request_id'],'action_id':choice['id']}))
