"""Native timeout recovery probe; uses only current offered actions."""
import json
import os
from pathlib import Path
import sys
import time

request = json.load(sys.stdin)
run = Path(os.environ['VCMI_PLAYTEST_RUN'])
counter = run / 'evidence/timeout-probe.json'
state = json.loads(counter.read_text()) if counter.exists() else {'calls': 0}
state['calls'] += 1
counter.write_text(json.dumps(state))
if sys.argv[1] == 'exhaust' or state['calls'] == 1:
    sys.exit(75)
if state['calls'] == 3:
    # The supervising test saves while this unanswered request is in flight.
    time.sleep(8)
    sys.exit(75)
choices = [a for a in request['actions'] if a['kind'] == 'build']
if not choices:
    choices = [a for a in request['actions'] if a['kind'] == 'explore'
               and not a['route_encounters'] and not a['stop_threats']]
if not choices:
    raise RuntimeError('fixture needs a useful offered action after the timeout')
print(json.dumps({'protocol': 1, 'request_id': request['request_id'],
                  'action_id': choices[0]['id']}))
