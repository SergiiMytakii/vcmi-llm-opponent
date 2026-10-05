"""Deterministic strategic controller for the real engine boundary."""
import json
import os
import sys

r=json.load(sys.stdin)
assert r['protocol']==2 and 'actions' not in r
town=r['observation']['towns'][0]['ref']
goal=dict(id='guild',kind='develop_town',actor_ref=None,target_ref=town,deadline_day=r['observation']['day']+3,
          priority=80,building_id=0,min_army_value=0,depends_on=[],required_capabilities=['build'],
          complete_when=dict(kind='building_present',value=0))
plan=dict(version=3,revision=r['identity']['revision']+1,approach='economy',horizon_days=5,goals=[goal],reserves=[],
          policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',reason='Explicit building probe',
           evidence_refs=['town:'+town],victory_method='Prepare own force for public conquest',assignments=[],
           alternatives=[dict(approach='economy',benefit='Develop town',cost='Building cost',uncertainty='Future threats unknown'),
                         dict(approach='offense',benefit='Advance',cost='Army commitment',uncertainty='Enemy destination unknown')],
           reconsider_when=[dict(goal_id='guild',kind='deadline_missed')],plan=plan,
           usage=dict(input_tokens=0,output_tokens=0,known=True))
mode=os.environ.get('NK3_PROBE_MODE','valid')
if mode=='retain_seed':
    goals=r['campaign']['goals']
    reply.update(decision='retain',plan=None,assignments=[],
        reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in goals])
if mode=='three_force_events':
    own=r['observation']
    if r.get('campaign'):
        goals=r['campaign']['goals']
        reply.update(decision='retain',plan=None)
    else:
        goals=[]
        for index,source in enumerate(t for t in own['towns'] if t['army_holder_ref']!=t['ref']):
            holder=next(h for h in own['heroes'] if h['ref']==source['army_holder_ref'])
            goals.append(dict(id='hold'+str(index),kind='preserve_force',actor_ref=holder['ref'],target_ref=source['ref'],
                deadline_day=own['day']+5,priority=40,building_id=-1,min_army_value=holder['army_value'],depends_on=[],
                required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=own['day']+5)))
        plan['goals']=goals
    reply['assignments']=[dict(hero_ref=g['actor_ref'],role='defender') for g in goals]
    reply['reconsider_when']=[dict(goal_id=g['id'],kind='deadline_missed') for g in goals]
if mode=='force_history':
    if r.get('campaign'):
        existing=r['campaign']['goals'][0]
        goal.update(existing)
    else:
        own=r['observation'];source=next(t for t in own['towns'] if t['army_holder_ref']!=t['ref'])
        holder=next(h for h in own['heroes'] if h['ref']==source['army_holder_ref'])
        goal.update(id='hold',kind='preserve_force',actor_ref=holder['ref'],target_ref=source['ref'],building_id=-1,
                    deadline_day=own['day']+5,min_army_value=holder['army_value'],required_capabilities=['land'],
                    complete_when=dict(kind='force_preserved_until',value=own['day']+5))
    reply['assignments']=[dict(hero_ref=goal['actor_ref'],role='defender')]
    reply['reconsider_when']=[dict(goal_id='hold',kind='deadline_missed')]
    if r.get('campaign'):reply.update(decision='retain',plan=None)
    if r.get('campaign') and os.environ.get('VCMI_NK3_GARRISON_PROBE_MODE')=='force_loss':
        reply['identity']['generation']='old'
