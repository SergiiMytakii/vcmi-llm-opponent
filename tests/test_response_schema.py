"""Model-facing response constraints through the subscription subprocess seam."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codex_fixture import codex_fixture
from fixtures.strategic_intent import with_intent
from test_nullkiller3_controller import strategic_request
from controller.native_strategy import reply_schema

ROOT = Path(__file__).resolve().parents[1]

MODEL = '''
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
args = sys.argv
pathlib.Path(os.environ['SCHEMA_CAPTURE']).write_bytes(
    pathlib.Path(args[args.index('--output-schema')+1]).read_bytes())
json.load(sys.stdin)
pathlib.Path(args[args.index('-o')+1]).write_bytes(pathlib.Path(os.environ['MODEL_REPLY']).read_bytes())
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
'''


def expand_schema(schema):
    """Read standard local JSON Schema references independently of the encoder."""
    def expand(value):
        if isinstance(value, dict):
            if '$ref' in value:
                assert set(value) == {'$ref'}
                target = schema
                for key in value['$ref'].split('/')[1:]:
                    target = target[key.replace('~1', '/').replace('~0', '~')]
                return expand(target)
            return {key:expand(item) for key,item in value.items() if key != '$defs'}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value
    return expand(schema)


class ResponseSchemaTest(unittest.TestCase):
    def request_and_reply(self):
        request = strategic_request()
        request['observation']['visible_objects'] = [
            dict(ref='object:'+str(i), kind='artifact', visible=True) for i in range(2, 322)]
        reply = dict(protocol=2, request_id=request['request_id'], identity=request['identity'],
            decision='revise', reason='Build the funded guild', evidence_refs=['town:object:1'],
            victory_method='Prepare for conquest', assignments=[],
            alternatives=[dict(approach='economy', benefit='Income', cost='Gold', uncertainty='Enemy intent'),
                          dict(approach='offense', benefit='Advance', cost='Army', uncertainty='Enemy strength')],
            reconsider_when=[dict(goal_id='guild', kind='deadline_missed')],
            plan=dict(version=3, revision=1, approach='economy', horizon_days=3,
                goals=[dict(id='guild', kind='develop_town', actor_ref=None, target_ref='object:1',
                    deadline_day=3, priority=80, building_id=0, min_army_value=0, depends_on=[],
                    required_capabilities=['build'], complete_when=dict(kind='building_present', value=0), risk=None)],
                reserves=[], policy=dict(max_loss_ratio=.2, allow_route_repair=True,
                    allow_helper_replacement=False, critical_towns=['object:1'])))
        return request, with_intent(request, reply)

    def call(self, request, reply):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'reply.json').write_text(json.dumps(reply))
            decision = folder/'decision'; decision.mkdir()
            result = subprocess.run([sys.executable, str(ROOT/'controller/main.py')],
                input=json.dumps(request), text=True, capture_output=True, timeout=10,
                env={**os.environ, **codex_fixture(folder, MODEL),
                     'SCHEMA_CAPTURE':str(folder/'schema.json'), 'MODEL_REPLY':str(folder/'reply.json'),
                     'VCMI_EXPERIENCE_MODE':'off', 'VCMI_STRATEGY_GUIDE_MODE':'off',
                     'VCMI_GAME_RULES_MODE':'off', 'VCMI_PLAYTEST_DECISION_DIR':str(decision)})
            sent = (folder/'schema.json').read_bytes()
            diagnostics = json.loads(result.stderr)
            return result, json.loads(sent), len(sent), diagnostics

    def assert_same_constraints(self, original, expanded):
        if isinstance(original, dict):
            self.assertIsInstance(expanded, dict)
            self.assertFalse(set(expanded)-set(original))
            for key in set(original)-set(expanded):
                self.assertIn(key, ('minLength', 'maxLength'))
                self.assertEqual(original['type'], 'string')
                for value in original['enum']:
                    if key == 'minLength':self.assertGreaterEqual(len(value), original[key])
                    else:self.assertLessEqual(len(value), original[key])
            for key,value in expanded.items():self.assert_same_constraints(original[key], value)
        elif isinstance(original, list):
            self.assertEqual(len(original), len(expanded))
            for left,right in zip(original, expanded):self.assert_same_constraints(left, right)
        else:self.assertEqual(original, expanded)

    def test_large_strategic_schema_is_smaller_with_the_same_allowed_decisions(self):
        request, reply = self.request_and_reply()
        original = reply_schema(request)
        result, sent, size, info = self.call(request, reply)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['plan'], reply['plan'])
        original_size = len(json.dumps(original, ensure_ascii=False, separators=(',', ':')).encode())
        self.assertLess(size, original_size*.75)
        self.assert_same_constraints(original, expand_schema(sent))
        self.assertEqual(info['input_encoding']['reply_schema_bytes'], size)
        self.assertEqual(info['input_encoding']['original_reply_schema_bytes'], original_size)

    def test_invalid_references_and_goal_target_kinds_still_produce_no_command(self):
        request, legal = self.request_and_reply()
        for field,value in [('goal', 'object:unknown'), ('goal', 'object:2'),
                            ('evidence', 'target:unknown'), ('hero', 'object:2'),
                            ('milestone', 'object:unknown')]:
            with self.subTest(field=field, value=value):
                reply = copy.deepcopy(legal)
                if field == 'goal':reply['plan']['goals'][0]['target_ref'] = value
                elif field == 'evidence':reply['evidence_refs'] = [value]
                elif field == 'hero':reply['assignments'] = [dict(hero_ref=value, role='main')]
                else:reply['strategy_update']['selected']['milestones'][0]['complete_when']['target_ref'] = value
                result, sent, _, info = self.call(request, reply)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(info['failure_kind'], 'invalid_reply')
                self.assert_same_constraints(reply_schema(request), expand_schema(sent))

    def test_nonredundant_enum_length_constraints_survive_transport(self):
        # Evidence supplied by the request can be longer than an assumption allows.
        # Such a list must not be merged with the unrestricted outer evidence list.
        request, reply = self.request_and_reply()
        request['evidence_refs'] = ['', 'target:'+'x'*50]
        result, sent, _, info = self.call(request, reply)
        self.assertEqual(result.returncode, 0, result.stderr)
        expanded = expand_schema(sent)
        self.assert_same_constraints(reply_schema(request), expanded)
        assumption_refs = expanded['properties']['strategy_update']['properties']['selected']['anyOf'][1][
            'properties']['assumptions']['items']['properties']['evidence_refs']['items']
        self.assertEqual(assumption_refs['maxLength'], 40)
        self.assertEqual(assumption_refs['minLength'], 1)

    def test_unicode_enum_bounds_count_characters(self):
        request, reply = self.request_and_reply()
        reference = 'target:'+'ї'*30
        request['evidence_refs'] = [reference]
        reply['strategy_update']['selected']['assumptions'] = [
            dict(text='Observed reference', evidence_refs=[reference], uncertainty='Unknown')]
        result, sent, _, _ = self.call(request, reply)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_same_constraints(reply_schema(request), expand_schema(sent))


if __name__ == '__main__':unittest.main()
