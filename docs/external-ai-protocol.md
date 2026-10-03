# ExternalAI protocol, first increment

This development protocol currently handles one construction decision per turn. It does not yet implement
the complete observation/action contract from the research documents.

The engine launches `VCMI_EXTERNAL_AI_EXECUTABLE` with one argument, `VCMI_EXTERNAL_AI_SCRIPT`.
Both must be absolute paths. There is no shell command interpolation. One child process serves one request.
The executable is currently Python and the script is `controller/main.py` (a deterministic build-first policy).

The engine writes one UTF-8 JSON object to stdin, then closes stdin. Maximum input size: 256 KiB.
The controller writes one JSON object to stdout and exits successfully. Maximum output size: 8 KiB.
Stderr is discarded by this initial adapter. Process execution is limited to 20 seconds including launch;
polling and cleanup can add up to approximately 220 ms. Game shutdown cancels the request.
On Windows, the child is created suspended, assigned to the owned Job Object, then resumed.
Windows execution still requires verification on the Windows developer machine.

Example request (cost order follows VCMI's resource indices):

```json
{
  "protocol": 1,
  "request_id": "0:1",
  "observation": {"player": 0, "day": 1},
  "actions": [
    {"id": "end", "kind": "end_turn"},
    {"id": "build-0", "kind": "build", "building": "mageGuild1", "cost": [5, 0, 5, 0, 0, 0, 2000, 0]}
  ]
}
```

The candidate list includes only currently buildable normal buildings in the player's own towns. Grail,
automatic and special constructions are excluded. The engine keeps
the town/building IDs locally. An action ID is valid only for its request; it must not be reused on a later turn.
The resource-array example is illustrative; actual costs and array length come from the engine.

Reply, with exactly these three fields:

```json
{"protocol": 1, "request_id": "0:1", "action_id": "build-0"}
```

The adapter rejects stale IDs, unknown actions, invalid JSON, excess fields, oversized replies, nonzero exits,
and timeouts. Failure ends the turn. A valid build is revalidated through VCMI's callback immediately before
dispatch. After the server response (or a five-second observation deadline), the adapter reads the town state
and logs whether the building is actually present. Acknowledgement alone is not considered build success.
It never retries a potentially applied construction request.

This milestone does not call a model or sandbox model tools. The separate Codex integration must establish
its restricted tools, file visibility, turn budget and fallback before being enabled for gameplay.
