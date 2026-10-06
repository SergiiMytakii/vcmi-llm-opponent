"""Campaign intentions cross the same reply boundary as real game commands."""
import copy
import json
from pathlib import Path
import sys
import os
import subprocess
import tempfile
from codex_fixture import codex_fixture
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'controller'))
from codex import validate_reply


def campaign_request():
    return {'protocol': 1, 'request_id': '0:1:0',
            'observation': {'day': 1, 'player': 0, 'resources': [10, 0, 10, 0, 0, 0, 5000],
                            'resource_order': ['wood','mercury','ore','sulfur','crystal','gems','gold'],
                            'victory': {'kind': 'conquest', 'supported': True},
                            'heroes': [{'id': 1}, {'id': 2}], 'towns': [{'id': 3}]},
            'memory': {'schema': 2, 'campaign': None, 'plan': None,
                       'campaign_review': {'required': True, 'reasons': ['initial_campaign']},
                       'known_objects': [{'ref': 'object:4', 'kind': 'mine'}]},
            'actions': [{'id': 'end', 'kind': 'end_turn'},
                        {'id': 'move', 'kind': 'visit', 'hero': 1, 'target_ref': 'object:4'}]}


def campaign_update():
    return {'decision': 'revise', 'reason': 'The owned town and army can fund early expansion.',
            'evidence_refs': ['town:object:3', 'observation:resources'],
            'plan': {'victory_method': 'Expand income and defeat every hostile team.',
                     'approach': 'expansion', 'main_hero_ref': 'object:1', 'horizon_day': 5,
                     'advantages': [{'fact_ref': 'town:object:3', 'benefit': 'Fund recruitment',
                                     'constraint': 'Delivery requires a town visit.'},
                                    {'fact_ref': 'hero:object:1', 'benefit': 'Lead expansion',
                                     'constraint': 'Enemy strength remains unknown.'}],
                     'milestones': [{'target_ref': 'object:4', 'executor_ref': 'object:1',
                                     'due_day': 4, 'expected': 'Capture the observed mine.'}],
                     'assignments': [{'hero_ref': 'object:1', 'role': 'main', 'target_ref': 'object:4', 'task': 'Take mine'},
                                     {'hero_ref': 'object:2', 'role': 'scout', 'target_ref': None, 'task': 'Find a passage'}],
                     'reserves': [{'resource': 'gold', 'amount': 1000, 'purpose': 'Reinforcement', 'release_if': 'Threat or better capture'}],
                     'alternatives': [{'approach': 'economy', 'benefit': 'Increase daily income', 'cost': 'Delay army purchases',
                                       'risk': 'Early enemy pressure', 'abandon_if': 'A nearby enemy appears'},
                                      {'approach': 'expansion', 'benefit': 'Capture mine income', 'cost': 'Army and movement',
                                       'risk': 'Unknown encounters', 'abandon_if': 'Route becomes unsafe'}]}}


