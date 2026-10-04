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
    def run_controller(self, behavior='valid'):
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
assert 'model_reasoning_effort="medium"' in args
assert schema['properties']['action_id']['enum'] == ['end', 'build-0']
if mode == 'timeout': time.sleep(45)
if mode == 'late': time.sleep(25)
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
            result = subprocess.run([sys.executable, str(ROOT / 'controller/main.py')],
                                    input=json.dumps(request), text=True, capture_output=True, timeout=40,
                                    env={**os.environ, **fixture_env,
                                         'CODEX_STUB_MODE': behavior, 'OPENAI_API_KEY': 'test-key',
                                         'CODEX_API_KEY': 'test-key'})
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout), json.loads(result.stderr)

    def test_uses_valid_codex_choice_with_subscription_profile(self):
        reply, info = self.run_controller()
        self.assertEqual(reply['action_id'], 'build-0')
        self.assertEqual(info['provider'], 'codex')
        self.assertEqual(info['usage']['input_tokens'], 12)

    def test_failed_or_invalid_choices_never_spend_resources(self):
        for failure in ['stale', 'unknown', 'boolean', 'extra', 'tool', 'incomplete', 'version', 'exit', 'overflow']:
            with self.subTest(failure=failure):
                reply, info = self.run_controller(failure)
                self.assertEqual(reply['action_id'], 'end')
                self.assertEqual(info['provider'], 'fallback')
                self.assertTrue(info['reason'])

    def test_slow_model_is_cancelled_within_native_deadline(self):
        reply, info = self.run_controller('timeout')
        self.assertEqual(reply['action_id'], 'end')
        self.assertIn('deadline', info['reason'])
        self.assertGreaterEqual(info['duration_seconds'], 34)
        self.assertLess(info['duration_seconds'], 37)

    def test_model_reply_after_the_old_deadline_is_used(self):
        reply, info = self.run_controller('late')
        self.assertEqual(reply['action_id'], 'build-0')
        self.assertEqual(info['provider'], 'codex')
        self.assertGreaterEqual(info['duration_seconds'], 25)
        self.assertLess(info['duration_seconds'], 35)


if __name__ == '__main__':
    unittest.main()
