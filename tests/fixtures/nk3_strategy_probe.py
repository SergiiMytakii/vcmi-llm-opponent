"""Deterministic strategic controller for the real engine boundary."""
import json
import os
import sys

r=json.load(sys.stdin)
assert r['protocol']==2 and 'actions' not in r
# Directed setup precedes proof: only actual own callback receipts are used.
# The production model receives the unmodified, current native DTO afterward.
setup_mode=os.environ.get('NK3_PROBE_MODE')
losses=[e for e in r['memory'].get('recent_results',[]) if e.get('action',{}).get('kind')=='battle'
        and e.get('outcome')=='battle_lost']
reinforced=any(e.get('goal',{}).get('id')=='restore-helper-force' for e in r['observation'].get('confirmed_deliveries',[]))
if setup_mode in ('model_after_loss','model_after_helper_reinforcement') and losses and (setup_mode=='model_after_loss' or setup_mode=='model_after_helper_reinforcement' and reinforced):
    import subprocess
    from pathlib import Path
    process=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'controller/main.py')],
                           input=json.dumps(r).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    sys.stdout.buffer.write(process.stdout);sys.stderr.buffer.write(process.stderr);sys.exit(process.returncode)
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
if mode=='model_after_helper_reinforcement':mode='restore_helper_force' if losses else 'hold_helpers'
if mode in ('hold_helpers','model_after_loss'):
    own=r['observation'];plan['goals']=[];reply['assignments']=[]
    plan['approach']='defense';plan['policy']['critical_towns']=[t['ref'] for t in own['towns']]
    reply['alternatives'][0].update(approach='defense',benefit='Hold the separate own towns',cost='Delay conquest',uncertainty='Observed hostile advance may defeat the helper')
    reply['reason']='Protect own towns with separate holders; the weak helper remains exposed to the visible hostile force.'
    for actor in own['heroes']:
        safe=min(own['towns'],key=lambda t:sum(abs(t['position'][i]-actor['position'][i]) for i in (0,1)))
        hold=dict(goal,id='hold-'+actor['ref'].replace(':','-'),kind='preserve_force',actor_ref=actor['ref'],
                  target_ref=safe['ref'],building_id=-1,min_army_value=actor['army_value'],required_capabilities=['land'],
                  complete_when=dict(kind='force_preserved_until',value=own['day']+3))
        plan['goals'].append(hold);reply['assignments'].append(dict(hero_ref=actor['ref'],role='defender'))
    reply['reconsider_when']=[dict(goal_id=g['id'],kind='deadline_missed') for g in plan['goals']]
    if r.get('campaign') and any(g['kind'] in ('preserve_force','defend_area') for g in r['campaign']['goals']):
        reply['defense_exit']=dict(waiting_for='Observe the hostile advance before day '+str(own['day']+1),
                                  expected_gain='Preserve the separate own defenders',next_step='Reassess the observed front')
if mode=='restore_helper_force':
    own=r['observation'];actor=min(own['heroes'],key=lambda h:h['army_value'])
    source=max(own['towns'],key=lambda t:t.get('defense_value',0))
    goal.update(id='restore-helper-force',kind='reinforce_hero',actor_ref=actor['ref'],target_ref=source['ref'],
                building_id=-1,min_army_value=actor['army_value']+source['defense_value'],required_capabilities=['land','transfer'],
                complete_when=dict(kind='army_at_least',value=actor['army_value']+source['defense_value']))
    reply['assignments']=[dict(hero_ref=h['ref'],role='scout' if h==actor else 'defender') for h in own['heroes']]
    reply['reconsider_when']=[dict(goal_id=goal['id'],kind='deadline_missed')]
    reply['alternatives'][0].update(approach='defense',benefit='Use the observed separate own troop pool',cost='Reduce stationary town protection',uncertainty='Hostile movement remains unknown')
    if r.get('campaign') and any(g['kind'] in ('preserve_force','defend_area') for g in r['campaign']['goals']):reply['defense_exit']=None
if mode=='battle_attribution':
    if r.get('campaign') and any(g['kind'] in ('preserve_force','defend_area') for g in r['campaign']['goals']):reply['defense_exit']=None
    reply['alternatives'][0].update(approach='defense',benefit='Retain stationary own protection while removing the visible attacker',cost='Delay the next operation',uncertainty='Other hostile forces remain unknown')
    own=r['observation'];actor=max(own['heroes'],key=lambda h:h['army_value'])
    enemy=next((o for o in own['objects'] if o.get('kind')=='hero' and o.get('visible') is True
                and o.get('owner') in own.get('enemy_players',[])),None)
    if enemy:
        goal.update(id='named-interception',kind='intercept_hero',actor_ref=actor['ref'],target_ref=enemy['ref'],
                    building_id=-1,min_army_value=actor['army_value'],required_capabilities=['land'],
                    complete_when=dict(kind='enemy_engaged',value=0),risk=dict(max_loss_ratio=.7,reason='Directed named combat proof'))
        reply['assignments']=[dict(hero_ref=actor['ref'],role='main')]
        reply['reconsider_when']=[dict(goal_id=goal['id'],kind='deadline_missed')]
    else:
        reply['assignments']=own.get('strategy_assignments',[])
    plan['policy']['max_loss_ratio']=.15
