"""Ordered multi-action choices through the real controller subprocess."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture

ROOT = Path(__file__).resolve().parents[1]


class TurnBatchControllerTest(unittest.TestCase):
    def run_choice(self, followups):
        with tempfile.TemporaryDirectory() as directory:
            env = codex_fixture(Path(directory), '''
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
request = json.load(sys.stdin)
reply = {'protocol':1, 'request_id':request['request_id'], 'action_id':'build-a',
         'follow_up_action_ids':json.loads(os.environ['BATCH_FOLLOWUPS'])}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{}}))
''')
            request = {'protocol':1, 'request_id':'0:1:0',
                       'observation':{'day':1, 'batch_action_limit':32},
                       'actions':[{'id':'build-a','kind':'build'},
                                  {'id':'build-b','kind':'build'},
                                  {'id':'move-a','kind':'visit'},
                                  {'id':'move-b','kind':'explore'},
                                  {'id':'end','kind':'end_turn'}]}
            result = subprocess.run([sys.executable, str(ROOT/'controller/main.py')],
                                    input=json.dumps(request), text=True, capture_output=True, timeout=10,
                                    env={**os.environ, **env, 'BATCH_FOLLOWUPS':json.dumps(followups)})
            self.assertEqual(result.returncode, 0, result.stderr)
            return request, json.loads(result.stdout), json.loads(result.stderr)

    def test_one_model_choice_covers_two_towns_and_two_heroes(self):
        request, reply, metadata = self.run_choice(['build-b','move-a','move-b'])
        self.assertEqual(metadata['provider'], 'codex', metadata)
        self.assertEqual(reply['action_id'], 'build-a')
        self.assertEqual(reply['follow_up_action_ids'], ['build-b','move-a','move-b'])
        sys.path.insert(0, str(ROOT))
        from playtesting.controller import validate_reply
        self.assertEqual(validate_reply(request, json.dumps(reply)), reply)

    def test_invalid_batch_never_executes_its_first_purchase(self):
        for choices in (['unoffered'], ['build-a'], ['move-a','move-a'],
                        ['end','move-a'], ['move-b'] * 32, 'move-a', [True]):
            with self.subTest(choices=choices):
                _, reply, metadata = self.run_choice(choices)
                self.assertEqual(metadata['provider'], 'fallback')
                self.assertEqual(reply['action_id'], 'end')
                self.assertNotIn('follow_up_action_ids', reply)

    def test_end_turn_can_finish_a_batch(self):
        _, reply, metadata = self.run_choice(['build-b','end'])
        self.assertEqual(metadata['provider'], 'codex')
        self.assertEqual(reply['follow_up_action_ids'], ['build-b','end'])


if __name__ == '__main__': unittest.main()
