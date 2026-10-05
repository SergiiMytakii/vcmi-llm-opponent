"""Keep one legal handoff intent and the named source army pledge."""
import copy,json,os,sys,time
from pathlib import Path
r=json.load(sys.stdin);world=r['observation'];hero=world['heroes'][0];town=world['towns'][0];helper=world['heroes'][1]
gate=os.environ.get('NK3_STAGNATION_SAVE_GATE')
if gate and any(s['question']=='stagnation:operations' for s in r['signals']):
 deadline=time.monotonic()+5
 while not Path(gate).exists() and time.monotonic()<deadline:time.sleep(.03)
plan=r.get('campaign')
if not plan:
 def goal(id,kind,actor,minimum,predicate):
  return dict(id=id,kind=kind,actor_ref=actor,target_ref=town['ref'],deadline_day=7,priority=90 if id=='deliver' else 40,
   building_id=-1,min_army_value=minimum,depends_on=[],required_capabilities=['land','transfer'] if kind=='reinforce_hero' else ['land'],complete_when=predicate)
 plan=dict(version=3,revision=r['identity']['revision']+1,approach='defense',horizon_days=6,
  goals=[goal('deliver','reinforce_hero',hero['ref'],0,dict(kind='army_at_least',value=6000)),
         goal('hold','defend_area',helper['ref'],8850,dict(kind='held_until',value=7))],
  reserves=[dict(goal_id='hold',resources=[0]*7,force_value=8850)],
  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
renumber=bool(r.get('campaign') and os.environ.get('NK3_STAGNATION_MODE')=='renumber'
              and any(s['question']=='stagnation:operations' for s in r['signals']))
release=bool(r.get('campaign') and os.environ.get('NK3_STAGNATION_MODE')=='release'
             and any(s['question']=='stagnation:operations' for s in r['signals']))
if renumber:
 plan=copy.deepcopy(plan);plan['revision']=r['identity']['revision']+1
 for goal in plan['goals']:goal['id']+='2'
 for reserve in plan['reserves']:reserve['goal_id']+='2'
if release:
 plan=copy.deepcopy(plan);plan['revision']=r['identity']['revision']+1
 next(g for g in plan['goals'] if g['kind']=='defend_area')['min_army_value']=8700
 plan['reserves'][0]['force_value']=8700
delivery=next(g for g in plan['goals'] if g['kind']=='reinforce_hero')['id']
holding=next(g for g in plan['goals'] if g['kind']=='defend_area')['id']
reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise' if renumber or release or not r.get('campaign') else 'retain',
 reason='Observe actual legal delivery progress without spending the source pledge',evidence_refs=['hero:'+hero['ref']],
 victory_method='Preserve the source defense and improve the main force',
 assignments=[dict(hero_ref=hero['ref'],role='main'),dict(hero_ref=helper['ref'],role='defender')],
 alternatives=[dict(approach='defense',benefit='Keep the source pledge',cost='Troops cannot move',uncertainty='Whole creature packing'),
               dict(approach='offense',benefit='Supply the main force',cost='Change the source pledge',uncertainty='Future threats')],
 reconsider_when=[dict(goal_id=delivery,kind='route_not_established')],plan=plan if renumber or release or not r.get('campaign') else None,
 usage=dict(input_tokens=0,output_tokens=0,known=True))
print(json.dumps(reply))