if mode=='garrison_slots':
    own=r['observation'];hero=own['heroes'][0]
    source=next(t for t in own['towns'] if t['army_holder_ref']!=t['ref'])
    holder=next(h for h in own['heroes'] if h['ref']==source['army_holder_ref'])
    goal.update(id='deliver',kind='reinforce_hero',actor_ref=hero['ref'],target_ref=source['ref'],building_id=-1,
                deadline_day=own['day']+5,min_army_value=hero['army_value']+1000,required_capabilities=['land','transfer'],
                complete_when=dict(kind='army_at_least',value=hero['army_value']+1000))
    hold=dict(id='hold',kind='preserve_force',actor_ref=holder['ref'],target_ref=source['ref'],
              deadline_day=own['day']+5,priority=40,building_id=-1,min_army_value=holder['army_value'],depends_on=[],
              required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=own['day']+5))
    plan['goals'].append(hold)
    reply['assignments']=[dict(hero_ref=hero['ref'],role='main'),
                          dict(hero_ref=holder['ref'],role='reinforcement')]
    reply['reconsider_when']=[dict(goal_id='deliver',kind='deadline_missed')]
    if r.get('campaign'):
        reply.update(decision='retain',plan=None)
        reply['assignments']=[dict(hero_ref=hero['ref'],role='main'),
                              dict(hero_ref=holder['ref'],role='reinforcement')]
if mode in ('scout','fronts','reachable_fronts'):
    hero=r['observation']['heroes'][0]
    choices=r['observation']['frontier_options']
    if mode=='reachable_fronts':
        choices=[f for f in choices if any(a['hero_ref']==hero['ref'] and a['day']==r['observation']['day']
                                         and a['army_loss_estimate']==0 for a in f.get('own_arrivals',[]))]
    frontier=(max(choices,key=lambda f:(f['position'][0],-abs(f['position'][1]-hero['position'][1])))
              if mode in ('fronts','reachable_fronts') and choices else r['observation']['frontier_options'][0])
    goal.update(id='scout',kind='scout_frontier',actor_ref=hero['ref'],target_ref=frontier['ref'],building_id=-1,
                required_capabilities=['land'],complete_when=dict(kind='frontier_observed',value=0))
    reply['assignments']=[dict(hero_ref=hero['ref'],role='scout')]
    reply['reconsider_when']=[dict(goal_id='scout',kind='deadline_missed')]
    reply['evidence_refs']=['hero:'+hero['ref']]
    if mode=='reachable_fronts' and not choices and r.get('campaign'):
        reply.update(decision='retain',plan=None)
if mode=='resource':
    hero=r['observation']['heroes'][0]
    def distance(o):return max(abs(hero['position'][i]-o['position'][i]) for i in (0,1))
    resource=min((o for o in r['observation']['visible_objects'] if o['kind']=='resource'),key=distance)
    goal.update(id='supply',kind='secure_resource',actor_ref=hero['ref'],target_ref=resource['ref'],building_id=-1,
                required_capabilities=['land'],complete_when=dict(kind='reserve_at_least',value=1000))
    reply['assignments']=[dict(hero_ref=hero['ref'],role='collector')]
    reply['reconsider_when']=[dict(goal_id='supply',kind='deadline_missed')]
    reply['evidence_refs']=['hero:'+hero['ref'],'target:'+resource['ref']]
if mode=='economy':
    hero=r['observation']['heroes'][0]
    goal.update(id='income',building_id=12,deadline_day=r['observation']['day']+6,
                complete_when=dict(kind='building_present',value=12))
    plan['horizon_days']=7
    hold=dict(id='defense_floor',kind='preserve_force',actor_ref=hero['ref'],target_ref=town,
              deadline_day=r['observation']['day']+6,priority=20,building_id=-1,min_army_value=1000,
              depends_on=[],required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=r['observation']['day']+6))
    plan['goals'].append(hold)
    plan['reserves']=[dict(goal_id='defense_floor',resources=[0,0,0,0,0,0,1000],force_value=1000)]
    reply['assignments']=[dict(hero_ref=hero['ref'],role='defender')]
    reply['reconsider_when']=[dict(goal_id='income',kind='deadline_missed')]
if mode=='stale':reply['identity']['generation']='old'
if mode=='invalid':plan['goals'][0]['required_capabilities']=['fly']
if mode in ('timeout','slow'):
    import time
    time.sleep(30 if mode=='slow' else 5)
print(json.dumps(reply))
