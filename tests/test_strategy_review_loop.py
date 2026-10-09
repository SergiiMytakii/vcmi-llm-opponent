"""Accepted operations cover only the question they actually answer."""
import copy
import json
import subprocess
import unittest
from pathlib import Path
import test_decision_basis_native as basis
DRIVER=basis.DRIVER

@unittest.skipUnless(DRIVER.is_file(), 'requires native value driver')
class QuestionCoverageTest(unittest.TestCase):
    def run_case(self, case):
        result=subprocess.run([str(DRIVER),'--question-coverage'],input=json.dumps(case),
                              text=True,capture_output=True,check=True)
        return json.loads(result.stdout)

    def test_exact_milestone_and_live_wait_cover_until_exit_without_target_change(self):
        case=basis.NativeDecisionBasisTest().preparation(conditional=True)
        question='strategy:no_progress:stage-1'
        case['request']['signals']=[dict(question=question,facts='unchanged town')]
        result=self.run_case(case)
        self.assertEqual(result['coverage'][0]['question'],question)
        self.assertIn('wait',result['coverage'][0]['goal_ids'])
        self.assertFalse(result['reopened'])
        case['end_goal']='wait'
        result=self.run_case(case)
        self.assertEqual(result['reopened'],[question])
        self.assertEqual(result['coverage'],[])

    def test_unrelated_or_unaccepted_part_cannot_cover_stall(self):
        case=basis.NativeDecisionBasisTest().preparation(conditional=True)
        case['request']['signals']=[dict(question='strategy:no_progress:other',facts='unchanged')]
        self.assertEqual(self.run_case(case)['coverage'],[])
        case['request']['signals'][0]['question']='strategy:no_progress:stage-1'
        case['reply']['operation_focus']['bindings']=[]
        self.assertEqual(self.run_case(case)['coverage'],[])

    def test_fresh_corrected_obligation_closes_the_exact_ended_basis_question(self):
        case=basis.NativeDecisionBasisTest().preparation(conditional=True)
        goal=case['reply']['plan']['goals'][-1];goal['depends_on']=[]
        case['reply']['decision_basis']['waits'][0].update(purpose='safety',basis_goal_ids=['wait'])
        case.update(question='decision_basis:hashed-event',facts=json.dumps(dict(actor_ref='object:0',purpose='prepare',ended_reason='preparation_completed')))
        result=subprocess.run([str(DRIVER),'--signal-coverage'],input=json.dumps(case),text=True,capture_output=True,check=True)
        self.assertTrue(json.loads(result.stdout)['covered'])
        # Actorless unrelated construction supplies no correction for that wait.
        case['reply']['plan']['goals'].pop()
        result=subprocess.run([str(DRIVER),'--signal-coverage'],input=json.dumps(case),text=True,capture_output=True,check=True)
        self.assertFalse(json.loads(result.stdout)['covered'])
        case.update(question='townless_survival',facts='previously townless')
        result=subprocess.run([str(DRIVER),'--signal-coverage'],input=json.dumps(case),text=True,capture_output=True,check=True)
        self.assertTrue(json.loads(result.stdout)['covered'])


class RoleAdmissionTest(unittest.TestCase):
    def test_captured_weak_hold_is_refused_by_controller(self):
        from controller.native_strategy import validate_reply
        root=Path(__file__).resolve().parents[1]
        captured=json.loads((root/'tests/fixtures/nk3_strategy_review_day2.json').read_text())
        request=captured['request'];reply=captured['reply']
        with self.assertRaisesRegex(ValueError,'weaker_main_without_supported_offense'):
            validate_reply(request,reply,wire=True)
        for assignment in reply['assignments']:
            if assignment['hero_ref']=='object:0':assignment['role']='main'
            if assignment['hero_ref']=='object:4':assignment['role']='defender'
        validate_reply(request,reply,wire=True)

    @unittest.skipUnless(DRIVER.is_file(), 'requires native value driver')
    def test_weak_actor_quotes_match_native_admission_and_deliveries(self):
        from controller.native_strategy import validate_reply
        from test_nullkiller3_controller import strategic_request
        from test_strategy_guide import final_reply
        request=strategic_request();world=request['observation']
        world['heroes'][0]['position']=[1,1,0];world['towns'][0]['position']=[1,1,0]
        world['heroes'].append(dict(id=2,ref='stronger',army_value=15000,position=[2,1,0]))
        world['enemy_players']=[1];world['daily_income']=[0]*7
        world['objects'].append(dict(id=3,ref='enemy',kind='hero',owner=1,visible=True))
        world['forecasts']=dict(routes=[dict(target_ref='enemy',own_arrivals=[dict(hero_ref='object:0',day=2,army_value=5000,army_loss_estimate=500)])],defenses=[])
        reply=final_reply(request);goal=reply['plan']['goals'][0]
        goal.update(kind='intercept_hero',actor_ref='object:0',target_ref='enemy',building_id=-1,min_army_value=1000,
                    required_capabilities=['land'],complete_when=dict(kind='enemy_engaged',value=0))
        reply['assignments']=[dict(hero_ref='object:0',role='main'),dict(hero_ref='stronger',role='defender')]
        def check(expected):
            observed=subprocess.run([str(DRIVER),'--reinforcement-observation'],input=json.dumps(world),text=True,capture_output=True,check=True)
            world.update(json.loads(observed.stdout))
            try:validate_reply(request,reply);controller=True
            except ValueError:controller=False
            wire=copy.deepcopy(reply);wire['usage']=dict(known=True,input_tokens=1,output_tokens=1)
            request['evidence_refs']=reply['evidence_refs']
            result=subprocess.run([str(DRIVER),'--decision'],input=json.dumps(dict(request=request,reply=wire,world=world,current=None)),text=True,capture_output=True,check=True)
            native=json.loads(result.stdout)
            self.assertEqual((controller,native['accepted']),(expected,expected),native)
        check(True)
        route=world['forecasts']['routes'][0]['own_arrivals'][0];route['army_loss_estimate']=2000;check(False)
        goal['risk']=dict(max_loss_ratio=.5,reason='Named interception of a base threat');check(True)
        world['forecasts']['routes']=[];check(False)
        goal.pop('risk');goal.update(kind='reinforce_hero',target_ref='stronger',min_army_value=6000,
                                    required_capabilities=['land','transfer'],complete_when=dict(kind='army_at_least',value=6000))
        world['heroes'][0]['army_units']=[dict(creature=1,count=50,unit_value=100)]
        world['heroes'][1]['army_units']=[dict(creature=1,count=150,unit_value=100)]
        world['forecasts']['routes']=[dict(target_ref='object:0',own_arrivals=[dict(hero_ref='stronger',day=2,army_value=15000,army_loss_estimate=0)])]
        check(True)
        world['forecasts']['routes'][0]['own_arrivals'][0]['day']=9;check(False)
        world['forecasts']['deliveries']=[dict(goal_id='old',recipient_ref='object:0',source_ref='stronger',
            status='conditional',required_value=6000,arrival_day=9,deadline_day=10)]
        check(False)
        world['forecasts']['deliveries']=[]
        world['forecasts']['routes'][0]['own_arrivals'][0]['day']=2
        world['heroes'][1].update(army_units=[dict(creature=1,count=1,unit_value=15000)],minimum_retained_army_value=15000)
        check(False)
        world['heroes'].pop();check(False)


