"""A legal delivery intent whose known source cannot be reached today."""
import json
import os
import sys

r=json.load(sys.stdin);world=r['observation'];hero=world['heroes'][0]
if r.get('campaign'):
    plan=r['campaign']
else:
    source=max(world['towns'],key=lambda t:t['position'][0])
    goal=dict(id='supply',kind='reinforce_hero',actor_ref=hero['ref'],target_ref=source['ref'],
        deadline_day=world['day']+(2 if os.environ.get('NK3_DEADLINE_MODE')=='timely' else 0),
        priority=90,building_id=-1,min_army_value=0,depends_on=[],
        required_capabilities=['land','transfer'],complete_when=dict(kind='army_at_least',value=12000))
    plan=dict(version=3,revision=r['identity']['revision']+1,approach='offense',horizon_days=3,
        goals=[goal],reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
                                           allow_helper_replacement=True,critical_towns=[]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain' if r.get('campaign') else 'revise',
    reason='Evaluate the known delivery deadline before spending the travel turn',
    evidence_refs=['hero:'+hero['ref']],victory_method='Reinforce the main army for conquest',
    assignments=[dict(hero_ref=hero['ref'],role='main',goal_ids=['supply'])],
    alternatives=[dict(approach='offense',benefit='Deliver troops',cost='Travel',uncertainty='Deadline feasibility'),
                  dict(approach='economy',benefit='Develop locally',cost='Build cost',uncertainty='Future income')],
    reconsider_when=[dict(goal_id='supply',kind='deadline_missed')],plan=None if r.get('campaign') else plan,
    usage=dict(input_tokens=0,output_tokens=0,known=True))
print(json.dumps(reply))