class CampaignContractTest(unittest.TestCase):
    def test_campaign_crosses_controller_and_recorder_without_becoming_facts(self):
        request = campaign_request()
        reply = {'protocol': 1, 'request_id': request['request_id'], 'action_id': 'move',
                 'strategy': None, 'campaign': campaign_update()}
        self.assertEqual(validate_reply(request, copy.deepcopy(reply)), reply)
        sys.path.insert(0, str(ROOT))
        from playtesting.controller import validate_reply as recorded
        self.assertEqual(recorded(request, json.dumps(reply)), reply)
        self.assertIsNone(request['memory']['campaign'])

    def reply(self, request, update):
        return {'protocol':1, 'request_id':request['request_id'], 'action_id':'move',
                'strategy':None, 'campaign':update}

    def test_conflicts_unknown_facts_and_double_reserves_reject_whole_choice(self):
        for case in ('hero', 'target', 'reserve', 'facts', 'unknown', 'milestone', 'horizon', 'main', 'alternative', 'unicode'):
            request, update = campaign_request(), campaign_update()
            plan = update['plan']
            if case == 'hero': plan['assignments'].append(copy.deepcopy(plan['assignments'][0]))
            if case == 'target': plan['assignments'][1]['target_ref'] = 'object:4'
            if case == 'reserve': plan['reserves'].append(copy.deepcopy(plan['reserves'][0]))
            if case == 'facts': update['known_objects'] = []
            if case == 'unknown': update['evidence_refs'] = ['hero:object:999']
            if case == 'milestone': plan['milestones'][0]['executor_ref'] = 'object:2'
            if case == 'horizon': plan['horizon_day'] = True
            if case == 'main': plan['assignments'][0]['role'] = 'scout'
            if case == 'alternative': plan['alternatives'][1]['approach'] = 'economy'
            if case == 'unicode': update['reason'] = 'Я' * 81
            with self.subTest(case=case), self.assertRaises(ValueError):
                validate_reply(request, self.reply(request, update))

    def test_milestones_allow_sequential_targets_at_their_deadlines(self):
        request, update = campaign_request(), campaign_update()
        update['plan']['milestones'].append({'target_ref':None, 'executor_ref':'object:1',
                                            'due_day':5, 'expected':'Scout the next passage.'})
        reply = self.reply(request, update)
        self.assertEqual(validate_reply(request, reply), reply)
        update['plan']['milestones'][1]['due_day'] = 4
        self.assertEqual(validate_reply(request, reply), reply)
        update['plan']['milestones'][1]['due_day'] = 1
        self.assertEqual(validate_reply(request, reply), reply)

    def test_distinct_executors_cannot_promise_the_same_unassigned_target(self):
        request, update = campaign_request(), campaign_update()
        request['memory']['known_objects'].append({'ref':'object:5','kind':'mine'})
        update['plan']['milestones'] = [
            {'target_ref':'object:5','executor_ref':hero,'due_day':4,'expected':'Capture mine.'}
            for hero in ('object:1','object:2')]
        with self.assertRaises(ValueError): validate_reply(request, self.reply(request, update))

    def test_campaign_budget_counts_compact_utf8_wire_bytes(self):
        request, update = campaign_request(), campaign_update()
        update['plan']['milestones'] *= 6
        def expand(value):
            for key, item in value.items():
                if key in ('reason', 'victory_method', 'benefit', 'constraint', 'expected',
                           'task', 'purpose', 'release_if', 'cost', 'risk', 'abandon_if'):
                    value[key] = 'x' * 119
                elif isinstance(item, dict): expand(item)
                elif isinstance(item, list):
                    for record in item:
                        if isinstance(record, dict): expand(record)
        expand(update)
        size = len(json.dumps(update, ensure_ascii=False, separators=(',', ':')).encode())
        self.assertLessEqual(size, 4096)
        self.assertGreater(len(json.dumps(update).encode()), 4096)
        reply = self.reply(request, update)
        self.assertEqual(validate_reply(request, reply), reply)

    def test_campaign_and_operational_plan_commit_as_one_consistent_intent(self):
        from test_strategy import PLAN
        request, update = campaign_request(), campaign_update()
        operational = {**PLAN, 'target_ref':'object:4', 'executor_ref':'object:1'}
        reply = {**self.reply(request, update), 'strategy':operational}
        self.assertEqual(validate_reply(request, reply), reply)
        operational['executor_ref'] = 'object:2'
        with self.assertRaises(ValueError): validate_reply(request, reply)

    def test_retain_needs_observed_basis_and_cannot_keep_a_lost_executor(self):
        request = campaign_request()
        request['memory']['campaign'] = campaign_update()['plan']
        retain = {'decision':'retain', 'reason':'The same army remains available.',
                  'evidence_refs':['hero:object:1'], 'plan':None}
        reply = self.reply(request, retain)
        self.assertEqual(validate_reply(request, reply), reply)
        request['observation']['heroes'] = [{'id':2}]
        with self.assertRaises(ValueError): validate_reply(request, reply)
        request = campaign_request()
        with self.assertRaises(ValueError): validate_reply(request, self.reply(request, retain))

    def test_all_owned_heroes_remain_in_model_input_beyond_storage_budget(self):
        from prompt_context import bounded_history
        request = campaign_request()
        request['observation']['heroes'] += [{'id':n} for n in range(10,40)]
        request['memory']['campaign'] = campaign_update()['plan']
        request['memory']['known_objects'] += [
            {'ref':'object:'+str(n),'last_seen_day':0,'stale':True,'description':'x'*1000}
            for n in range(100,150)]
        projected, _ = bounded_history(request)
        self.assertEqual(projected['observation']['heroes'], request['observation']['heroes'])
        self.assertEqual(projected['memory']['campaign'], request['memory']['campaign'])
        self.assertIn('object:4', [o['ref'] for o in projected['memory']['known_objects']])
        self.assertEqual(projected['memory']['campaign_review'], request['memory']['campaign_review'])

    def test_retain_completed_pickup_but_reject_new_or_unconfirmed_absent_target(self):
        request = campaign_request()
        request['memory']['campaign'] = campaign_update()['plan']
        request['memory']['known_objects'][0].update(
            kind='resource', not_seen_at_last_position=True, collected_by_us=True)
        request['actions'] = [{'id':'end', 'kind':'end_turn'}]
        retain = {'decision':'retain', 'reason':'The assigned pickup is complete.',
                  'evidence_refs':['hero:object:1'], 'plan':None}
        reply = {**self.reply(request, retain), 'action_id':'end'}
        self.assertEqual(validate_reply(request, copy.deepcopy(reply)), reply)
        sys.path.insert(0, str(ROOT))
        from playtesting.controller import validate_reply as recorded
        self.assertEqual(recorded(request, json.dumps(reply)), reply)
        with self.assertRaises(ValueError):
            validate_reply(request, {**reply, 'campaign':campaign_update()})
        request['memory']['known_objects'][0]['collected_by_us'] = False
        with self.assertRaises(ValueError): validate_reply(request, reply)

    def test_reply_size_includes_campaign_operational_plan_and_batch(self):
        from test_strategy import PLAN
        from prompt_context import compact_json
        request = campaign_request()
        request['observation']['batch_action_limit'] = 32
        ids = ['step-'+str(n)+'-'+'x'*160 for n in range(31)]
        request['actions'] += [{'id':i,'kind':'visit'} for i in ids]
        operational = {**PLAN,'target_ref':'object:4','executor_ref':'object:1'}
        for key in ('goal','rationale','reserves','progress','change_reason'): operational[key] = 'x'*240
        for key in ('steps','reconsider_if'): operational[key] = ['x'*160]*4
        reply = {'protocol':1,'request_id':request['request_id'],'action_id':'move',
                 'strategy':operational,'campaign':campaign_update(),
                 'follow_up_action_ids':ids[:1]}
        self.assertEqual(validate_reply(request, copy.deepcopy(reply)),reply)
        reply['follow_up_action_ids'] = ids
        self.assertGreater(len(compact_json(reply).encode()),8192)
        with self.assertRaisesRegex(ValueError,'transport limit'): validate_reply(request,reply)

    def test_real_entrypoint_applies_schema_and_never_emits_a_conflicting_batch(self):
        request = campaign_request()
        request['observation']['batch_action_limit'] = 32
        update = campaign_update()
        with tempfile.TemporaryDirectory() as directory:
            fixture = codex_fixture(Path(directory), '''
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
request = json.load(sys.stdin)
schema = json.loads(pathlib.Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
assert 'campaign' in schema['required']
update = json.loads(os.environ['TEST_CAMPAIGN'])
reply = {'protocol':1, 'request_id':request['request_id'], 'action_id':'move',
         'strategy':None, 'campaign':update, 'follow_up_action_ids':['end']}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{}}))
''')
            for valid in (True, False):
                candidate = copy.deepcopy(update)
                if not valid: candidate['plan']['assignments'][1]['target_ref'] = 'object:4'
                child = subprocess.run([sys.executable, str(ROOT/'controller/main.py')],
                    input=json.dumps(request), text=True, capture_output=True, timeout=15,
                    env={**os.environ, **fixture, 'VCMI_EXPERIENCE_MODE':'off', 'TEST_CAMPAIGN':json.dumps(candidate)})
                self.assertEqual(child.returncode, 0, child.stderr)
                reply, metadata = json.loads(child.stdout), json.loads(child.stderr)
                self.assertEqual(metadata['provider'], 'codex' if valid else 'fallback')
                self.assertEqual(reply['action_id'], 'move' if valid else 'end')
                if valid: self.assertEqual(reply['campaign'], update)
                else: self.assertNotIn('campaign', reply)

if __name__ == '__main__': unittest.main()
