"""Allocate a crossing's boat funds independently of another hero's reserve."""
from strategic_intent import with_intent
import json
import os
import sys

r=json.load(sys.stdin);world=r['observation'];heroes=world['heroes'];hero=heroes[0];helper=heroes[1]
town=world['towns'][0]['ref']
if r.get('campaign'):
    plan=r['campaign'];goals=plan['goals']
else:
    mine=next(o for o in world['objects'] if o['kind']=='mine' and o['visible'])
    capture=dict(id='across_water',kind='capture_target',actor_ref=hero['ref'],target_ref=mine['ref'],
        deadline_day=world['day']+6,priority=90,building_id=-1,min_army_value=0,depends_on=[],
        required_capabilities=['land','water']+(['build_boat'] if 'build_boat' in world['capabilities'] else []),
        complete_when=dict(kind='target_owned',value=world['player']))
    hold=dict(id='hold',kind='preserve_force',actor_ref=helper['ref'],target_ref=town,
        deadline_day=world['day']+6,priority=40,building_id=-1,min_army_value=89,depends_on=[],
        required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=world['day']+6))
    funded=os.environ.get('NK3_SHIPYARD_MODE','funded')=='funded'
    wood=world['resources'][0];gold=world['resources'][6]
    reserves=[dict(goal_id='hold',resources=[wood-(11 if funded else 9),0,0,0,0,0,gold-2000],force_value=0)]
    if funded:reserves.append(dict(goal_id='across_water',resources=[10,0,0,0,0,0,1000],force_value=0))
    goals=[capture,hold]
    plan=dict(version=3,revision=r['identity']['revision']+1,approach='expansion',horizon_days=6,goals=goals,
        reserves=reserves,policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain' if r.get('campaign') else 'revise',
    reason='Fund the known crossing while preserving the other obligation',evidence_refs=['hero:'+hero['ref'],'town:'+town],
    victory_method='Secure income for the public conquest condition',
    assignments=[dict(hero_ref=hero['ref'],role='main'),
                 dict(hero_ref=helper['ref'],role='defender')],
    alternatives=[dict(approach='expansion',benefit='Own the mine',cost='Boat and travel',uncertainty='Placement can change'),
                  dict(approach='economy',benefit='Develop home',cost='Building cost',uncertainty='Future income unknown')],
    reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in goals],plan=None if r.get('campaign') else plan,
    usage=dict(input_tokens=0,output_tokens=0,known=True))
print(json.dumps(with_intent(r,reply)))
