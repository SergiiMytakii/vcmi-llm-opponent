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

    def learn_loss(self):
        self.call(self.request())
        return self.call(self.request(day=2,heroes=[]))

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
