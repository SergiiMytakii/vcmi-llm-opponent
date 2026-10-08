import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile


ROOT = Path(__file__).resolve().parents[1]


class ControllerTest(unittest.TestCase):
    def test_resource_rejection_retains_usage_and_reaches_the_next_model_request(self):
        from codex_fixture import codex_fixture
        from test_nullkiller3_controller import strategic_request
        from test_strategy_guide import MODEL, final_reply
        request = strategic_request()
        rejected = final_reply(request)
        second_goal = dict(rejected['plan']['goals'][0], id='second-guild')
        rejected['plan']['goals'].append(second_goal)
        rejected['plan']['reserves'] = [dict(goal_id='guild', force_value=0,
                                            resources=[6, 0, 0, 0, 0, 0, 0]),
                                       dict(goal_id='second-guild', force_value=0,
                                            resources=[15, 0, 0, 0, 0, 0, 0])]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {**os.environ, **codex_fixture(root, MODEL), 'CAPTURE': folder,
                   'FINAL_REPLY': json.dumps(rejected), 'VCMI_EXPERIENCE_MODE': 'off',
                   'VCMI_STRATEGY_GUIDE_MODE': 'off', 'VCMI_GAME_RULES_MODE': 'off'}
            for number in (1, 2):
                directory = root / f'decision-{number}'
                directory.mkdir()
                result = subprocess.run([sys.executable, str(ROOT / 'controller/main.py')],
                    input=json.dumps(request), text=True, capture_output=True, timeout=10,
                    env={**env, 'VCMI_PLAYTEST_DECISION_DIR': str(directory)})
                self.assertEqual(result.returncode, 0, result.stderr)
                reply = json.loads(result.stdout)
                self.assertEqual(reply, dict(protocol=2, request_id=request['request_id'],
                    identity=request['identity'], failure=dict(
                        code='resource_commitments_exceed_available_funds',
                        required=[21, 0, 0, 0, 0, 0, 0], available=[10, 10, 10, 10, 10, 10, 10000]),
                    usage=dict(known=True, input_tokens=120, output_tokens=40)))
                metadata = json.loads(result.stderr)
                self.assertEqual(metadata['failure_kind'], 'invalid_reply')
                self.assertEqual(metadata['reason'], 'resource_commitments_exceed_available_funds')
                self.assertEqual(json.loads((directory / 'reply.json').read_text()), reply)
                request['memory']['recent_results'] = [dict(player=0, day=1, outcome='refused',
                    reason='resource_commitments_exceed_available_funds')]
            self.assertEqual(len(list(root.glob('call-*.json'))), 2, 'one model call per native request')
            second = json.loads((root / 'call-2.json').read_text())['request']
            self.assertEqual(second['memory']['recent_results'], request['memory']['recent_results'])

    def test_resource_rejection_reports_unknown_usage_without_fabricating_tokens(self):
        from codex_fixture import codex_fixture
        from test_nullkiller3_controller import strategic_request
        from test_strategy_guide import MODEL, final_reply
        request = strategic_request()
        rejected = final_reply(request)
        rejected['plan']['reserves'] = [dict(goal_id='guild', force_value=0,
                                            resources=[21, 0, 0, 0, 0, 0, 0])]
        with tempfile.TemporaryDirectory() as folder:
            model = MODEL.replace("'input_tokens':120,'output_tokens':40", "'input_tokens':120")
            env = {**os.environ, **codex_fixture(Path(folder), model), 'CAPTURE': folder,
                   'FINAL_REPLY': json.dumps(rejected), 'VCMI_PLAYTEST_DECISION_DIR': folder,
                   'VCMI_EXPERIENCE_MODE': 'off', 'VCMI_STRATEGY_GUIDE_MODE': 'off', 'VCMI_GAME_RULES_MODE': 'off'}
            result = subprocess.run([sys.executable, str(ROOT / 'controller/main.py')],
                input=json.dumps(request), text=True, capture_output=True, timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['usage'], dict(known=False, input_tokens=0, output_tokens=0))


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
