"""Issue one own capture intention across observed water; no engine commands."""
import json
import sys

r=json.load(sys.stdin)
world=r['observation']
hero=world['heroes'][0]
mine=next(o for o in world['objects'] if o['kind']=='mine' and o['visible'])
goals=r.get('campaign',{}).get('goals',[]) if r.get('campaign') else []
goal=goals[0] if goals else dict(id='across_water',kind='capture_target',actor_ref=hero['ref'],target_ref=mine['ref'],
    deadline_day=world['day']+6,priority=90,building_id=-1,min_army_value=0,depends_on=[],
    required_capabilities=['land','water'] if 'water' in world['capabilities'] else ['land'],
    complete_when=dict(kind='target_owned',value=world['player']))
plan=dict(version=3,revision=r['identity']['revision']+1,approach='expansion',horizon_days=6,goals=[goal],reserves=[],
    policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain' if goals else 'revise',
    reason='Capture the observed mine using a legal native route',evidence_refs=['hero:'+hero['ref'],'target:'+mine['ref']],
    victory_method='Secure income for the public conquest condition',
    assignments=[dict(hero_ref=hero['ref'],role='main')],
    alternatives=[dict(approach='expansion',benefit='Own the known mine',cost='Travel time',uncertainty='Route may change'),
                  dict(approach='economy',benefit='Develop home',cost='Building cost',uncertainty='Future income unknown')],
    reconsider_when=[dict(goal_id=goal['id'],kind='deadline_missed')],plan=None if goals else plan,
    usage=dict(input_tokens=0,output_tokens=0,known=True))
print(json.dumps(reply))
