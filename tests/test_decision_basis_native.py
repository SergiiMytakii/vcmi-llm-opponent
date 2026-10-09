"""Public native admission verifies concrete preparation without inventing routes."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
import test_decision_basis_controller as controller_basis

DRIVER = Path(__file__).resolve().parents[1] / '.build/background-values/nullkiller3-campaign-driver'

@unittest.skipUnless(DRIVER.is_file(), 'requires native value driver')
class NativeDecisionBasisTest(unittest.TestCase):
    def preparation(self, conditional=False):
        request, reply = controller_basis.DecisionBasisTest().preparation()
        reply['usage'] = dict(input_tokens=1, output_tokens=1, known=True)
        request['evidence_refs'] = reply['evidence_refs']
        world = request['observation']
        world['heroes'][0]['position'] = world['towns'][0]['position'] = [1,1,0]
        world['daily_income'] = [0]*7
        world['towns'][0]['building_options'][0].update(
            requirements=['allOf'], cost=[0]*7, availability='allowed_now')
        if conditional:
            world['map_overview'] = dict(objects=[dict(ref='far:town',kind='town',owner=1,visible=True)])
            reply['strategy_update']['selected']['milestones'][0]['complete_when'] = dict(
                kind='target_owned',target_ref='far:town',actor_ref=None,value=0)
        return dict(request=request, reply=reply, world=world, current=None)

    def run_case(self, case):
        result = subprocess.run([str(DRIVER),'--decision'],input=json.dumps(case),
                                text=True,capture_output=True,check=True)
        return json.loads(result.stdout)

    def test_attained_army_cannot_justify_new_preparation(self):
        result = self.run_case(self.preparation())
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'preparation_result_already_satisfied')

    def test_conditional_course_and_real_preparation_allow_null_next_goal(self):
        result = self.run_case(self.preparation(conditional=True))
        self.assertTrue(result['accepted'], result)

    def test_unknown_schedule_rejects_preparation_without_touching_course(self):
        case = self.preparation(conditional=True)
        case['world']['towns'][0]['building_options'][0]['availability'] = 'unknown'
        result = self.run_case(case)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'preparation_schedule_unconfirmed')
        self.assertIsNone(result['plan'])

    def test_garrison_preparation_has_existing_current_day_quote(self):
        case=self.preparation(conditional=True)
        source=case['reply']['plan']['goals'][0]
        source.update(kind='prepare_garrison',actor_ref='object:0',building_id=-1,
                      garrison_mode='recruit',required_capabilities=['land'],
                      complete_when=dict(kind='garrison_at_least',value=100))
        town=case['world']['towns'][0]
        town['recruitment_options']=[dict(creature=1,available=2,weekly_growth=0,
            unit_value=100,unit_cost=[0,0,0,0,0,0,10])]
        case['reply']['plan']['reserves']=[dict(goal_id='guild',resources=[0,0,0,0,0,0,10000],force_value=0)]
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)
        town['recruitment_options'][0]['available']=0
        result=self.run_case(case)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'],'preparation_schedule_unconfirmed')

    def test_actorless_construction_dependencies_work_first_and_retained(self):
        case=self.preparation(conditional=True)
        source=case['reply']['plan']['goals'][0]
        chained=copy.deepcopy(source)
        chained.update(id='chained',building_id=1,depends_on=['guild'],
                       complete_when=dict(kind='building_present',value=1))
        case['reply']['plan']['goals']=[source,chained]
        case['world']['towns'][0]['building_options'].append(dict(
            id=1,supported=True,requirements=['allOf',0],cost=[0]*7,availability='allowed_now'))
        case['reply']['decision_basis']=dict(waits=[],town_choices=[])
        case['reply']['operation_focus']['bindings']=[dict(goal_id='guild',milestone_id='stage-1')]
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)
        case['current']=result['plan']
        case['request']['campaign']=result['plan']
        selected=case['reply']['strategy_update']['selected']
        case['request']['strategic_intent']=dict(selected,version=1,revision=1,adopted_day=1,progress={},bindings=[])
        case['reply'].update(decision='retain',plan=None,
            strategy_update=dict(decision='keep',base_revision=1,selected=None,change_reason=None))
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)

    def test_wait_ref_requires_its_own_operation_binding(self):
        case = self.preparation(conditional=True)
        case['reply']['operation_focus']['bindings'].pop()
        result = self.run_case(case)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'unbound_wait_goal')

if __name__ == '__main__':
    unittest.main()
