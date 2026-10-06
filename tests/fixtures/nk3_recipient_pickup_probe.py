"""Replay a recorded own plan without abandoning an in-progress courier."""
import json
import sys
from pathlib import Path
r=json.load(sys.stdin);a=json.loads(Path(sys.argv[1]).read_text())
a.update(request_id=r['request_id'],identity=r['identity'],usage=dict(input_tokens=0,output_tokens=0,known=True))
if r['observation']['day']<83 or r['identity']['revision']>=61:
 a.update(decision='retain',plan=None,reconsider_when=[dict(goal_id=g['id'],kind='deadline_missed') for g in r['campaign']['goals']])
else:a['plan']['revision']=r['identity']['revision']+1
print(json.dumps(a))
