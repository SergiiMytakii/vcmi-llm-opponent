"""Build once, then hold a decision open so a real game save can capture it."""
import json
import sys
import time

request = json.load(sys.stdin)
if request['request_id'] == '0:1:0':
    action = next(a for a in request['actions'] if a['kind'] == 'build')
    strategy = {
        'executor_ref': None, 'ready_when': {'kind': 'always', 'value': None},
        'complete_when': {'kind': 'confirmed_action', 'value': 'build'},
        'goal': 'Save/load integration probe', 'target_ref': action['target_ref'],
        'rationale': 'Remember the completed purchase across a saved game.',
        'reserves': 'Keep remaining resources.', 'progress': 'First purchase selected.',
        'change_reason': 'Initial plan.', 'steps': ['Build once', 'Resume the saved turn'],
        'reconsider_if': ['The town changes owner'],
    }
else:
    time.sleep(12)
    action = next(a for a in request['actions'] if a['kind'] == 'end_turn')
    strategy = None
print(json.dumps({'protocol': 1, 'request_id': request['request_id'],
                  'action_id': action['id'], 'strategy': strategy}))