class ControllerFeedbackTest(unittest.TestCase):
    def test_closed_semantic_rejections_traverse_subprocess_reader_restore_and_next_request(self):
        import os,sys,tempfile
        from codex_fixture import codex_fixture
        from test_strategy_guide import MODEL,final_reply
        from test_nullkiller3_controller import strategic_request
        from controller.native_strategy import validate_rejection
        root=Path(__file__).resolve().parents[1]
        request=strategic_request();reply=final_reply(request)
        cases={}
        weak=copy.deepcopy(reply);request['observation']['heroes'].append(dict(id=2,ref='stronger',army_value=15000))
        weak['assignments']=[dict(hero_ref='object:0',role='main')]
        cases['weaker_main_without_supported_offense']=weak
        focus=copy.deepcopy(reply);focus['operation_focus']['revision']=2
        cases['invalid_strategic_operation_focus']=focus
        wait_case=basis.NativeDecisionBasisTest().preparation(conditional=True)
        wait_request=wait_case['request'];wait=wait_case['reply'];wait.pop('usage')
        wait['decision_basis']['waits'][0]['purpose']='intercept'
        cases['unsupported_wait_purpose']=(wait_request,wait)
        target=copy.deepcopy(reply)
        request['observation']['objects'].append(dict(ref='resource',kind='resource',visible=True))
        target['strategy_update']['selected']['milestones'][0]['complete_when']=dict(kind='target_owned',target_ref='resource',actor_ref=None,value=0)
        cases['unsupported_strategic_ownership_target']=target
        action=copy.deepcopy(target)
        action['strategy_update']['selected']['milestones'][0]['complete_when']=dict(kind='site_visited',target_ref='resource',actor_ref='object:0',value=0)
        cases['unsupported_strategic_action_target']=action
        for code,value in cases.items():
            r,answer=value if isinstance(value,tuple) else (request,value)
            with self.subTest(code=code),tempfile.TemporaryDirectory() as folder:
                env={**os.environ,**codex_fixture(Path(folder),MODEL),'CAPTURE':folder,'FINAL_REPLY':json.dumps(answer),
                     'VCMI_PLAYTEST_DECISION_DIR':folder,'VCMI_EXPERIENCE_MODE':'off',
                     'VCMI_STRATEGY_GUIDE_MODE':'off','VCMI_GAME_RULES_MODE':'off'}
                result=subprocess.run([sys.executable,str(root/'controller/main.py')],input=json.dumps(r),
                    text=True,capture_output=True,env=env,timeout=12)
                self.assertEqual(result.returncode,0,result.stderr)
                rejection=json.loads(result.stdout);validate_rejection(r,rejection)
                self.assertEqual(rejection['failure'],dict(code=code))
                feedback=subprocess.run([str(DRIVER),'--controller-feedback'],
                    input=json.dumps(dict(reply=rejection,request=r)),text=True,capture_output=True,check=True)
                next_request=json.loads(feedback.stdout)
                self.assertEqual(next_request['observation']['decision_feedback']['failure']['code'],code)
                # The next actual model request receives native-restored feedback.
                second=Path(folder)/'second';second.mkdir()
                env.update(VCMI_PLAYTEST_DECISION_DIR=str(second),FINAL_REPLY=json.dumps(answer))
                subprocess.run([sys.executable,str(root/'controller/main.py')],input=json.dumps(next_request),
                    text=True,capture_output=True,env=env,timeout=12,check=True)
                captured=json.loads((Path(folder)/'call-2.json').read_text())['request']
                self.assertEqual(captured['observation']['decision_feedback']['failure']['code'],code)
                rejection['identity']['day']+=1
                invalid=subprocess.run([str(DRIVER),'--controller-feedback'],
                    input=json.dumps(dict(reply=rejection,request=r)),text=True,capture_output=True,check=True)
                self.assertIsNone(json.loads(invalid.stdout)['observation']['decision_feedback'])
