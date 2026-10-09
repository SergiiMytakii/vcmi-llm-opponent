"""Controlled native caller: build completes one wait; independent delivery stays live."""
import json
import sys

r = json.load(sys.stdin)
world = r['observation']
if r.get('campaign'):
    # Rejection must not restore the obsolete hold or cancel the courier.
    raise SystemExit(75)
main, courier = sorted(world['heroes'], key=lambda h: -h['army_value'])
town = world['towns'][0]['ref']
day = world['day']
def goal(name, kind, actor, target, priority, predicate, value, force=0):
    return dict(id=name, kind=kind, actor_ref=actor, target_ref=target,
                deadline_day=day+3, priority=priority, building_id=0 if kind=='develop_town' else -1,
                min_army_value=force, depends_on=[], required_capabilities=['build'] if actor is None else ['land'],
                complete_when=dict(kind=predicate, value=value), risk=None)
build = goal('ready-guild', 'develop_town', None, town, 100, 'building_present', 0)
hold = goal('temporary-preparation', 'preserve_force', main['ref'], town, 90,
            'force_preserved_until', day+3, main['army_value'])
delivery = goal('independent-delivery', 'reinforce_hero', main['ref'], courier['ref'], 80,
                'army_at_least', main['army_value']+1, main['army_value'])
delivery['required_capabilities'] = ['land', 'transfer']
policy = dict(max_loss_ratio=.2, allow_route_repair=True, allow_helper_replacement=True, critical_towns=[])
plan = dict(version=3, revision=r['identity']['revision']+1, approach='economy', horizon_days=3,
            goals=[build, hold, delivery], reserves=[dict(goal_id=hold['id'], resources=[0]*7,
            force_value=main['army_value'])], policy=policy)
enemy = next(t for t in world['objects'] if t['kind']=='town' and t.get('owner') != world['player'])
selected = dict(objective='Capture the hostile town after preparation', selection_reason='Controlled caller proof',
    assumptions=[], milestones=[dict(id='conquest', description='Own the hostile town', depends_on=[],
    complete_when=dict(kind='target_owned',target_ref=enemy['ref'],actor_ref=None,value=world['player'])),
    dict(id='readiness',description='Confirm incoming army',depends_on=[],
         complete_when=dict(kind='army_at_least',target_ref=None,actor_ref=main['ref'],value=main['army_value']+courier['army_value'])),
    dict(id='home',description='Retain home ownership',depends_on=[],
         complete_when=dict(kind='target_owned',target_ref=town,actor_ref=None,value=world['player']))],
    reconsider_when=[dict(kind='milestone_completed',milestone_id='conquest',reason='Observe actual ownership')])
reply = dict(protocol=2, request_id=r['request_id'], identity=r['identity'], decision='revise',
    reason='Build guild during temporary preparation; the independent courier keeps its commitment',
    evidence_refs=['town:'+town,'hero:'+main['ref']], victory_method='Capture the opposing town on fresh routes',
    assignments=[dict(hero_ref=main['ref'],role='main'),dict(hero_ref=courier['ref'],role='reinforcement')],
    alternatives=[dict(approach='economy',benefit='Complete preparation',cost='One build',uncertainty='Future routes unknown'),
        dict(approach='offense',benefit='Conquest',cost='Army exposure',uncertainty='No promised future route')],
    reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in plan['goals']],plan=plan,
    strategy_update=dict(decision='revise',base_revision=0,selected=selected,change_reason='Initial selected course'),
    operation_focus=dict(revision=1,bindings=[dict(goal_id=g['id'],milestone_id='conquest') for g in plan['goals']]),
    decision_basis=dict(waits=[dict(goal_id=hold['id'],purpose='prepare',basis_goal_ids=[build['id']],next_goal_id=None)],
                        town_choices=[]), usage=dict(known=True,input_tokens=0,output_tokens=0))
print(json.dumps(reply))