if mode in ('small_hero_delivery','disjoint_hero_delivery'):
    own=r['observation'];actor=max(own['heroes'],key=lambda h:h['army_value'])
    existing=next((g for g in (r.get('campaign') or {}).get('goals',[]) if g['id']=='small-delivery'),None)
    if existing:
        goal.update(existing)
    else:
        if mode=='disjoint_hero_delivery':
            source_ref=min((h for h in own['heroes'] if h['ref']!=actor['ref']),key=lambda h:h['army_value'])['ref']
            amount=1 # Deliberately impossible intent must not create an empty exchange.
        else:
            sources=[s for s in own['offensive_preparation']['reinforcement_sources'] if s['kind']=='hero'
                     and 0<s['unpledged_army_value']<actor['army_value']*.05 and s.get('meeting_routes')]
            source=min(sources,key=lambda s:s['unpledged_army_value'])
            source_ref=source['source_ref'];amount=source['unpledged_army_value']
        goal.update(id='small-delivery',kind='reinforce_hero',actor_ref=actor['ref'],target_ref=source_ref,
            building_id=-1,deadline_day=own['day']+2,min_army_value=actor['army_value'],
            required_capabilities=['land','transfer'],
            complete_when=dict(kind='army_at_least',value=actor['army_value']+amount))
    reply['assignments']=[dict(hero_ref=goal['actor_ref'],role='main'),
                          dict(hero_ref=goal['target_ref'],role='reinforcement')]
    reply['reconsider_when']=[dict(goal_id=goal['id'],kind='deadline_missed')]
    reply['reason']='Deliver the explicitly requested small compatible reinforcement'
    if existing:reply.update(decision='retain',plan=None,assignments=own['strategy_assignments'])
if mode=='known_passage_scout':
    own=r['observation'];actor=max(own['heroes'],key=lambda h:h['army_value'])
    existing=next((g for g in (r.get('campaign') or {}).get('goals',[]) if g['id']=='known-passage-scout'),None)
    if existing:
        goal.update(existing)
    else:
        choices=[(f,a) for f in own['frontier_options'] if f['position'][2]!=actor['position'][2]
                 for a in f.get('own_arrivals',[]) if a['hero_ref']==actor['ref']
                 and a['army_loss_estimate']<=actor['army_value']*.1 and a['day']<=own['day']+3]
        frontier,arrival=min(choices,key=lambda pair:(pair[1]['day'],pair[1]['movement_cost']))
        goal.update(id='known-passage-scout',kind='scout_frontier',actor_ref=actor['ref'],target_ref=frontier['ref'],
            building_id=-1,min_army_value=int(actor['army_value']*.8),required_capabilities=['land'],
            complete_when=dict(kind='frontier_observed',value=0))
    plan['policy']['max_loss_ratio']=.1
    reply['assignments']=[dict(hero_ref=actor['ref'],role='main')]
    reply['reconsider_when']=[dict(goal_id=goal['id'],kind='deadline_missed')]
    reply['evidence_refs']=['hero:'+actor['ref']]
    reply['reason']='Use an offered whole route through a learned passage'
    if r.get('campaign') and any(g['id']==goal['id'] for g in r['campaign']['goals']):
        reply.update(decision='retain',plan=None,assignments=own['strategy_assignments'])
if mode=='passage':
    own=r['observation']
    entries=[o for o in own['objects'] if o.get('kind')=='subterranean_gate' and o.get('visible') is True]
    choices=[h for h in own['heroes'] if 1000<=h['army_value']<=10000]
    actor=min(choices,key=lambda h:h['army_value'])
    entry=next(o for o in entries if o['position'][2]==actor['position'][2])
    goal.update(id='passage',kind='explore_passage',actor_ref=actor['ref'],target_ref=entry['ref'],building_id=-1,
                deadline_day=own['day']+3,min_army_value=actor['army_value'],required_capabilities=['land'],
                complete_when=dict(kind='passage_explored',value=0))
    reply['assignments']=[dict(hero_ref=actor['ref'],role='scout')]
    reply['reconsider_when']=[dict(goal_id='passage',kind='deadline_missed')]
    reply['evidence_refs']=['hero:'+actor['ref']]
    if r.get('campaign') and any(g['kind']=='explore_passage' for g in r['campaign']['goals']):
        reply.update(decision='retain',plan=None,assignments=own['strategy_assignments'])
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
if mode=='rejection_feedback' and r['identity']['revision']==0:
    reply['assignments']=[dict(hero_ref=r['observation']['heroes'][0]['ref'],role='defender')]
if mode=='rejection_feedback' and r['identity']['revision']>0:
    hero=r['observation']['heroes'][0]['ref']
    goal.update(id='hold-a',kind='defend_area',actor_ref=hero,target_ref=town,building_id=-1,
                min_army_value=0,deadline_day=r['observation']['day']+1,
                required_capabilities=['land'],complete_when=dict(kind='held_until',value=r['observation']['day']+1))
    if not any(item.get('outcome')=='strategy_rejected' for item in r['memory'].get('recent_results',[])):
        plan['goals'].append(dict(goal,id='hold-b'))
    reply['assignments']=[dict(hero_ref=hero,role='main')]
    reply['reconsider_when']=[dict(goal_id='hold-a',kind='deadline_missed')]
if mode=='rejection_feedback' and r['identity']['revision']>=2:
    reply.update(decision='retain',plan=None,assignments=r['observation']['strategy_assignments'],
                 reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in r['campaign']['goals']])
if mode=='invalid':plan['goals'][0]['required_capabilities']=['fly']
if mode in ('timeout','slow'):
    import time
    time.sleep(30 if mode=='slow' else 5)
print(json.dumps(reply))
