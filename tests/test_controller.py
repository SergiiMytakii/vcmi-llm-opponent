import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile


ROOT = Path(__file__).resolve().parents[1]


class ControllerTest(unittest.TestCase):
    def test_direct_launch_records_each_request_and_reply_by_default(self):
        request={"protocol":1,"request_id":"recorded","observation":{},
                 "actions":[{"id":"finish","kind":"end_turn"}]}
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,"VCMI_PROFILE_DIR":folder,"VCMI_CODEX_EXECUTABLE":"/missing/codex"}
            env.pop('VCMI_PLAYTEST_DECISION_DIR',None)
            for _ in range(2):
                result=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],
                    input=json.dumps(request),text=True,capture_output=True,env=env,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
            records=list((Path(folder)/'logs/decisions').iterdir())
            self.assertEqual(len(records),2)
            for record in records:
                self.assertEqual(json.loads((record/'request.json').read_text()),request)
                self.assertEqual(json.loads((record/'reply.json').read_text())['action_id'],'finish')
                self.assertEqual(json.loads((record/'explanation.json').read_text())['provider'],'fallback')

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
