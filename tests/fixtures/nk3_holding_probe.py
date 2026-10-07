"""One stationed defender and one independent scout through the strategy contract."""
from strategic_intent import with_intent
import json
import sys

r=json.load(sys.stdin);world=r['observation'];defender,scout=world['heroes'][:2]
if r.get('campaign'):
    plan=r['campaign']
else:
    choices=[(arrival['day'],arrival['movement_cost'],frontier['ref'])
        for frontier in world['frontier_options'] for arrival in frontier['own_arrivals']
        if arrival['hero_ref']==scout['ref'] and arrival['day']<=world['day']+1]
    frontier=min(choices)[2]
    hold=dict(id='hold',kind='defend_area',actor_ref=defender['ref'],target_ref=world['towns'][0]['ref'],
        deadline_day=world['day']+3,priority=100,building_id=-1,min_army_value=defender['army_value'],
        depends_on=[],required_capabilities=['land'],complete_when=dict(kind='held_until',value=world['day']+3))
    explore=dict(id='scout',kind='scout_frontier',actor_ref=scout['ref'],target_ref=frontier,
        deadline_day=world['day']+3,priority=70,building_id=-1,min_army_value=0,
        depends_on=[],required_capabilities=['land'],complete_when=dict(kind='frontier_observed',value=0))
    plan=dict(version=3,revision=r['identity']['revision']+1,approach='defense',horizon_days=3,
        goals=[hold,explore],reserves=[dict(goal_id='hold',resources=[0]*7,force_value=defender['army_value'])],
        policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain' if r.get('campaign') else 'revise',
    reason='Keep the defender at home while the independent scout observes the frontier',
    evidence_refs=['hero:'+defender['ref'],'hero:'+scout['ref']],victory_method='Hold home and find a safe conquest route',
    assignments=[dict(hero_ref=defender['ref'],role='defender'),
                 dict(hero_ref=scout['ref'],role='scout')],
    alternatives=[dict(approach='defense',benefit='Keep home',cost='Reserve main force',uncertainty='No known attack'),
                  dict(approach='scouting',benefit='Reveal routes',cost='Scout movement',uncertainty='Unseen terrain')],
    reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in plan['goals']],
    plan=None if r.get('campaign') else plan,usage=dict(input_tokens=0,output_tokens=0,known=True))
print(json.dumps(with_intent(r,reply)))
