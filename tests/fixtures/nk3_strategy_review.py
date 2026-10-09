"""Scripted decisions for the real strategic caller and early-attack control."""
import copy
from strategic_intent import with_intent


def answer(request, mode='retry'):
    world=request['observation'];day=world['day']
    actor=max(world['heroes'],key=lambda h:h['army_value'])
    home=world['towns'][0]['ref']
    enemy=next(o for o in world['objects'] if o['kind']=='town' and o.get('owner') in world['enemy_players'])
    review=any(s['question'].startswith('strategy:no_progress:') for s in request['signals'])
    attack=mode=='control' or review and day>=5
    goal=dict(id='review-attack' if attack else 'review-hold',kind='capture_target' if attack else 'preserve_force',
        actor_ref=actor['ref'],target_ref=enemy['ref'] if attack else home,deadline_day=day+6,
        priority=90,building_id=-1,min_army_value=actor['army_value'],depends_on=[],required_capabilities=['land'],
        complete_when=dict(kind='target_owned' if attack else 'force_preserved_until',value=world['player'] if attack else day+6),
        risk=dict(max_loss_ratio=.7,reason='Named controlled attack on the offered hostile base') if attack else None)
    if not attack and request.get('campaign'):
        goal=copy.deepcopy(request['campaign']['goals'][0])
    plan=dict(version=3,revision=request['identity']['revision']+1,approach='offense' if attack else 'defense',horizon_days=7,
        goals=[goal],reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
    reply=dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
        reason='Execute the named attack after the unresolved review' if attack else 'Keep a timed safety obligation',
        evidence_refs=['hero:'+actor['ref'],'target:'+enemy['ref']],victory_method='Capture the visible hostile base',
        assignments=[dict(hero_ref=actor['ref'],role='main')],
        alternatives=[dict(approach='offense',benefit='Capture hostile base',cost='Quoted losses',uncertainty='Native battle outcome'),
                      dict(approach='defense',benefit='Keep force at home',cost='Delay',uncertainty='Enemy next action')],
        reconsider_when=[dict(goal_id=goal['id'],kind='deadline_missed')],plan=plan)
    reply=with_intent(request,reply)
    if not request.get('strategic_intent'):
        selected=reply['strategy_update']['selected']
        selected['milestones'][0].update(id='conquest',description='Own the visible hostile town',depends_on=[],
            complete_when=dict(kind='target_owned',target_ref=enemy['ref'],actor_ref=None,value=world['player']))
        selected['milestones'][1]['depends_on']=['conquest']
        selected['reconsider_when']=[dict(kind='no_progress',milestone_id='conquest',reason='Review the unfinished conquest')]
    reply['operation_focus']['bindings']=[dict(goal_id=goal['id'],milestone_id='conquest')]
    if any(g['kind'] in ('preserve_force','defend_area') for g in (request.get('campaign') or {}).get('goals',[])):reply['defense_exit']=None if attack else dict(waiting_for='Timed hold exit',expected_gain='Protect home force',next_step='Requote offense')
    if review and not attack and mode=='retry':
        reply['decision_basis']['waits'][0]['purpose']='intercept' # Stable controller rejection.
    return reply
