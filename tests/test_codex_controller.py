import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture


ROOT = Path(__file__).resolve().parents[1]


class CodexControllerTest(unittest.TestCase):
    def run_controller(self, behavior='valid', expected_exit=0):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture_env = codex_fixture(root, '''
import json, os, pathlib, sys, time
mode = os.environ['CODEX_STUB_MODE']
if sys.argv[1:] == ['--version']:
    print('codex-cli ' + ('0.161.0' if mode == 'version' else '0.160.0')); sys.exit(0)
args = sys.argv
schema = json.loads(pathlib.Path(args[args.index('--output-schema') + 1]).read_text())
request = json.loads(sys.stdin.read())
assert 'OPENAI_API_KEY' not in os.environ and 'CODEX_API_KEY' not in os.environ
assert '--ignore-user-config' in args and '--ignore-rules' in args
assert args[args.index('-m') + 1] == 'gpt-6.1-sol'
assert 'forced_login_method="chatgpt"' in args
assert 'model_reasoning_effort="low"' in args
assert schema['properties']['action_id']['enum'] == ['end', 'build-0']
if mode == 'timeout': time.sleep(90)
if mode == 'late': time.sleep(38)
if mode == 'exit': sys.exit(4)
if mode == 'overflow': print('x' * (2 * 1024 * 1024)); sys.exit(0)
answer = {'protocol': 1, 'request_id': request['request_id'], 'action_id': 'build-0'}
if mode == 'stale': answer['request_id'] = 'old'
if mode == 'unknown': answer['action_id'] = 'unoffered'
if mode == 'boolean': answer['protocol'] = True
if mode == 'extra': answer['command'] = 'buy'
pathlib.Path(args[args.index('-o') + 1]).write_text(json.dumps(answer))
if mode == 'tool': print(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution'}}))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}}))
if mode != 'incomplete': print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 4}}))
''')
            request = {'protocol': 1, 'request_id': '0:7', 'observation': {'day': 7},
                       'actions': [{'id': 'end', 'kind': 'end_turn'}, {'id': 'build-0', 'kind': 'build'}]}
            entrypoint = ROOT / 'controller/main.py'
            if behavior == 'boundary':
                decision = root / 'decision'
                decision.mkdir()
                fixture_env['VCMI_PLAYTEST_DECISION_DIR'] = str(decision)
                entrypoint = root / 'clocked-controller.py'
                entrypoint.write_text(f'''import sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, {str(ROOT / 'controller')!r})
import main
with patch.object(time, 'monotonic', side_effect=lambda: 60.001 if Path({str(decision / 'codex-events.jsonl')!r}).exists() else 0):
    main.main()
''')
            result = subprocess.run([sys.executable, str(entrypoint)],
                                    input=json.dumps(request), text=True, capture_output=True, timeout=65,
                                    env={**os.environ, **fixture_env,
                                         'CODEX_STUB_MODE': behavior, 'OPENAI_API_KEY': 'test-key',
                                         'CODEX_API_KEY': 'test-key'})
            self.assertEqual(result.returncode, expected_exit, result.stderr)
            if expected_exit:
                self.assertEqual(result.stdout, '', 'an unanswered request must not become a game action')
            return json.loads(result.stdout) if result.stdout else None, json.loads(result.stderr)

    def test_uses_valid_codex_choice_with_subscription_profile(self):
        reply, info = self.run_controller()
        self.assertEqual(reply['action_id'], 'build-0')
        self.assertEqual(info['provider'], 'codex')
        self.assertEqual(info['model'], 'gpt-6.1-sol')
        self.assertEqual(info['reasoning_effort'], 'low')
        self.assertEqual(info['usage']['input_tokens'], 12)

    def test_failed_or_invalid_choices_never_spend_resources(self):
        for failure in ['stale', 'unknown', 'boolean', 'extra', 'tool', 'incomplete', 'version', 'exit', 'overflow']:
            with self.subTest(failure=failure):
                reply, info = self.run_controller(failure)
                self.assertEqual(reply['action_id'], 'end')
                self.assertEqual(info['provider'], 'fallback')
                self.assertTrue(info['reason'])

    def test_slow_model_is_cancelled_within_native_deadline(self):
        reply, info = self.run_controller('timeout', expected_exit=75)
        self.assertIsNone(reply)
        self.assertIsNone(info['action_id'])
        self.assertTrue(info['retryable'])
        self.assertIn('deadline', info['reason'])
        self.assertGreaterEqual(info['duration_seconds'], 60)
        self.assertLess(info['duration_seconds'], 65)

    def test_model_reply_after_the_old_deadline_is_used(self):
        reply, info = self.run_controller('late')
        self.assertEqual(reply['action_id'], 'build-0')
        self.assertEqual(info['provider'], 'codex')
        self.assertGreaterEqual(info['duration_seconds'], 38)
        self.assertLess(info['duration_seconds'], 60)

    def test_completed_process_observed_after_deadline_does_not_end_the_turn(self):
        reply, info = self.run_controller('boundary', expected_exit=75)
        self.assertIsNone(reply)
        self.assertIsNone(info['action_id'])
        self.assertTrue(info['retryable'])
        self.assertIn('deadline', info['reason'])


if __name__ == '__main__':
    unittest.main()
