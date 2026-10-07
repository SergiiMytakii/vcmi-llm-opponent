"""Model decisions bind helper hires to offered candidates and useful jobs."""
from fixtures.strategic_intent import with_intent
import copy
import unittest
from test_nullkiller3_controller import strategic_request
from controller.native_strategy import validate_reply


def reply(request,goal):
    return with_intent(request,dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
        reason='Hire a scout for the offered frontier',evidence_refs=['town:object:1'],victory_method='Expand safely',
        assignments=[dict(hero_ref='object:0',role='main')],
        alternatives=[dict(approach='scouting',benefit='Separate exploration',cost='Hiring expense',uncertainty='Post-hire routes unknown'),
                      dict(approach='defense',benefit='Keep base protected',cost='Delay expansion',uncertainty='Enemy intent unknown')],
        reconsider_when=[dict(goal_id=goal['id'],kind='deadline_missed')],
        plan=dict(version=3,revision=1,approach='scouting',horizon_days=3,goals=[goal],reserves=[],
            policy=dict(max_loss_ratio=.25,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))))


class HelperHiringControllerTest(unittest.TestCase):
    def test_offered_helper_requires_matching_town_role_job_and_funds(self):
        request=strategic_request()
        request['observation']['towns'][0]['hiring_options']=[dict(ref='tavern:17',hero_type_id=17,
            can_recruit=True,cost=[0,0,0,0,0,0,2500])]
        goal=dict(id='hire-scout',kind='hire_helper',actor_ref=None,target_ref='object:1',candidate_ref='tavern:17',
            helper_role='scout',job_ref='tile:frontier',deadline_day=2,priority=80,building_id=-1,min_army_value=0,
            depends_on=[],required_capabilities=[],complete_when=dict(kind='helper_hired',value=0))
        validate_reply(request,reply(request,goal))
        for key,value in [('candidate_ref','tavern:99'),('job_ref','hidden:job'),('helper_role','defender')]:
            bad=copy.deepcopy(goal);bad[key]=value
            with self.assertRaises(ValueError):validate_reply(request,reply(request,bad))
        request['observation']['resources'][6]=2499
        with self.assertRaises(ValueError):validate_reply(request,reply(request,goal))
        request['observation']['resources'][6]=10000
        request['campaign']=reply(request,goal)['plan']
        request['observation']['towns'][0]['hiring_options']=[]
        request['observation']['heroes'].append(dict(id=3,ref='object:3',hero_type_id=17,army_value=1000))
        request['observation']['confirmed_helper_hires']=[dict(goal=goal,day=1,hero_ref='object:3',hero_type_id=17)]
        retained=reply(request,goal);retained.update(decision='retain',plan=None)
        validate_reply(request,retained)
        request['observation']['heroes'].pop()
        request['observation']['goal_statuses']={'hire-scout':{'state':'completed'}}
        validate_reply(request,retained)  # Historical hiring must not replay after a helper is lost.
        request['observation']['confirmed_helper_hires'][0]['hero_type_id']=99
        with self.assertRaises(ValueError):validate_reply(request,retained)



class DefenseExitControllerTest(unittest.TestCase):
    def test_repeated_hold_requires_concrete_exit_review_but_allows_offense(self):
        request=strategic_request()
        request['campaign']={'approach':'defense','goals':[]}
        request['signals']=[dict(question='campaign_exhausted',facts='hold-completed')]
        goal=dict(id='hold',kind='defend_area',actor_ref='object:0',target_ref='object:1',
            deadline_day=3,priority=90,building_id=-1,min_army_value=4000,depends_on=[],
            required_capabilities=['land'],complete_when=dict(kind='held_until',value=3))
        request['campaign']['goals']=[copy.deepcopy(goal)]
        answer=reply(request,goal)
        with self.assertRaises(ValueError):validate_reply(request,answer)
        answer['defense_exit']=None
        with self.assertRaises(ValueError):validate_reply(request,answer)
        answer['defense_exit']=dict(waiting_for='Known weekly growth',expected_gain='Buy offered defenders when stock appears',
                                   next_step='Requote interception and departure after confirmed recruitment')
        validate_reply(request,answer)
        request['observation']['objects'].append(dict(ref='object:2',kind='mine',owner=1,visible=True))
        answer['plan']['goals'][0].update(kind='capture_target',target_ref='object:2',complete_when=dict(kind='target_owned',value=0))
        answer['defense_exit']=None
        validate_reply(request,answer)

    def test_hold_reassessment_covers_all_signals_approaches_and_retention(self):
        goal=dict(id='hold',kind='preserve_force',actor_ref='object:0',target_ref='object:1',
            deadline_day=3,priority=90,building_id=-1,min_army_value=4000,depends_on=[],
            required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=3))
        for approach in ('scouting','offense','defense'):
            for signal in ('helper_hired:scout','battle_loss:scout','repair_exhausted','defense:object:1'):
                request=strategic_request();request['campaign']=reply(request,goal)['plan']
                request['campaign']['approach']=approach
                request['signals']=[dict(question=signal,facts='new')]
                for decision in ('revise','retain'):
                    with self.subTest(approach=approach,signal=signal,decision=decision):
                        a=reply(request,goal)
                        if decision=='retain':a.update(decision='retain',plan=None)
                        with self.assertRaises(ValueError):validate_reply(request,a)
                        a['defense_exit']=None
                        with self.assertRaises(ValueError):validate_reply(request,a)
                        a['defense_exit']=dict(waiting_for='New own route quotes',expected_gain='Compare viable departure',next_step='Reassess departure versus justified protection')
                        validate_reply(request,a)
