"""Choose an offered safe observation area through the public strategy contract."""
import json
import os
import sys

r=json.load(sys.stdin);world=r['observation']
actor=max(world['heroes'],key=lambda h:h['army_value'])
choices=[(area,route) for area in world.get('scouting_options',[])
         for route in area['own_arrivals'] if route['hero_ref']==actor['ref']
         and route['army_loss_estimate']==0 and route['expected_new_tiles']>0]
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain',
 reason='No offered observation area yet',evidence_refs=r['evidence_refs'][:1],
 victory_method='Discover legal routes for conquest',assignments=world['strategy_assignments'],
 alternatives=[dict(approach='scouting',benefit='Discover information',cost='Movement',uncertainty='Hidden terrain'),
               dict(approach='offense',benefit='Conquest',cost='Army',uncertainty='Missing route')],
 reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in r['campaign']['goals']],
 plan=None,usage=dict(input_tokens=0,output_tokens=0,known=True))
existing=next((g for g in r['campaign']['goals'] if g['id']=='observe-area'),None)
if choices and not existing:
 area,route=min(choices,key=lambda pair:(pair[1]['day'],-pair[1]['expected_new_tiles'],pair[1]['movement_cost']))
 goal=dict(id='observe-area',kind='scout_area',actor_ref=actor['ref'],target_ref=area['ref'],
  deadline_day=world['day']+3,priority=80,building_id=-1,min_army_value=actor['army_value'],depends_on=[],
  required_capabilities=['land'],complete_when=dict(kind='area_observed',value=route['sight_radius']))
 mode=os.environ.get('NK3_SCOUT_AREA_MODE','valid')
 if mode=='unknown':goal['target_ref']='tile:[0,0,1]'
 if mode=='radius':goal['complete_when']['value']=route['sight_radius']+1
 reply.update(decision='revise',reason='Reveal the offered unknown area from a known safe tile',
  plan=dict(version=3,revision=r['identity']['revision']+1,approach='scouting',horizon_days=3,
   goals=[goal],reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
    allow_helper_replacement=True,critical_towns=[t['ref'] for t in world['towns']])),
  reconsider_when=[dict(goal_id='observe-area',kind='deadline_missed')])
print(json.dumps(reply))
