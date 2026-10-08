"""Native-caller threat fixture. Own model sees only the game's own request.
Seed one supported offensive obligation; the opponent reinforces its own hero
while the real own background model prepares the next own turn.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from strategic_intent import with_intent
ROOT=Path(__file__).resolve().parents[2]
r=json.load(sys.stdin);own=r['observation'];player=r['identity']['player']
if player==0 and (own['day']>1 or r.get('mode')=='prepare_next_turn'):
    process=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(r).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    sys.stdout.buffer.write(process.stdout);sys.stderr.buffer.write(process.stderr);sys.exit(process.returncode)
if player==1:time.sleep(35)
hero=own['heroes'][0];town=own['towns'][0]
if player==0:
    enemy=next(o for o in own['objects'] if o.get('kind')=='town' and o.get('owner') in own['enemy_players'])
    kind,target,predicate,amount='capture_target',enemy['ref'],'target_owned',player
else:
    kind,target,predicate,amount='reinforce_hero',town['ref'],'army_at_least',20000
goal=dict(id='offense' if player==0 else 'new-visible-force',kind=kind,actor_ref=hero['ref'],target_ref=target,
    deadline_day=own['day']+5,priority=90,building_id=-1,min_army_value=hero['army_value'],depends_on=[],
    required_capabilities=['land'] if player==0 else ['land','transfer'],complete_when=dict(kind=predicate,value=amount),risk=None)
if player==0:
    goal['risk']=dict(max_loss_ratio=.8,reason='Controlled fixture permits the quoted initial offensive route; the later visible reinforcement requires fresh review')
plan=dict(version=3,revision=r['identity']['revision']+1,approach='offense',horizon_days=5,goals=[goal],reserves=[],
    policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town['ref']]))
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',reason='Controlled native offensive obligation' if player==0 else 'Controlled own reinforcement',
    evidence_refs=['hero:'+hero['ref']],victory_method='Capture the known enemy town',assignments=[dict(hero_ref=hero['ref'],role='main')],
    alternatives=[dict(approach='offense',benefit='Conquest',cost='Troops',uncertainty='Enemy future force'),dict(approach='defense',benefit='Protect home',cost='Delay',uncertainty='Enemy intentions')],
    reconsider_when=[dict(goal_id=goal['id'],kind='route_not_established')],plan=plan,usage=dict(known=True,input_tokens=0,output_tokens=0))
reply=with_intent(r,reply)
if player==0 and r.get('campaign'):
    reply.update(decision='retain',plan=None,assignments=own['strategy_assignments'])
    reply=with_intent(r,reply)
if player==0 and r.get('strategic_intent') is None:
    selected=reply['strategy_update']['selected']
    selected['milestones'][0]['complete_when']=dict(kind='target_owned',target_ref=target,actor_ref=None,value=player)
    selected['reconsider_when']=[dict(kind='base_threat',milestone_id='stage-1',reason='Review changed visible front')]
print(json.dumps(reply))
