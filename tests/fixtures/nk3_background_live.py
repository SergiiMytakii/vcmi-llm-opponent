"""Bounded native-caller fixture: seeded opening, slow opponent, real own decisions.

The first own turn uses the existing public reply fixture. Every prepared own
reply and later own-turn foreground choice uses the actual configured model.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
request=json.load(sys.stdin)
seed=request['identity']['player']==1 or request.get('mode')!='prepare_next_turn' and request['identity']['day']==1
if request['identity']['player']==1:time.sleep(35)
script=ROOT/('tests/fixtures/nk3_strategy_probe.py' if seed else 'controller/main.py')
child=subprocess.run([sys.executable,str(script)],input=json.dumps(request).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
if seed and request['identity']['player']==0 and request.get('campaign') and child.returncode==0:
    reply=json.loads(child.stdout)
    reply.update(decision='retain',plan=None,assignments=request['observation']['strategy_assignments'])
    child.stdout=(json.dumps(reply)+'\n').encode()
sys.stdout.buffer.write(child.stdout);sys.stderr.buffer.write(child.stderr);sys.exit(child.returncode)
