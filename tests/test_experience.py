"""Learning through the real controller subprocess and persistent storage."""
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
import json, pathlib, sys
import os
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0'); sys.exit(0)
args = sys.argv
request = json.loads(sys.stdin.read())
schema = json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
context = request.get('experience', {})
lessons = context.get('lessons', [])
episodes = context.get('episodes', [])
mode = os.environ.get('LEARNING_TEST_MODE','support')
usable = [l for l in lessons if l['status'] != 'retired']
answer = {'protocol':1, 'request_id':request['request_id'],
          'action_id':'defend' if usable else 'attack', 'strategy':None}
if mode == 'invalid-action':answer['action_id']='not-offered'
if answer['action_id'] not in [a['id'] for a in request['actions']]: answer['action_id']='end'
if mode == 'invalid-action':answer['action_id']='not-offered'
if 'learning' in schema['properties']:
    assessments=[]
    for episode in episodes[:2]:
        assessments.append({'episode_id':episode['id'], 'lesson_id':lessons[0]['id'] if lessons else None,
            'verdict':mode if mode in ('contradict','uncertain','revise') else 'support', 'rule':'Keep a defensive reserve before committing the only army to an uncertain fight.',
            'conditions':['combat','defense'], 'evidence_ids':[episode['signals'][0]['id']],
            'explanation':'The own army disappeared after the attack; the causal interpretation remains tentative.'})
    answer['learning']={'expectation':'Preserve a force that can defend the town.', 'assessments':assessments}
    if mode == 'invented' and assessments: assessments[0]['evidence_ids']=['invented-event']
    if mode == 'skip-reflection':answer['learning']['assessments']=[]
    if mode == 'revise' and assessments:
        assessments[0]['rule']='Keep a defensive reserve when a visible enemy threatens the town; otherwise consider a decisive attack.'
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
'''


class ExperienceControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vcmi experience тест ')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.env = {**os.environ, **codex_fixture(self.folder, MODEL),
                    'VCMI_EXPERIENCE_DB':str(self.folder/'experience.sqlite3'),
                    'VCMI_EXPERIENCE_MODE':'learn'}

    def request(self, game='party-one', day=1, heroes=None):
        return {'protocol':1, 'request_id':f'0:{day}:0',
                'observation':{'day':day, 'player':0,
                    'heroes':heroes if heroes is not None else [{'id':7,'strength':{'army_ai_value':1000}}],
                    'towns':[{'id':8}], 'resources':[5000]},
                'memory':{'schema':2,'experience_id':game,'plan':None,'recent_results':[]},
                'actions':[{'id':'end','kind':'end_turn'},
                           {'id':'attack','kind':'attack','hero':7},
                           {'id':'defend','kind':'recruit','town':8}]}

    def call(self, request, **env):
        result = subprocess.run([sys.executable,str(ROOT/'controller/main.py')],
                                input=json.dumps(request),text=True,capture_output=True,timeout=10,
                                env={**self.env,**env})
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout),json.loads(result.stderr)

    def test_observed_loss_becomes_a_lesson_used_by_a_new_controller_in_another_game(self):
        first,info = self.call(self.request())
        self.assertEqual(first['action_id'],'attack')
        self.assertEqual(info['provider'],'codex')
        lost = self.request(day=2,heroes=[])
        lost['memory']['recent_results']=[{'sequence':1,'day':1,'action':{'id':'attack','kind':'attack','hero':7},'outcome':'unconfirmed'}]
        self.call(lost)
        next_game,info = self.call(self.request(game='party-two'))
        self.assertEqual(next_game['action_id'],'defend')
        self.assertEqual(info['provider'],'codex')
        self.assertNotIn('learning',next_game,'engine protocol must remain unchanged')

    def test_one_offered_episode_does_not_allow_a_second_assessment_to_discard_the_choice(self):
        source = MODEL.replace("    answer['learning']={'expectation':", """    if mode == 'fill-schema' and assessments:
        capacity = schema['properties']['learning']['properties']['assessments']['maxItems']
        while len(assessments) < capacity:
            assessments.append({**assessments[0], 'explanation':'A second assessment of the same episode.'})
    answer['learning']={'expectation':""")
        self.env.update(codex_fixture(self.folder, source))
        self.call(self.request())
        reply, info = self.call(self.request(day=2, heroes=[]), LEARNING_TEST_MODE='fill-schema')
        self.assertEqual(info['provider'], 'codex', 'schema permitted duplicate episode assessment')
        self.assertEqual(reply['action_id'], 'attack')
        self.assertEqual(info['experience']['lessons_updated'], 1)

    def test_supported_confidence_requires_matching_declared_rules_and_executor(self):
        rules=dict(engine_version='1.8',engine_revision='revision-A',
                   mods=[dict(id='core',version=''),dict(id='vcmi',version='1.5')])
        for number in range(3):
            first=self.request(game='version-A-'+str(number));first['observation']['rules']=rules
            self.call(first)
            after=self.request(game='version-A-'+str(number),day=2,heroes=[])
            after['observation']['rules']=rules
            self.call(after)
        source=MODEL.replace("mode = os.environ.get('LEARNING_TEST_MODE','support')", """
mode = os.environ.get('LEARNING_TEST_MODE','support')
current=context['execution_context'];lesson=lessons[0]
assert lesson['supporting_games']==3
assert lesson['matching_supporting_games']==int(os.environ['EXPECTED_MATCHING_GAMES'])
assert lesson['confidence']==('supported' if os.environ['EXPECTED_MATCHING_GAMES']=='3' else 'hypothesis')
assert lesson['evidence_contexts_complete']
assert len(lesson['evidence_contexts'])==1
origin=lesson['evidence_contexts'][0]
assert origin['engine_revision']=='revision-A'
assert origin['execution_mechanism']=='external_actions_v1'
assert origin['supporting_games']==3
assert current['rules_known']==(os.environ['EXPECTED_RULES_KNOWN']=='1')
""")
        self.env.update(codex_fixture(self.folder,source))
        cases=[('same',rules,None,3,True),
               ('mod-order',{**rules,'mods':list(reversed(rules['mods']))},None,3,True),
               ('engine-version',{**rules,'engine_revision':'revision-B'},None,0,True),
               ('mod-version',{**rules,'mods':[dict(id='vcmi',version='2.0')]},None,0,True),
               ('unknown-mod',{**rules,'mods':[dict(id='custom',version='')]},None,0,False),
               ('native-executor',rules,'native_campaign_v3',0,True)]
        for name,current_rules,mechanism,matching,known in cases:
            with self.subTest(context=name):
                request=self.request(game='context-'+name);request['observation']['rules']=current_rules
                if mechanism:request['memory']['execution_mechanism']=mechanism
                _,info=self.call(request,EXPECTED_MATCHING_GAMES=str(matching),EXPECTED_RULES_KNOWN='1' if known else '0')
                self.assertEqual(info['provider'],'codex','the current rule/executor context was misrepresented')

    def test_native_episode_keeps_physical_town_army_and_visiting_defender_facts(self):
        first=self.request(game='native-defense')
        first['memory']['execution_mechanism']='native_campaign_v3'
        town=dict(id=8,ref='object:1',position=[5,11,0],defense_value=5679,
                  army_holder_ref='object:1',visiting_hero_ref='object:0')
        first['observation']['towns']=[town]
        first['observation']['heroes']=[dict(id=7,ref='object:0',position=[5,11,0],
                                           army_value=22666,strength=dict(army_ai_value=22666))]
        self.call(first)
        source=MODEL.replace("mode = os.environ.get('LEARNING_TEST_MODE','support')", """
mode = os.environ.get('LEARNING_TEST_MODE','support')
assert len(episodes)==1
for observation in (episodes[0]['trajectory'][-1]['observation'],episodes[0]['after']):
    town=observation['towns'][0]
    assert town['defense_value']==5679
    assert town['army_holder_ref']=='object:1'
    assert town['visiting_hero_ref']=='object:0'
    assert observation['heroes'][0]['army_value']==22666
""")
        self.env.update(codex_fixture(self.folder,source))
        after=copy.deepcopy(first);after['request_id']='0:2:1';after['observation']['day']=2
        after['observation']['resources']=[6000]
        _,info=self.call(after)
        self.assertEqual(info['provider'],'codex','native defense facts were lost in durable episode projection')

    def learn_loss(self):
        self.call(self.request())
        return self.call(self.request(day=2,heroes=[]))

    def test_native_episode_keeps_acknowledged_embark_state_in_the_model_context(self):
        first=self.request(game='native-boat')
        first['memory']['execution_mechanism']='native_campaign_v3'
        first['observation']['heroes']=[dict(id=7,ref='object:0',position=[7,11,0],army_value=1000,in_boat=False)]
        self.call(first)
        source=MODEL.replace("mode = os.environ.get('LEARNING_TEST_MODE','support')", """
mode = os.environ.get('LEARNING_TEST_MODE','support')
assert len(episodes)==1
before=episodes[0]['trajectory'][0]['observation']['heroes'][0]
after=episodes[0]['after']['heroes'][0]
assert before['position']==[7,11,0] and before['in_boat'] is False
assert after['position']==[8,11,0] and after['in_boat'] is True
assert before['army_value']==after['army_value']==1000
""")
        self.env.update(codex_fixture(self.folder,source))
        after=copy.deepcopy(first);after['request_id']='0:2:1';after['observation']['day']=2
        after['observation']['heroes'][0].update(position=[8,11,0],in_boat=True)
        after['observation']['resources']=[6000]
        _,info=self.call(after)
        self.assertEqual(info['provider'],'codex','the actual own embark state was omitted from durable learning context')

    def test_contradictory_experience_retires_a_lesson_instead_of_repeating_it(self):
        self.learn_loss()
        self.call(self.request(game='counterexample'))
        self.call(self.request(game='counterexample',day=2,heroes=[]),LEARNING_TEST_MODE='contradict')
        reply,_ = self.call(self.request(game='later-party'))
        self.assertEqual(reply['action_id'],'attack')

    def test_an_overgeneral_lesson_can_be_replaced_by_a_more_precise_rule(self):
        self.learn_loss()
        self.call(self.request(game='refinement'))
        _,info=self.call(self.request(game='refinement',day=2,heroes=[]),LEARNING_TEST_MODE='revise')
        self.assertEqual(info['provider'],'codex')
        self.assertEqual(info['experience']['lessons_updated'],1)
        # Observe the replacement through a fresh real controller call.
        self.env.update(codex_fixture(self.folder,MODEL.replace("answer = {'protocol':1", "assert any('visible enemy' in l['rule'] and l['status']=='active' for l in lessons)\nassert any('uncertain fight' in l['rule'] and l['status']=='retired' for l in lessons)\nanswer = {'protocol':1")))
        _,info=self.call(self.request(game='after-refinement'))
        self.assertEqual(info['provider'],'codex')

    def test_same_episode_is_not_learned_twice_on_retry(self):
        self.call(self.request())
        lost = self.request(day=2,heroes=[])
        _,first = self.call(lost)
        _,retry = self.call(lost)
        self.assertEqual(first['experience']['lessons_updated'],1)
        self.assertEqual(retry['experience']['lessons_updated'],0)

    def test_unknown_or_uncertain_evidence_does_not_create_an_actionable_lesson(self):
        for mode in ('invented','uncertain'):
            with self.subTest(mode=mode):
                database = str(self.folder/(mode+'.sqlite3'))
                self.call(self.request(),VCMI_EXPERIENCE_DB=database)
                _,info = self.call(self.request(day=2,heroes=[]),VCMI_EXPERIENCE_DB=database,LEARNING_TEST_MODE=mode)
                later,_ = self.call(self.request(game='next-party'),VCMI_EXPERIENCE_DB=database)
                self.assertEqual(later['action_id'],'attack')
                if mode == 'invented': self.assertEqual(info['provider'],'fallback')

    def test_incomplete_own_list_is_not_mistaken_for_a_lost_hero(self):
        self.call(self.request())
        later = self.request(day=2)
        later['observation'].pop('heroes')
        _,info = self.call(later)
        self.assertEqual(info['experience']['lessons_updated'],0)

    def test_read_only_and_off_modes_never_modify_the_library(self):
        self.learn_loss()
        database = self.folder/'experience.sqlite3'
        before = database.read_bytes()
        reply,_ = self.call(self.request(game='evaluation'),VCMI_EXPERIENCE_MODE='read_only')
        self.assertEqual(reply['action_id'],'defend')
        self.assertEqual(database.read_bytes(),before)
        reply,_ = self.call(self.request(game='without-memory'),VCMI_EXPERIENCE_MODE='off')
        self.assertEqual(reply['action_id'],'attack')
        self.assertEqual(database.read_bytes(),before)

    def test_terminal_result_is_reviewed_without_inventing_a_last_observation(self):
        self.call(self.request())
        final = self.request(day=2)
        final['request_id']='0:2:final'
        final['observation']={'day':2,'player':0,'terminal_result':'loss'}
        final['actions']=[{'id':'end','kind':'end_turn'}]
        reply,info = self.call(final)
        self.assertEqual(reply['action_id'],'end')
        self.assertEqual(info['experience']['lessons_updated'],1)
        later,_ = self.call(self.request(game='after-defeat'))
        self.assertEqual(later['action_id'],'defend')

    def test_storage_failure_keeps_the_valid_game_decision_available(self):
        reply,info = self.call(self.request(),VCMI_EXPERIENCE_DB=str(self.folder))
        self.assertEqual(reply['action_id'],'attack')
        self.assertEqual(info['provider'],'codex')
        self.assertIn('experience_error',info)

    def test_fallback_is_recorded_as_infrastructure_instead_of_a_model_attack(self):
        self.call(self.request())  # Same request revisited after loading an earlier save.
        _,info=self.call(self.request(),LEARNING_TEST_MODE='invalid-action')
        self.assertEqual(info['provider'],'fallback')
        source=MODEL.replace("episodes = context.get('episodes', [])", "episodes = context.get('episodes', [])\nif episodes:\n    assert episodes[0]['trajectory'][0]['action']['kind']=='end_turn'\n    assert episodes[0]['trajectory'][0]['action']['provider']=='fallback'")
        self.env.update(codex_fixture(self.folder,source))
        _,info=self.call(self.request(day=2,heroes=[]))
        self.assertEqual(info['provider'],'codex')

    def test_a_model_cannot_silently_skip_offered_reflection(self):
        self.call(self.request())
        _,info=self.call(self.request(day=2,heroes=[]),LEARNING_TEST_MODE='skip-reflection')
        self.assertEqual(info['provider'],'fallback')
        reply,_=self.call(self.request(game='later-party'))
        self.assertEqual(reply['action_id'],'attack')

    def test_rollback_reoffers_an_unassessed_consequence_instead_of_losing_it(self):
        self.call(self.request())
        self.call(self.request(day=2,heroes=[]),LEARNING_TEST_MODE='skip-reflection')
        self.call(self.request())
        _,info=self.call(self.request(day=2,heroes=[]))
        self.assertEqual(info['experience']['lessons_updated'],1)

    def test_same_day_rollback_does_not_expose_a_future_terminal_result(self):
        self.call(self.request())
        final=self.request()
        final['request_id']='0:1:final'
        final['observation']={'day':1,'player':0,'terminal_result':'loss'}
        self.call(final)
        self.call(self.request())
        source=MODEL.replace("episodes = context.get('episodes', [])", "episodes = context.get('episodes', [])\nassert not any('terminal_result' in d['observation'] for e in episodes for d in e['trajectory'])")
        self.env.update(codex_fixture(self.folder,source))
        _,info=self.call(self.request(day=2,heroes=[]))
        self.assertEqual(info['provider'],'codex')

    def test_retired_popular_rules_cannot_crowd_out_their_active_refinements(self):
        sys.path.insert(0,str(ROOT/'controller'))
        from experience import Experience
        store=Experience(self.folder/'ranking.sqlite3')
        self.addCleanup(store.close)
        day=0
        def offer():
            nonlocal day
            day+=1
            request=self.request(game='ranking',day=day)
            request['observation']['resources']=[1000+day]
            request['actions'].append({'id':'build','kind':'build'})
            request['experience']=store.prepare(request)
            return request
        def accept(request,rule,verdict='support',lesson_id=None):
            items=[{'episode_id':e['id'],'lesson_id':lesson_id,'verdict':verdict,'rule':rule,
                    'conditions':['economy'],'evidence_ids':[e['signals'][0]['id']],
                    'explanation':'Fixture-controlled resource change is the observed evidence.'}
                   for e in request['experience']['episodes']]
            store.accept(request,{'action_id':'build','learning':{'expectation':'Preserve useful resources.','assessments':items}})
        accept(offer(),'Initial expectation')
        for number in range(6):
            rule=f'Reserve resources for economic objective {number}.'
            for _ in range(10):
                request=offer()
                known=next((l['id'] for l in request['experience']['lessons'] if l['rule']==rule),None)
                accept(request,rule,lesson_id=known)
        for number in range(6):
            request=offer()
            old=next(l for l in request['experience']['lessons'] if l['rule']==f'Reserve resources for economic objective {number}.')
            accept(request,f'Refined rule {number}: reserve resources only when a funded economic follow-up is feasible.',
                   verdict='revise',lesson_id=old['id'])
        fresh=self.request(game='new-ranking-party')
        fresh['actions'].append({'id':'build','kind':'build'})
        lessons=store.prepare(fresh)['lessons']
        self.assertEqual(len([l for l in lessons if l['status']=='active' and l['rule'].startswith('Refined rule')]),6)


if __name__ == '__main__':
    unittest.main()
