"""Inspect the actual model stdin across the controller subprocess boundary."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codex_fixture import codex_fixture

ROOT = Path(__file__).resolve().parents[1]

MODEL = '''
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
args = sys.argv
raw = sys.stdin.read()
pathlib.Path(os.environ['PROMPT_CAPTURE']).write_text(raw, encoding='utf-8')
schema = json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
reply = {'protocol':1, 'request_id':schema['properties']['request_id']['enum'][0], 'action_id':'build'}
if 'strategy' in schema['required']: reply['strategy'] = None
if 'follow_up_action_ids' in schema['required']: reply['follow_up_action_ids'] = []
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1}}))
'''


def restore_request(encoded):
    """Independent reader of the model-facing shared JSON format."""
    if set(encoded) != {'reference_key', 'shared', 'request'}:
        return encoded
    marker, definitions = encoded['reference_key'], encoded['shared']

    def expand(value):
        if isinstance(value, dict):
            if list(value) == [marker]:
                return expand(definitions[value[marker]])
            return {key:expand(item) for key,item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(encoded['request'])


class PromptContextTest(unittest.TestCase):
    def request(self):
        return {'protocol':1, 'request_id':'0:1:0',
                'observation':{'day':1, 'resources':[0,0,0,0,0,0,5000]},
                'actions':[{'id':'end','kind':'end_turn'},
                           {'id':'build','kind':'build','cost':[0,0,0,0,0,0,1000],
                            'effects':{'description':'Гильдия магов'}}]}

    def call(self, request):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            capture = folder/'prompt.json'
            decision = folder/'decision'
            decision.mkdir()
            result = subprocess.run([sys.executable, str(ROOT/'controller/main.py')],
                input=json.dumps(request), text=True, capture_output=True, timeout=10,
                env={**os.environ, **codex_fixture(folder, MODEL, expand_context=False),
                     'VCMI_EXPERIENCE_MODE':'off', 'PROMPT_CAPTURE':str(capture),
                     'VCMI_PLAYTEST_DECISION_DIR':str(decision)})
            self.assertEqual(result.returncode, 0, result.stderr)
            reply, info = json.loads(result.stdout), json.loads(result.stderr)
            self.assertEqual(info['provider'], 'codex', info)
            self.assertEqual(reply['action_id'], 'build')
            raw = capture.read_text(encoding='utf-8')
            self.assertEqual((decision/'codex-request.json').read_text(encoding='utf-8'), raw)
            schema = json.loads((decision/'codex-schema.json').read_text())
            self.assertEqual(schema['properties']['action_id']['enum'], ['end','build'])
            self.assertEqual(info['input_encoding']['sent_bytes'], len(raw.encode('utf-8')))
            return raw, info

    def test_model_receives_compact_utf8_without_changing_game_facts(self):
        request = self.request()
        raw, _ = self.call(request)
        self.assertIn('Гильдия магов', raw)
        self.assertNotIn('\\u', raw)
        self.assertNotIn(': ', raw)
        self.assertNotIn(', ', raw)
        self.assertEqual(json.loads(raw), request)

    def test_repeated_facts_are_shared_without_losing_uncertainty_or_time(self):
        request = self.request()
        army = {'detailed':False, 'stacks':[{'creature':'core:goblin', 'quantity_category':4}],
                'strength':{'basis':'vcmi_creature_ai_value_without_hero_or_siege',
                            'estimate':2100, 'minimum':1200, 'maximum':2940,
                            'uncertainty':'quantity_categories'}, 'note':'Наблюдаемая армия'}
        sightings = [{'id':n, 'ref':'object:' + str(n), 'army':copy.deepcopy(army),
                      'stale':False, 'day':2} for n in range(12)]
        request['observation']['visible_objects'] = sightings
        request['memory'] = {'plan':None, 'known_objects':copy.deepcopy(sightings), 'recent_results':[]}
        request['memory']['known_objects'][0].update(stale=True, day=1)
        request['observation']['unknown'] = None
        request['observation']['empty'] = []
        original = copy.deepcopy(request)
        raw, _ = self.call(request)
        encoded = json.loads(raw)
        self.assertIn('shared', encoded)
        self.assertEqual(restore_request(encoded), original)
        self.assertEqual(request, original)
        plain = json.dumps(original, ensure_ascii=False, separators=(',', ':'))
        self.assertLess(len(raw.encode('utf-8')), len(plain.encode('utf-8')) * .7)

    def test_game_data_reference_keys_and_distinct_scalar_types_remain_literal(self):
        request = self.request()
        record = {'note':'Сведения о неизвестном противнике, а не подтверждение победы.' * 4,
                  'quantity':None, 'empty':[], 'flags':[False, 0, True, 1, 1.0]}
        request['observation']['records'] = [copy.deepcopy(record) for _ in range(10)]
        request['observation']['literal'] = {'$ref':0, '$ref_':{'$ref':1}}
        raw, _ = self.call(request)
        encoded = json.loads(raw)
        self.assertNotIn(encoded['reference_key'], {'$ref', '$ref_'})
        restored = restore_request(encoded)
        self.assertEqual(restored, request)
        self.assertEqual([type(x) for x in restored['observation']['records'][0]['flags']],
                         [bool,int,bool,int,float])


if __name__ == '__main__':
    unittest.main()
