"""Controlled player-visible decisions for native townless recovery proof."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from strategic_intent import with_intent
r=json.load(sys.stdin)
if r.get('mode')=='prepare_next_turn':sys.exit(1)
w=r['observation'];rule=w.get('victory',{}).get('townless_defeat',{})
h=w['heroes'][0];day=w['day'];limit=None
if not w['towns'] and type(rule.get('own_elapsed_turns')) is int:
    limit=day+rule['turns']-rule['own_elapsed_turns']-1
marker=Path(os.environ['NK3_TOWNLESS_MARKER'])
objects={o['ref']:o for o in w['objects']}
resources=[o for o in objects.values() if o['kind']=='resource' and o.get('visible')]
towns=[o for o in objects.values() if o['kind']=='town' and o.get('visible') and o.get('owner')!=w['player']]
if limit is not None and not marker.exists() and os.environ.get('NK3_TOWNLESS_CASE')!='choice':
    marker.touch();target=resources[0];kind='secure_resource';deadline=limit+1
elif limit is not None:
    quotes={x['target_ref']:x['own_arrivals'] for x in w['forecasts']['routes']}
    eligible=[o for o in towns if any(a['hero_ref']==h['ref'] and a['day']<=limit for a in quotes.get(o['ref'],[]))]
    if not eligible:sys.exit(1)
    choose=max if os.environ.get('NK3_TOWNLESS_CASE')=='choice' else min
    target=choose(eligible,key=lambda o:min((a['day'],a['movement_cost']) for a in quotes[o['ref']] if a['hero_ref']==h['ref']))
    if os.environ.get('NK3_TOWNLESS_CASE')=='choice':
        committed={g['target_ref'] for g in (r.get('campaign') or {}).get('goals',[]) if g['kind']=='capture_target'}
        target=next((o for o in eligible if o['ref'] in committed),target)
    kind='capture_target';deadline=limit
else:
    if not resources:sys.exit(1)
    target=min(resources,key=lambda o:sum(abs(a-b) for a,b in zip(o['position'],h['position'])));kind='secure_resource';deadline=day+2
name=('rescue' if kind=='capture_target' else 'pickup')+'-'+str(day)
goal=dict(id=name,kind=kind,actor_ref=h['ref'],target_ref=target['ref'],deadline_day=deadline,
    priority=100,building_id=-1,min_army_value=0,depends_on=[],required_capabilities=['land'],risk=None,
    complete_when=dict(kind='target_owned',value=w['player']) if kind=='capture_target' else dict(kind='reserve_at_least',value=0))
plan=dict(version=3,revision=r['identity']['revision']+1,approach='expansion',horizon_days=7,goals=[goal],reserves=[],
    policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=False,critical_towns=[]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',
    reason='Controlled townless survival contract',evidence_refs=['observation:victory'],victory_method='Conquest',
    assignments=[dict(hero_ref=h['ref'],role='main')],
    alternatives=[dict(approach='expansion',benefit='Survive',cost='Force',uncertainty='Route'),dict(approach='offense',benefit='Deny base',cost='Force',uncertainty='Enemy')],
    reconsider_when=[dict(goal_id=name,kind='route_not_established')],plan=plan,usage=dict(known=True,input_tokens=0,output_tokens=0))
print(json.dumps(with_intent(r,reply)))
