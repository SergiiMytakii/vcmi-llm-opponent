"""Check the real garrison-to-visiting-hero action seam on the transfer fixture."""
import json
import sys

request = json.load(sys.stdin)
transfers = [a for a in request['actions'] if a['kind'] == 'transfer']
town_army = request['observation']['towns'][0]['army']
if town_army and not transfers:
    raise AssertionError('Town has troops and a visiting hero, but no transfer is offered')
action = transfers[0] if transfers else next(a for a in request['actions'] if a['kind'] == 'end_turn')
print(json.dumps({'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}))
