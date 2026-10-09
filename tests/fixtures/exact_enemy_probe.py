"""Bounded observation probe, without a live model or gameplay orders."""
import json
import sys
request = json.load(sys.stdin)
print(json.dumps({'protocol': 2, 'request_id': request['request_id'],
                  'identity': request['identity'], 'failure': {'code': 'observation_probe'}}))
