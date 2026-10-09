"""A concrete waiting obligation supplies its course and preparation basis."""
import copy
import unittest
from controller.native_strategy import validate_reply
from test_nullkiller3_controller import strategic_request
from test_strategy_guide import final_reply


class DecisionBasisTest(unittest.TestCase):
    def preparation(self):
        request = strategic_request()
        reply = final_reply(request)
        hold = dict(id='wait', kind='preserve_force', actor_ref='object:0', target_ref='object:1',
                    deadline_day=3, priority=70, building_id=-1, min_army_value=0,
                    depends_on=['guild'], required_capabilities=['land'],
                    complete_when=dict(kind='force_preserved_until', value=3))
        reply['plan']['goals'].append(hold)
        reply['assignments'] = [dict(hero_ref='object:0', role='main')]
        reply['operation_focus']['bindings'].append(dict(goal_id='wait', milestone_id='stage-1'))
        reply['strategy_update']['selected']['milestones'][0]['complete_when'] = dict(
            kind='army_at_least', actor_ref='object:0', target_ref=None, value=1)
        reply['decision_basis'] = dict(waits=[dict(goal_id='wait', purpose='prepare',
                                                  basis_goal_ids=['guild'], next_goal_id=None)], town_choices=[])
        return request, reply

    def test_first_choice_accepts_null_native_goal_statuses(self):
        request=strategic_request()
        request['observation']['goal_statuses']=None
        reply=final_reply(request)
        self.assertIs(validate_reply(request,reply),reply)

    def test_one_hero_can_keep_independent_preservation_in_same_refuge(self):
        request,reply=self.preparation()
        first=reply['plan']['goals'][-1]
        first.update(depends_on=[],min_army_value=1000)
        second=copy.deepcopy(first)
        second.update(id='second-wait',min_army_value=2000,deadline_day=4)
        second['complete_when']['value']=4
        reply['plan']['goals'].append(second)
        reply['operation_focus']['bindings'].append(dict(goal_id='second-wait',milestone_id='stage-1'))
        reply['decision_basis']['waits']=[dict(goal_id=g['id'],purpose='safety',basis_goal_ids=[g['id']],
                                               next_goal_id=None) for g in (first,second)]
        reply['plan']['reserves']=[dict(goal_id=g['id'],force_value=g['min_army_value'],resources=[0]*7)
                                  for g in (first,second)]
        self.assertIs(validate_reply(request,reply),reply)

    def test_actorless_construction_dependencies_need_no_hero_wait_basis(self):
        for retained in (False,True):
            request=strategic_request();reply=final_reply(request)
            request['observation']['towns'][0]['building_options'].append(dict(id=1,supported=True))
            second=copy.deepcopy(reply['plan']['goals'][0])
            second.update(id='second-building',building_id=1,depends_on=['guild'])
            second['complete_when']['value']=1
            reply['plan']['goals'].append(second)
            reply['operation_focus']['bindings'].append(dict(goal_id=second['id'],milestone_id='stage-1'))
            request['observation']['goal_statuses']={second['id']:dict(state='blocked',reason='dependency_unconfirmed')}
            if retained:
                request['campaign']=copy.deepcopy(reply['plan'])
                request['strategic_intent']=dict(reply['strategy_update']['selected'],version=1,revision=1,
                    adopted_day=1,progress={},bindings=[])
                reply['decision']='retain';reply['plan']=None
                reply['strategy_update']=dict(decision='keep',base_revision=1,selected=None,change_reason=None)
            with self.subTest(retained=retained):
                self.assertIs(validate_reply(request,reply),reply)

    def test_attained_army_is_not_new_preparation(self):
        request, reply = self.preparation()
        with self.assertRaisesRegex(ValueError, 'preparation_result_already_satisfied'):
            validate_reply(request, reply)

    def test_conditional_far_course_does_not_require_ready_future_operation(self):
        request,reply=self.preparation()
        request['observation']['map_overview']=dict(objects=[dict(ref='far:town',kind='town',owner=1,visible=True)])
        reply['strategy_update']['selected']['milestones'][0]['complete_when']=dict(
            kind='target_owned',target_ref='far:town',actor_ref=None,value=0)
        self.assertIs(validate_reply(request,reply),reply)

    def test_useful_safety_needs_no_daily_army_gain(self):
        request,reply=self.preparation()
        reply['decision_basis']['waits'][0].update(purpose='safety',basis_goal_ids=['wait'])
        self.assertIs(validate_reply(request,reply),reply)

    def test_basis_refs_cannot_substitute_for_wait_binding(self):
        request,reply=self.preparation()
        reply['decision_basis']['waits'][0].update(purpose='safety',basis_goal_ids=['wait'])
        reply['operation_focus']['bindings'].pop()
        with self.assertRaisesRegex(ValueError,'unbound_wait_goal'):validate_reply(request,reply)

    def test_first_retain_and_revise_all_require_basis(self):
        request,reply=self.preparation()
        reply['decision_basis']['waits'][0].update(purpose='safety',basis_goal_ids=['wait'])
        for retained in (False,True):
            r=copy.deepcopy(request);a=copy.deepcopy(reply)
            if retained:
                r['campaign']=copy.deepcopy(a['plan']);a['decision']='retain';a['plan']=None
                r['strategic_intent']=dict(a['strategy_update']['selected'],version=1,revision=1,adopted_day=1,progress={},bindings=[])
                a['strategy_update']=dict(decision='keep',base_revision=1,selected=None,change_reason=None)
                a['defense_exit']=dict(waiting_for='Review threat',expected_gain='Keep safe force',next_step='Requote attack')
            validate_reply(r,a)
            a['decision_basis']['waits']=[]
            with self.subTest(retained=retained),self.assertRaisesRegex(ValueError,'missing_wait_basis'):
                validate_reply(r,a)

    def test_historical_capture_is_not_current_ownership(self):
        request,reply=self.preparation()
        request['observation']['objects'].append(dict(ref='lost:town',kind='town',visible=True,owner=1))
        stage=reply['strategy_update']['selected']['milestones'][0]
        stage['complete_when']=dict(kind='target_owned',target_ref='lost:town',actor_ref=None,value=0)
        request['strategic_intent']=dict(reply['strategy_update']['selected'],version=1,revision=1,
            adopted_day=1,progress={'stage-1':dict(completed=True,currently_satisfied=False)},bindings=[])
        reply['strategy_update']=dict(decision='keep',base_revision=1,selected=None,change_reason=None)
        validate_reply(request,reply)

if __name__ == '__main__':
    unittest.main()
