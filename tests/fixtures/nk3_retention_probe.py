"""Retain accepted delivery intents through the public strategy contract."""
from strategic_intent import with_intent
import json,sys
r=json.load(sys.stdin);plan=r['campaign'];goals=plan['goals'];actors={}
for g in goals:
 if g['actor_ref']:actors.setdefault(g['actor_ref'],[]).append(g['id'])
print(json.dumps(with_intent(r,dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain',
 reason='Continue the accepted supported schedule',evidence_refs=r['evidence_refs'][:1],
 victory_method='Execute the accepted campaign',assignments=[dict(hero_ref=h,role='reinforcement') for h,ids in actors.items()],
 alternatives=[dict(approach='offense',benefit='Meet the force target',cost='Recruitment',uncertainty='Future movement'),
               dict(approach='defense',benefit='Keep existing force',cost='Wait',uncertainty='Opponent intention')],
 reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in goals],plan=None,
 usage=dict(input_tokens=0,output_tokens=0,known=True)))))
