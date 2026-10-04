import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from codex_fixture import codex_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'controller'))
from codex import validate_reply

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playtesting.controller import validate_reply as validate_recorded_reply


PLAN = {
    'goal': 'Reinforce the hero, take the ore mine, then attack the town',
    'target_ref': 'object:42', 'rationale': 'Ore is needed for the next dwelling',
    'steps': ['Recruit archers', 'Visit the mine'], 'reserves': 'Keep 5 wood for the dwelling',
    'reconsider_if': ['Enemy threatens our town', 'Hero loses the ranged stack'],
    'executor_ref': None, 'ready_when': {'kind': 'always', 'value': None},
    'complete_when': {'kind': 'target_owned', 'value': None},
    'progress': 'Preparing to recruit', 'change_reason': 'Initial plan from the visible mine',
}


class StrategyContractTest(unittest.TestCase):
    def request(self):
        return {'protocol': 1, 'request_id': 'red:5:1',
                'observation': {'day': 5},
                'memory': {'schema': 2, 'plan': None, 'known_objects': [
                    {'ref': 'object:42', 'last_seen_day': 4, 'stale': True}]},
                'actions': [{'id': 'end', 'kind': 'end_turn'}]}

    def reply(self, plan):
        return {'protocol': 1, 'request_id': 'red:5:1', 'action_id': 'end', 'strategy': plan}

    def test_plan_can_reference_a_previous_sighting_and_survive_next_call(self):
        request = self.request()
        self.assertEqual(validate_reply(request, self.reply(copy.deepcopy(PLAN)))['strategy'], PLAN)
        request['memory']['plan'] = copy.deepcopy(PLAN)
        self.assertIsNone(validate_reply(request, self.reply(None))['strategy'])

    def test_invented_target_or_fact_update_is_rejected(self):
        for update in ({'target_ref': 'object:999'}, {'known_objects': []},
                       {'change_reason': ''}, {'steps': ['x'] * 5}):
            plan = {**PLAN, **update}
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_reply(self.request(), self.reply(plan))

    def test_plan_names_owned_executor_and_checkable_conditions(self):
        request = self.request()
        request['observation']['heroes'] = [{'id': 7}]
        plan = {**PLAN, 'executor_ref': 'object:7',
                'ready_when': {'kind': 'day_at_least', 'value': 7},
                'complete_when': {'kind': 'target_owned', 'value': None}}
        self.assertEqual(validate_reply(request, self.reply(plan))['strategy'], plan)
        for update in ({'executor_ref': 'object:99'}, {'ready_when': {'kind': 'day_at_least', 'value': True}},
                       {'complete_when': {'kind': 'target_owned', 'value': 1}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_reply(request, self.reply({**plan, **update}))

    def test_conditions_reject_missing_executor_target_or_extra_fact_fields(self):
        plan = {**PLAN, 'executor_ref': None, 'ready_when': {'kind': 'always', 'value': None},
                'complete_when': {'kind': 'target_owned', 'value': None}}
        for update in ({'ready_when': {'kind': 'army_strength_at_least', 'value': 100}},
                       {'target_ref': None}, {'complete_when': {'kind': 'always', 'value': None}},
                       {'complete_when': {'kind': 'unknown', 'value': None, 'observed': True}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_reply(self.request(), self.reply({**plan, **update}))

    def test_stale_reply_cannot_replace_plan(self):
        reply = self.reply(PLAN)
        reply['request_id'] = 'old-request'
        with self.assertRaises(ValueError):
            validate_reply(self.request(), reply)

    def test_plan_can_finish_after_confirmed_hero_hire_at_a_known_town(self):
        request = self.request()
        request['actions'].append({'id': 'hire-hero-0', 'kind': 'hire_hero',
                                   'town': 42, 'target_ref': 'object:42'})
        plan = {**PLAN, 'goal': 'Hire a scout',
                'complete_when': {'kind': 'confirmed_action', 'value': 'hire_hero'}}
        reply = {**self.reply(plan), 'action_id': 'hire-hero-0'}
        self.assertEqual(validate_reply(request, reply)['strategy'], plan)

    def test_threshold_conditions_require_bounded_integer_json_values(self):
        request = self.request()
        request['observation']['heroes'] = [{'id': 7}]
        for kind in ('day_at_least', 'army_strength_at_least'):
            for literal in ('7.0', '7e0', 'true', '-1', '2147483648'):
                plan = {**PLAN, 'executor_ref': 'object:7',
                        'ready_when': {'kind': kind, 'value': json.loads(literal)}}
                with self.subTest(kind=kind, literal=literal), self.assertRaises(ValueError):
                    validate_reply(request, self.reply(plan))
            for value in (0, 7, 2147483647):
                plan = {**PLAN, 'executor_ref': 'object:7',
                        'ready_when': {'kind': kind, 'value': value}}
                with self.subTest(kind=kind, value=value):
                    self.assertEqual(validate_reply(request, self.reply(plan))['strategy'], plan)

    def test_full_controller_passes_memory_and_returns_validated_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            request = self.request()
            request['memory']['plan'] = copy.deepcopy(PLAN)
            request['memory']['recent_results'] = [{'day': 4, 'outcome': 'unconfirmed'}]
            (folder / 'expected.json').write_text(json.dumps(request))
            fixture_env = codex_fixture(folder, '''
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
args = sys.argv
request = json.loads(sys.stdin.read())
expected = json.loads(pathlib.Path(os.environ['MEMORY_TEST_EXPECTED']).read_text())
assert request == expected
schema = json.loads(pathlib.Path(args[args.index('--output-schema') + 1]).read_text())
assert 'strategy' in schema['required']
assert schema['properties']['strategy']['anyOf'][1]['properties']['target_ref']['enum'] == [None, 'object:42']
instructions = pathlib.Path('instructions.txt').read_text()
assert 'PERSISTENT STRATEGY' in instructions
answer = {'protocol': 1, 'request_id': request['request_id'], 'action_id': 'end', 'strategy': request['memory']['plan']}
if os.environ['MEMORY_TEST_MODE'] == 'invalid': answer['strategy']['target_ref'] = 'object:999'
if os.environ['MEMORY_TEST_MODE'] == 'unicode': answer['strategy']['rationale'] = 'Сила 6520–14094; разведка'
pathlib.Path(args[args.index('-o') + 1]).write_text(json.dumps(answer))
print(json.dumps({'type': 'turn.completed', 'usage': {}}))
''')
            for mode in ('valid', 'invalid', 'unicode'):
                result = subprocess.run([sys.executable, str(ROOT / 'controller/main.py')],
                                        input=json.dumps(request), text=True, capture_output=True, timeout=20,
                                        env={**os.environ, **fixture_env,
                                             'MEMORY_TEST_EXPECTED': str(folder / 'expected.json'),
                                             'MEMORY_TEST_MODE': mode})
                self.assertEqual(result.returncode, 0, result.stderr)
                reply = validate_recorded_reply(request, result.stdout)
                metadata = json.loads(result.stderr)
                if mode in ('valid', 'unicode'):
                    self.assertEqual(metadata['provider'], 'codex', metadata)
                    expected = {**PLAN, 'rationale': 'Сила 6520–14094; разведка'} if mode == 'unicode' else PLAN
                    self.assertEqual(reply['strategy'], expected)
                    if mode == 'unicode':
                        self.assertIn('Сила 6520–14094; разведка', result.stdout)
                        self.assertNotIn('\\u', result.stdout)
                else:
                    self.assertEqual(metadata['provider'], 'fallback')
                    self.assertNotIn('strategy', reply)  # Cannot erase the saved plan.
                    self.assertEqual(reply['action_id'], 'end')


if __name__ == '__main__':
    unittest.main()
