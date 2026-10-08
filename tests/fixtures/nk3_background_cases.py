"""Controlled replies through actual native callers for retained questions."""
import copy
import json
import os
import sys
import time
from strategic_intent import with_intent

r=json.load(sys.stdin);world=r['observation'];player=r['identity']['player']
case=os.environ['NK3_BG_BARRIER_CASE'];background=r.get('mode')=='prepare_next_turn'
day=r.get('execution_day',world['day'])


def goal(name,kind,actor,target,value,building=-1,deadline=None):
    predicate={'develop_town':'building_present','secure_resource':'reserve_at_least',
               'capture_target':'target_owned','reinforce_hero':'army_at_least',
               'preserve_force':'force_preserved_until','defend_area':'held_until'}[kind]
    return dict(id=name,kind=kind,actor_ref=actor,target_ref=target,deadline_day=deadline or day+5,
        priority=80,building_id=building,min_army_value=1 if actor else 0,depends_on=[],
        required_capabilities=['build'] if kind=='develop_town' else ['land','transfer'] if kind=='reinforce_hero' else ['land'],
        complete_when=dict(kind=predicate,value=value),risk=None)


town=world['towns'][0];heroes=world['heroes']
policy=copy.deepcopy(r['campaign']['policy']) if r.get('campaign') else dict(
    max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town['ref']])
goals=[];reserves=[];retain=False
if player==1:
    if background:sys.exit(1)
    time.sleep(2)
    if case=='partial':
        target=next(o for o in world['objects'] if o['kind']=='resource' and o['position'][:2]==[22,12])
        goals=[goal('open-observed-front','secure_resource',heroes[0]['ref'],target['ref'],1)]
    elif case=='stabilization':
        first=goal('reinforce','reinforce_hero',heroes[0]['ref'],town['ref'],16000)
        target=next(o for o in world['objects'] if o['kind']=='resource' and o['position'][:2]==[16,12])
        second=goal('advance','secure_resource',heroes[0]['ref'],target['ref'],1);second['depends_on']=['reinforce']
        goals=[first,second]
    else:
        options=[b for b in town['building_options'] if b['supported'] and b['id'] not in town['buildings']]
        option=options[0];goals=[goal('blue-build','develop_town',None,town['ref'],option['id'],option['id'])]
elif background:
    if case=='allocation' and world['day']!=6:sys.exit(1)
    goals=[copy.deepcopy(g) for g in r['campaign']['goals'] if world['goal_statuses'][g['id']]['state']!='completed'
           and not (case=='allocation' and g['id']=='short')]
    reserves=[copy.deepcopy(v) for v in r['campaign']['reserves'] if v['goal_id'] in {g['id'] for g in goals}]
    if case!='stabilization':
        building=11 if case=='allocation' else 1
        goals.append(goal('prepared-town','develop_town',None,town['ref'],building,building,day+3))
        quote=next(b for b in town['building_options'] if b['id']==building)
        reserves.append(dict(goal_id='prepared-town',resources=quote['cost'],force_value=0))
    if case=='partial':
        for hero in heroes:
            options=[]
            for route in world['forecasts']['routes']:
                target=next((o for o in world['objects'] if o['ref']==route['target_ref']),None)
                if not target or target['kind']!='resource' or target['ref'] not in r['allowed_target_refs']:continue
                for arrival in route['own_arrivals']:
                    if arrival['hero_ref']==hero['ref'] and arrival['army_loss_estimate']==0:
                        options.append((arrival['day'],arrival['movement_cost'],target['ref']))
            assert options,('missing controlled safe route',hero['ref'])
            target=min(options)[2]
            goals.append(goal('prepared-'+hero['ref'].replace(':','-'),'secure_resource',hero['ref'],target,1))
elif r.get('campaign'):
    time.sleep(.3)  # Let the unrelated blue transport release its process lease.
    if case=='allocation' and world['day']<7:
        goals=copy.deepcopy(r['campaign']['goals']);reserves=copy.deepcopy(r['campaign']['reserves'])
        main_budget=min(12300,world['resources'][6])
        for reserve in reserves:
            reserve['resources'][6]=main_budget if reserve['goal_id']=='main' else world['resources'][6]-main_budget
    elif case=='stabilization' and world['day']==2:
        goals=[goal('current-defense','defend_area',heroes[0]['ref'],town['ref'],4,deadline=4)]
    else:retain=True
else:
    if case=='allocation':
        goals=[goal('main','preserve_force',heroes[0]['ref'],town['ref'],8,deadline=8),
               goal('short','preserve_force',heroes[1]['ref'],town['ref'],7,deadline=7)]
        for g,h in zip(goals,heroes):g['min_army_value']=h['army_value']
        reserves=[dict(goal_id='main',resources=[0,0,0,0,0,0,9300],force_value=0),
                  dict(goal_id='short',resources=[0,0,0,0,0,0,world['resources'][6]-9300],force_value=0)]
        policy['critical_towns']=[]
    elif case=='stabilization':
        target=next(o for o in world['objects'] if o['kind']=='town' and o['owner'] in world['enemy_players'])
        offensive=goal('offense','capture_target',heroes[0]['ref'],target['ref'],player)
        offensive['risk']=dict(max_loss_ratio=.8,reason='Controlled initial supported route')
        goals=[offensive];reserves=[dict(goal_id='offense',resources=[0,0,0,0,0,0,world['resources'][6]],force_value=0)]
    else:goals=[goal('seed-town','develop_town',None,town['ref'],0,0)]

plan=None if retain else dict(version=3,revision=r['identity']['revision']+1,approach='economy',horizon_days=7,
    goals=goals,reserves=reserves,policy=policy)
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain' if retain else 'revise',
    reason='Controlled caller barrier',evidence_refs=['observation:day'],victory_method='Controlled native proof',
    assignments=world.get('strategy_assignments',[]) if r.get('campaign') else [dict(hero_ref=h['ref'],role='collector') for h in heroes],
    alternatives=[dict(approach='economy',benefit='Build',cost='Resources',uncertainty='Future'),
                  dict(approach='defense',benefit='Protect',cost='Delay',uncertainty='Intent')],
    reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in (r['campaign']['goals'] if retain else goals)],
    plan=plan,usage=dict(known=True,input_tokens=0,output_tokens=0))
reply=with_intent(r,reply)
if any(g['kind'] in ('preserve_force','defend_area') for g in (r.get('campaign') or {}).get('goals',[])):
    reply['defense_exit']=dict(waiting_for='Confirmed held date',expected_gain='Retain protected own force',next_step='Reassess at release')
if background:
    reply.update(mode='prepare_next_turn',execution_day=day,intent_revision=r['intent_revision'])
    if not r['strategic_review']:reply['alternatives']=[]
print(json.dumps(reply))
