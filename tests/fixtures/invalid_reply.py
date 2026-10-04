"""Exercise native fallback without spending model calls or choosing from hidden state."""
import json
import sys
import time

json.load(sys.stdin)
time.sleep(0.1)
print('{}')
