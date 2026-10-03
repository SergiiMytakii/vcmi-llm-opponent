"""Deterministic policy for the first external-AI integration check."""
import json
import sys


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if type(request.get("protocol")) is not int or request["protocol"] != 1:
        raise ValueError("unsupported protocol")
    actions = request["actions"]
    action = next((item for item in actions if item["kind"] == "build"), actions[0])
    json.dump({
        "protocol": 1,
        "request_id": request["request_id"],
        "action_id": action["id"],
    }, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
