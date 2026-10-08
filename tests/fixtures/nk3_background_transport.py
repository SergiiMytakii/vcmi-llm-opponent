"""Controlled native transport errors, with ordinary replies through the same contract."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from strategic_intent import with_intent
r=json.load(sys.stdin);background=r.get('mode')=='prepare_next_turn'
case=os.environ.get('NK3_BACKGROUND_CASE','ready')
if r['identity']['player']==1:time.sleep(2)
if background and r['identity']['player']==0:
    if case=='pending':time.sleep(30)
    if case=='crash':sys.exit(1)
    if case=='invalid':print('{broken');sys.exit(0)
    if case=='oversized':print('x'*50000);sys.exit(0)
world=r['observation'];town=world['towns'][0]
options=[b for b in town['building_options'] if b.get('supported') and b['id'] not in town['buildings']]
if not options:sys.exit(1)
option=next((b for b in options if b.get('availability')=='allowed'),options[0])
day=r.get('execution_day',world['day']);name='build-'+str(day)+'-'+str(option['id'])
goal=dict(id=name,kind='develop_town',actor_ref=None,target_ref=town['ref'],deadline_day=day+3,
          priority=80,building_id=option['id'],min_army_value=0,depends_on=[],required_capabilities=['build'],
          complete_when=dict(kind='building_present',value=option['id']),risk=None)
plan=dict(version=3,revision=r['identity']['revision']+1,approach='economy',horizon_days=5,goals=[goal],reserves=[],
          policy=r['campaign']['policy'] if r.get('campaign') else dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town['ref']]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',reason='Controlled next native building',
    evidence_refs=['town:'+town['ref']],victory_method='Native public-contract test',assignments=world.get('strategy_assignments') or [],
    alternatives=[dict(approach='economy',benefit='Building',cost='Treasury',uncertainty='Future enemy'),dict(approach='offense',benefit='Advance',cost='Force',uncertainty='Route')],
    reconsider_when=[dict(goal_id=name,kind='deadline_missed')],plan=plan,usage=dict(known=True,input_tokens=0,output_tokens=0))
if not background and r.get('campaign') and world['day']==1:
    reply['decision']='retain';reply['plan']=None
    reply['reconsider_when']=[dict(goal_id=r['campaign']['goals'][0]['id'],kind='deadline_missed')]
reply=with_intent(r,reply)
if background:
    reply.update(mode='prepare_next_turn',execution_day=day,intent_revision=r['intent_revision'])
    if not r['strategic_review']:reply['alternatives']=[]
print(json.dumps(reply))
