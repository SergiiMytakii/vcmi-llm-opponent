"""Fixed strategic contract for native route selection, without a model."""
import json
import sys

request=json.load(sys.stdin)
world=request['observation']
hero=next(h for h in world['heroes'] if h['position']==[5,11,0])
target=next(o for o in world['visible_objects'] if o['kind']=='mine' and o['position']==[7,13,0])
goal=dict(id='capture',kind='capture_target',actor_ref=hero['ref'],target_ref=target['ref'],
          deadline_day=world['day']+5,priority=80,building_id=-1,min_army_value=0,depends_on=[],
          required_capabilities=['land'],complete_when=dict(kind='target_owned',value=world['player']))
plan=dict(version=3,revision=request['identity']['revision']+1,approach='expansion',horizon_days=5,
          goals=[goal],reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
          allow_helper_replacement=True,critical_towns=[world['towns'][0]['ref']]))
assignment=dict(hero_ref=hero['ref'],role='main',goal_ids=['capture'])
if request.get('campaign'):
    goal=request['campaign']['goals'][0]
    assignment['hero_ref']=goal['actor_ref']
json.dump(dict(protocol=2,request_id=request['request_id'],identity=request['identity'],
               decision='retain' if request.get('campaign') else 'revise',reason='Fixed native ranking operation',
               evidence_refs=['hero:'+hero['ref']],victory_method='Capture a visible income source',
               assignments=[assignment],alternatives=[
                   dict(approach='expansion',benefit='Secure income',cost='Movement',uncertainty='Later fronts unknown'),
                   dict(approach='economy',benefit='Build income',cost='Gold',uncertainty='Later fronts unknown')],
               reconsider_when=[dict(goal_id='capture',kind='deadline_missed')],
               plan=None if request.get('campaign') else plan,
               usage=dict(known=True,input_tokens=0,output_tokens=0)),sys.stdout)
