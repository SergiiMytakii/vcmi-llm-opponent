"""Choose a visible scholar through the same public campaign reply contract."""
import json
import os
import sys

r=json.load(sys.stdin);w=r['observation']
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain',
 reason='No typed known scholar is offered',evidence_refs=r['evidence_refs'][:1],
 victory_method='Improve an own hero through known safe sites',assignments=w['strategy_assignments'],
 alternatives=[dict(approach='scouting',benefit='Learn useful information',cost='Movement',uncertainty='Unknown onward route'),
               dict(approach='economy',benefit='Develop own heroes',cost='Movement',uncertainty='Unknown scholar lesson')],
 reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in r['campaign']['goals']],
 plan=None,usage=dict(input_tokens=0,output_tokens=0,known=True))
choices=[]
for site in w['objects']:
 if site['kind']!=os.environ.get('NK3_SITE_KIND','scholar') or not site.get('visible') or site.get('visited'):continue
 for offered in w['forecasts']['routes']:
  if offered['target_ref']!=site['ref']:continue
  for route in offered['own_arrivals']:
   hero=next(h for h in w['heroes'] if h['ref']==route['hero_ref'])
   if route['army_loss_estimate']==0 and route['day']<=w['day']+2:
    choices.append((hero,site,route))
if choices and not any(g['id']=='learn-site' for g in r['campaign']['goals']):
 hero,site,route=min(choices,key=lambda a:(a[0]['army_value'],a[2]['day'],a[2]['movement_cost']))
 goal=dict(id='learn-site',kind='visit_site',actor_ref=hero['ref'],target_ref=site['ref'],
  deadline_day=w['day']+2,priority=90,building_id=-1,min_army_value=hero['army_value'],depends_on=[],
  required_capabilities=['land'],complete_when=dict(kind='site_visited',value=0))
 reply.update(decision='revise',reason='Visit an offered known scholar with a safe own helper',
  plan=dict(version=3,revision=r['identity']['revision']+1,approach='scouting',horizon_days=3,
   goals=[goal],reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
    allow_helper_replacement=True,critical_towns=[t['ref'] for t in w['towns']])),
  reconsider_when=[dict(goal_id='learn-site',kind='deadline_missed')])
print(json.dumps(reply))
