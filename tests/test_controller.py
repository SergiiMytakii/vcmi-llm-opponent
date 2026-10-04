import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ControllerTest(unittest.TestCase):
    def test_utf8_protocol_is_independent_of_process_locale(self):
        request = {"protocol": 1, "request_id": "ход-1", "observation": {}, "actions": [
            {"id": "конец", "kind": "end_turn"}]}
        result = subprocess.run(
            [sys.executable, str(ROOT / "controller" / "main.py")],
            input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=5, env={**os.environ, "PYTHONIOENCODING": "ascii", "VCMI_CODEX_EXECUTABLE": "/missing/codex"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["action_id"], "конец")

    def test_rejects_unknown_protocol_without_an_action(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "controller" / "main.py")],
            input=json.dumps({"protocol": 99, "request_id": "x", "actions": [
                {"id": "finish", "kind": "end_turn"}]}),
            text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_CODEX_EXECUTABLE": "/missing/codex"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_unavailable_codex_ends_turn_without_spending(self):
        request = {
            "protocol": 1,
            "request_id": "turn-7",
            "observation": {"player": 0, "day": 3},
            "actions": [
                {"id": "finish", "kind": "end_turn"},
                {"id": "town-hall", "kind": "build", "cost": {"gold": 2500}},
            ],
        }
        result = subprocess.run(
            [sys.executable, str(ROOT / "controller" / "main.py")],
            input=json.dumps(request), text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_CODEX_EXECUTABLE": "/missing/codex"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "protocol": 1, "request_id": "turn-7", "action_id": "finish",
        })


if __name__ == "__main__":
    unittest.main()
