"""Select an offered attack for the native battle-continuation regression."""
import json
import sys
import time

request = json.load(sys.stdin)
if len(sys.argv) > 1:
    time.sleep(float(sys.argv[1]))
action = next((item for item in request["actions"] if item["kind"] == "attack"),
              request["actions"][0])
print(json.dumps({"protocol": 1, "request_id": request["request_id"],
                  "action_id": action["id"]}))
