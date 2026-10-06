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
    if not {'reference_key', 'shared', 'request'} <= set(encoded):
        return encoded
    marker, definitions = encoded['reference_key'], encoded['shared']

    def expand(value):
        if isinstance(value, dict):
            if list(value) == [encoded.get('object_key')]:
                shape, *cells = value[encoded['object_key']]
                return {**{key:expand(cell) for key,cell in encoded.get('field_defaults',{}).get(str(shape),{}).items()},
                        **{key:expand(cell) for key,cell in zip(encoded['fields'][shape], cells)}}
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
            self.assertEqual(schema['properties']['action_id']['enum'], [a['id'] for a in request['actions']])
            self.assertEqual(info['input_encoding']['sent_bytes'], len(raw.encode('utf-8')))
            return raw, info

    @unittest.skipUnless(os.environ.get('VCMI_CONTEXT_OVERFLOW_REQUEST'),
                         'requires private recorded own strategic overflow request')
    def test_recorded_strategic_request_fits_without_losing_current_facts(self):
        sys.path.insert(0,str(ROOT/'controller'))
        from prompt_context import bounded_history, without_unknown_army_values, encode_request, compact_json, SOFT_INPUT_BYTES
        request=json.loads(Path(os.environ['VCMI_CONTEXT_OVERFLOW_REQUEST']).read_text())
        original=copy.deepcopy(request)
        projected,_=bounded_history(without_unknown_army_values(request))
        encoded=encode_request(projected)
        self.assertEqual(json.dumps(restore_request(encoded),sort_keys=True),json.dumps(projected,sort_keys=True))
        self.assertEqual(request,original)
        self.assertLessEqual(len(compact_json(encoded).encode('utf-8')),SOFT_INPUT_BYTES)

    @unittest.skipUnless(os.environ.get('VCMI_CONTEXT_OVERFLOW_REQUEST'),
                         'requires private recorded own strategic overflow request')
    def test_recorded_request_reaches_provider_through_strategic_controller(self):
        request=json.loads(Path(os.environ['VCMI_CONTEXT_OVERFLOW_REQUEST']).read_text())
        previous=ROOT/'.build/s-duel-review-v18/decisions/9b5e5e591691441dbd58a336e87b3e29/stdout.bin'
        answer=json.loads(previous.read_bytes())
        answer.update(request_id=request['request_id'],identity=request['identity'],decision='retain',plan=None)
        answer.pop('usage',None)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'reply.json').write_text(json.dumps(answer))
            script="""
import json,os,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin);pathlib.Path(os.environ['PROMPT_CAPTURE']).write_text(json.dumps(r))
answer=json.loads(pathlib.Path(os.environ['PROBE_REPLY']).read_text())
schema=json.loads(pathlib.Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
if 'kind' in schema['properties']:answer={'kind':'decision','decision':answer,'guide_request':None}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
"""
            result=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(request),
                text=True,capture_output=True,timeout=10,
                env={**os.environ,**codex_fixture(folder,script),'VCMI_EXPERIENCE_MODE':'off',
                     'PROMPT_CAPTURE':str(folder/'capture.json'),'PROBE_REPLY':str(folder/'reply.json')})
            self.assertEqual(result.returncode,0,result.stderr)
            info=json.loads(result.stderr)
            self.assertEqual(info['provider'],'codex')
            self.assertLessEqual(info['input_encoding']['sent_bytes'],131072)
            self.assertEqual(json.loads(result.stdout)['identity'],request['identity'])
            from prompt_context import without_unknown_army_values
            projected=without_unknown_army_values(request)
            captured=json.loads((folder/'capture.json').read_text())
            self.assertEqual(json.dumps(captured['observation'],sort_keys=True),json.dumps(projected['observation'],sort_keys=True))

    @unittest.skipUnless(os.environ.get('VCMI_LEARNING_PRESSURE_REQUEST') and os.environ.get('VCMI_LEARNING_PRESSURE_DATABASE'),
                         'requires private strategic request and copied learning database')
    def test_analysis_context_is_independent_of_strategic_input_pressure(self):
        sys.path.insert(0,str(ROOT/'controller'))
        import sqlite3
        from experience import Experience
        request=json.loads(Path(os.environ['VCMI_LEARNING_PRESSURE_REQUEST']).read_text())
        request.pop('experience',None);original=copy.deepcopy(request)
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'learning.sqlite3'
            source=sqlite3.connect(Path(os.environ['VCMI_LEARNING_PRESSURE_DATABASE']).resolve().as_uri()+'?mode=ro',uri=True)
            target=sqlite3.connect(database);source.backup(target);target.close();source.close()
            store=Experience(database,'learn')
            try:
                store.observe(request)
                pending={row['id']:json.loads(row['payload']) for row in store.db.execute('SELECT id,payload FROM episodes WHERE assessed=0')}
                context=store.context(request)
                self.assertTrue(pending)
                self.assertTrue(context['episodes'],'strategy size must not prevent separate analysis')
                self.assertEqual(request,original)
                self.assertNotIn('experience',request)
                for episode in context['episodes']:self.assertEqual(episode,pending[episode['id']])
            finally:store.close()

    def test_route_defaults_preserve_overrides_nulls_and_scalar_types_on_model_stdin(self):
        request=self.request()
        request['observation']['routes']=[
            dict(hero_ref='object:0',army_value=516972,army_loss=0,stale=False,
                 day=95+n%4,movement_cost=n/100,position=[n,2,0],unknown=None) for n in range(240)]
        for n,value in enumerate([False,0,True,1,1.0,None]):
            request['observation']['routes'][n].update(army_loss=value,unknown=value)
        raw,_=self.call(request)
        encoded=json.loads(raw)
        self.assertIn('field_defaults',encoded)
        self.assertEqual(json.dumps(restore_request(encoded),sort_keys=True),json.dumps(request,sort_keys=True))

    def test_model_receives_compact_utf8_without_changing_game_facts(self):
        request = self.request()
        raw, _ = self.call(request)
        self.assertIn('Гильдия магов', raw)
        self.assertNotIn('\\u', raw)
        self.assertNotIn(': ', raw)
        self.assertNotIn(', ', raw)
        self.assertEqual(json.loads(raw), request)

    def test_varied_routes_share_field_names_without_dropping_actions_or_facts(self):
        request = self.request()
        request['observation']['routes'] = [
            {'hero':n % 3, 'target_ref':'object:' + str(n), 'travel_turns':n / 10,
             'owner':n % 4, 'resource_type':'wood' if n % 2 else 'ore',
             'resource_amount':None, 'stale':bool(n % 2), 'last_seen_day':n,
             'unseen_threats':'unknown', 'guard_strength_minimum':n * 100,
             'guard_strength_maximum':n * 200} for n in range(60)]
        request['actions'] += [{'id':'move-' + str(n), 'kind':'visit', **route}
                               for n,route in enumerate(request['observation']['routes'])]
        original = copy.deepcopy(request)
        raw, info = self.call(request)
        encoded = json.loads(raw)
        self.assertIn('fields', encoded)
        self.assertEqual(restore_request(encoded), original)
        self.assertEqual(request, original)
        self.assertLess(len(raw.encode()), len(json.dumps(original, ensure_ascii=False).encode()) * .7)
        self.assertIn('parts', info['input_encoding'])

    def test_history_budget_keeps_current_choices_plan_threats_and_uncertainty(self):
        request = self.request()
        request['observation']['player'] = 0
        request['observation']['day'] = 20
        threat = {'id':900, 'ref':'object:900', 'kind':'hero', 'owner':1,
                  'stale':True, 'last_seen_day':1, 'position':[7,8,0],
                  'army':{'quantity':None, 'note':'Old uncertain enemy army' * 10}}
        target = {'id':901, 'ref':'object:901', 'kind':'mine', 'owner':-1,
                  'resource_type':'wood', 'stale':True, 'last_seen_day':1}
        request['memory'] = {'plan':None, 'experience_id':'test-game',
            'known_objects':[{'id':n,'ref':'object:' + str(n),'kind':'frontier',
                              'last_seen_day':0,'stale':True,'note':'old frontier ' * 100}
                             for n in range(100)] + [threat,target],
            'recent_results':[{'sequence':1,'day':1,'outcome':'unconfirmed',
                               'action':{'id':'pending','kind':'attack','target_ref':'object:900'}}]}
        original = copy.deepcopy(request)
        raw, info = self.call(request)
        model = restore_request(json.loads(raw))
        self.assertEqual(request, original)
        self.assertEqual(model['observation'], original['observation'])
        self.assertEqual(model['actions'], original['actions'])
        self.assertEqual(model['memory']['plan'], original['memory']['plan'])
        self.assertIn(threat, model['memory']['known_objects'])
        self.assertIn(target, model['memory']['known_objects'])
        self.assertEqual(model['memory']['recent_results'], original['memory']['recent_results'])
        self.assertLessEqual(len(json.dumps(model['memory'], ensure_ascii=False, separators=(',', ':')).encode()), 32768)
        self.assertTrue(info['input_encoding']['history']['applied'])

    def test_protected_history_can_exceed_budget_without_hiding_threats(self):
        request = self.request()
        request['observation'].update(player=0, day=20)
        request['memory'] = {'plan':None, 'known_objects':[
            {'id':n,'ref':'object:' + str(n),'kind':'hero','owner':1,
             'last_seen_day':1,'stale':True,'note':'uncertain enemy ' * 100}
            for n in range(25)], 'recent_results':[]}
        raw, info = self.call(request)
        self.assertEqual(restore_request(json.loads(raw)), request)
        self.assertTrue(info['input_encoding']['history']['over_budget'])
        self.assertEqual(info['input_encoding']['history']['omitted_sightings'], 0)

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
        request['observation']['literal'] = {'$ref':0, '$ref_':{'$ref':1}, '$obj':[0,None]}
        raw, _ = self.call(request)
        encoded = json.loads(raw)
        self.assertNotIn(encoded['reference_key'], {'$ref', '$ref_'})
        self.assertNotEqual(encoded.get('object_key'), '$obj')
        restored = restore_request(encoded)
        self.assertEqual(restored, request)
        self.assertEqual([type(x) for x in restored['observation']['records'][0]['flags']],
                         [bool,int,bool,int,float])


if __name__ == '__main__':
    unittest.main()
