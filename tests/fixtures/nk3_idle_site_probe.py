"""A completed main visit must not wait for a different hero's hold to end."""
import json
import sys

r=json.load(sys.stdin);w=r['observation']
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain',
 reason='Keep the accepted independent commitments',evidence_refs=r['evidence_refs'][:1],
 victory_method='Use known safe sites while home remains covered',assignments=w['strategy_assignments'],
 alternatives=[dict(approach='scouting',benefit='Learn useful information',cost='Movement',uncertainty='Unknown onward route'),
               dict(approach='defense',benefit='Keep home',cost='Reserve a helper',uncertainty='Future threats')],
 reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in r['campaign']['goals']],
 plan=None,usage=dict(input_tokens=0,output_tokens=0,known=True))
if not any(g['id']=='main-site' for g in r['campaign']['goals']):
 main=w['offensive_preparation']['hero_ref']
 hero=next(h for h in w['heroes'] if h['ref']==main)
 choices=[]
 for site in w['objects']:
  if site['kind'] not in ('scholar','treasure_chest','obelisk') or not site.get('visible') or site.get('visited'):continue
  for offered in w['forecasts']['routes']:
   if offered['target_ref']!=site['ref']:continue
   for route in offered['own_arrivals']:
    if route['hero_ref']==main and route['army_loss_estimate']==0 and route['day']<=w['day']+2:
     choices.append((route['movement_cost'],site['ref']))
 if not choices:
  print(json.dumps(reply));sys.exit(0)
 _,target=min(choices)
 defender=max((h for h in w['heroes'] if h['ref']!=main),key=lambda h:h['army_value'])
 goals=[dict(id='main-site',kind='visit_site',actor_ref=main,target_ref=target,
  deadline_day=w['day']+2,priority=95,building_id=-1,min_army_value=hero['army_value'],depends_on=[],
  required_capabilities=['land'],complete_when=dict(kind='site_visited',value=0)),
 dict(id='independent-hold',kind='defend_area',actor_ref=defender['ref'],target_ref=w['towns'][0]['ref'],
  deadline_day=w['day']+3,priority=85,building_id=-1,min_army_value=defender['army_value'],depends_on=[],
  required_capabilities=['land'],complete_when=dict(kind='held_until',value=w['day']+3))]
 reply.update(decision='revise',reason='Give the main a current safe site independently of helper defense',
  plan=dict(version=3,revision=r['identity']['revision']+1,approach='scouting',horizon_days=3,
   goals=goals,reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
    allow_helper_replacement=True,critical_towns=[t['ref'] for t in w['towns']])),
  reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in goals])
print(json.dumps(reply))
