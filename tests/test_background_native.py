"""Native admission keeps independent groups and rejects stale global revisions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from test_background_controller import prepared,answer

ROOT=Path(__file__).resolve().parents[1]
DRIVER=ROOT/'.build/background-values/background-planning-driver'


def fixture():
    request=prepared();world=request['observation']
    old=request['campaign']['goals'][0];old['id']='old';old['building_id']=old['complete_when']['value']=0
    old['deadline_day']=4;request['campaign']['revision']=request['identity']['revision']=1
    town=world['towns'][0];town.update(buildings=[0],recruitment_options=[])
    town['building_options']=[dict(id=i,supported=True,availability='allowed',cost=[0]*7,requirements={'allOf':[]}) for i in (0,1,2)]
    world['forecasts']=dict(routes=[],defenses=[dict(town_ref='object:1',status='no_observed_front',threats=[],unconfirmed_threats=[])])
    world['heroes'][0].update(movement=0,movement_per_day=1500,mana=5)
    world['daily_income']=[0]*7
    world['map_size']=[2,2,1];world['visible_tile_counts']=[4]
    reply=answer(request);reply['plan']['goals'][0].update(id='new',building_id=1,deadline_day=5)
    reply['plan']['goals'][0]['complete_when']['value']=1
    reply['reconsider_when'][0]['goal_id']='new';reply['operation_focus']['bindings'][0]['goal_id']='new'
    request['evidence_refs']=reply['evidence_refs']
    reply['usage']=dict(known=True,input_tokens=10,output_tokens=10)
    fresh=copy.deepcopy(world);fresh['day']=2;fresh['heroes'][0]['movement']=1500
    return dict(request=request,reply=reply,observed=copy.deepcopy(world),fresh=fresh,pending=None)


def heroes_fixture():
    case=fixture();world=case['observed']
    world['heroes'].append(dict(world['heroes'][0],ref='hero:2'))
    roles=[dict(hero_ref=h['ref'],role='collector') for h in world['heroes']]
    world['strategy_assignments']=roles;case['reply']['assignments']=copy.deepcopy(roles)
    case['request']['allowed_actor_refs']=['object:0','hero:2']
    for actor,target in (('object:0','resource:one'),('hero:2','resource:two')):
        world['objects'].append(dict(ref=target,kind='resource',visible=True,position=[1,1,0]))
        world['forecasts']['routes'].append(dict(target_ref=target,own_arrivals=[dict(hero_ref=actor,day=2,
            army_value=5000,army_loss_estimate=0,end_turn_exposure=dict(status='conditional_unchanged_route',omitted_visible_enemy_count=0,visible_threats=[]))]))
        goal=copy.deepcopy(case['reply']['plan']['goals'][0]);goal.update(id=target.replace(':','-'),kind='secure_resource',actor_ref=actor,target_ref=target,building_id=-1,min_army_value=100)
        goal['complete_when']=dict(kind='reserve_at_least',value=1)
        case['reply']['plan']['goals'].append(goal)
        case['reply']['reconsider_when'].append(dict(goal_id=goal['id'],kind='route_not_established'))
        case['request']['allowed_target_refs'].append(target)
    case['request']['observation']=copy.deepcopy(world)
    case['fresh']=copy.deepcopy(world);case['fresh']['day']=2
    for hero in case['fresh']['heroes']:hero['movement']=hero['movement_per_day']
    return case


@unittest.skipUnless(DRIVER.is_file(),'requires built native value driver')
class NativeBackgroundTest(unittest.TestCase):
    def run_case(self,case):
        result=subprocess.run([str(DRIVER)],input=json.dumps(case),text=True,capture_output=True,check=True)
        return json.loads(result.stdout)

    def test_completed_goal_and_reserve_removed_new_town_task_admitted(self):
        case=fixture();case['request']['campaign']['reserves']=[dict(goal_id='old',resources=[0,0,0,0,0,0,50],force_value=0)]
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new'])
        self.assertEqual(result['candidate']['plan']['reserves'],[])
        self.assertEqual(result['candidate']['strategy_update']['decision'],'keep')

    def test_unknown_fog_safety_cannot_scope_or_admit_empty_fronts(self):
        case=heroes_fixture()
        for world in (case['observed'],case['request']['observation'],case['fresh']):
            world['visible_tile_counts']=[3]
        result=self.run_case(case)
        self.assertEqual(result['scope']['actors'],[])
        self.assertEqual(result['scope']['targets'],[])
        self.assertFalse(result['accepted'],result)

    def test_known_native_barrier_remains_conditional_safety_under_fog(self):
        case=heroes_fixture()
        for world in (case['observed'],case['request']['observation'],case['fresh']):
            world['visible_tile_counts']=[3]
            for route in world['forecasts']['routes']:
                route['own_arrivals'][0]['end_turn_exposure']['visible_threats']=[dict(
                    known_land_approach=dict(status='neutral_encounter_required_on_known_land_connections'))]
        result=self.run_case(case)
        self.assertEqual(result['scope']['actors'],['object:0','hero:2'])
        self.assertTrue(result['accepted'],result)

    def test_conditional_movement_scenario_is_not_a_route_safety_bound(self):
        case=heroes_fixture()
        for world in (case['observed'],case['request']['observation'],case['fresh']):
            for route in world['forecasts']['routes']:
                route['own_arrivals'][0]['end_turn_exposure']['visible_threats']=[dict(
                    known_land_approach=dict(status='open_known_land_connection',
                        movement_scenario=dict(turns=3,status='conditional_direct_land_approach')))]
        result=self.run_case(case)
        self.assertEqual(result['scope']['actors'],[])
        self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new'])

    def test_native_guarded_front_can_prepare_a_town_without_inventing_enemy_timing(self):
        case=fixture()
        for world in (case['observed'],case['request']['observation'],case['fresh']):
            world['visible_tile_counts']=[3]
            world['forecasts']['defenses'][0]['unconfirmed_threats']=[dict(assessment='guarded_approach',
                neutral_screen=dict(status='neutral_encounter_required_on_known_land_connections'))]
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)
        self.assertIn('object:1',result['scope']['targets'])

    def test_wrong_day_revision_unknown_identity_and_policy_are_rejected(self):
        for field in ('day','revision','identity','policy'):
            case=fixture()
            if field=='day':case['fresh']['day']=3
            elif field=='revision':case['reply']['intent_revision']=6
            elif field=='identity':case['reply']['identity']['generation']='stale'
            else:case['reply']['plan']['policy']['max_loss_ratio']=.4
            with self.subTest(field=field):self.assertFalse(self.run_case(case)['accepted'])

    def test_independent_town_survives_second_group_losing_ownership(self):
        case=fixture();town=copy.deepcopy(case['observed']['towns'][0]);town['ref']='town:2';town['buildings']=[]
        case['observed']['towns'].append(town);case['request']['observation']=copy.deepcopy(case['observed'])
        case['request']['allowed_target_refs'].append('town:2')
        goal=copy.deepcopy(case['reply']['plan']['goals'][0]);goal.update(id='second',target_ref='town:2')
        case['reply']['plan']['goals'].append(goal)
        case['reply']['reconsider_when'].append(dict(goal_id='second',kind='deadline_missed'))
        result=self.run_case(case)
        self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new'])
        self.assertEqual([g['accepted'] for g in result['groups']],[True,False])

    def test_completed_prerequisite_and_expired_live_goal_require_review(self):
        case=fixture();old=copy.deepcopy(case['request']['campaign']['goals'][0]);old.update(id='later',building_id=2,depends_on=['old'])
        old['complete_when']['value']=2;case['request']['campaign']['goals'].append(old)
        self.assertEqual(self.run_case(case)['reason'],'completed_prerequisite_requires_review')
        case=fixture();case['observed']['towns'][0]['buildings']=[]
        case['request']['campaign']['goals'][0]['deadline_day']=1
        self.assertEqual(self.run_case(case)['reason'],'invalid_carried_commitment')

    def test_calendar_refill_is_allowed_but_changed_army_or_front_is_stale(self):
        case=fixture();self.assertTrue(self.run_case(case)['strategy_fresh'])
        case['fresh']['heroes'][0]['army_value']=1
        self.assertFalse(self.run_case(case)['strategy_fresh'])

    def test_revised_global_course_rejects_changed_basis_atomically(self):
        case=fixture();case['request']['strategic_review']=True
        case['reply']['alternatives']=[dict(approach='economy',benefit='Build',cost='Funds',uncertainty='Enemy'),dict(approach='offense',benefit='Conquest',cost='Army',uncertainty='Route')]
        case['reply']['strategy_update'].update(decision='revise',selected={k:v for k,v in case['request']['strategic_intent'].items() if k in ('objective','selection_reason','assumptions','milestones','reconsider_when')},change_reason='Observed stall')
        case['reply']['operation_focus']['revision']=8;case['fresh']['heroes'][0]['army_value']=1
        result=self.run_case(case);self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'changed_strategic_basis')

    def test_two_heroes_and_town_keep_independent_tasks_after_local_threat(self):
        case=heroes_fixture()
        case['fresh']['forecasts']['routes'][1]['own_arrivals'][0]['end_turn_exposure']['status']='unknown'
        result=self.run_case(case);self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new','resource-one'])
        self.assertEqual([g['accepted'] for g in result['groups']],[True,True,False])

    def test_dependency_group_is_discarded_together_without_losing_town(self):
        case=heroes_fixture()
        case['reply']['plan']['goals'][2]['depends_on']=['resource-one']
        case['fresh']['forecasts']['routes'][0]['own_arrivals'][0]['end_turn_exposure']['status']='unknown'
        result=self.run_case(case);self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new'])
        self.assertEqual([g['accepted'] for g in result['groups']],[True,False])

    def test_unfunded_second_group_cannot_take_first_groups_treasury(self):
        case=heroes_fixture();case['fresh']['resources'][6]=100
        case['reply']['plan']['reserves']=[dict(goal_id='resource-one',resources=[0,0,0,0,0,0,80],force_value=0),
            dict(goal_id='resource-two',resources=[0,0,0,0,0,0,80],force_value=0)]
        result=self.run_case(case);self.assertTrue(result['accepted'],result)
        self.assertEqual([g['id'] for g in result['candidate']['plan']['goals']],['new','resource-one'])
        self.assertEqual(result['candidate']['plan']['reserves'][0]['resources'][6],80)

    def test_malformed_dependency_and_forged_completion_never_bypass_raw_validation(self):
        for mutation in ('dependency','completed','binding'):
            case=fixture()
            if mutation=='dependency':case['reply']['plan']['goals'][0]['depends_on']=['missing']
            elif mutation=='completed':case['reply']['plan']['goals'][0]['status']='completed'
            else:case['reply']['operation_focus']['bindings'][0]['milestone_id']='missing'
            with self.subTest(mutation=mutation):self.assertFalse(self.run_case(case)['accepted'])

    def test_global_keep_and_revise_are_final_when_calendar_basis_is_fresh(self):
        for decision in ('keep','revise'):
            case=fixture();case['request']['strategic_review']=True
            case['reply']['alternatives']=[dict(approach='economy',benefit='Build',cost='Funds',uncertainty='Enemy'),dict(approach='offense',benefit='Conquest',cost='Army',uncertainty='Route')]
            if decision=='revise':
                case['reply']['strategy_update'].update(decision='revise',selected={k:v for k,v in case['request']['strategic_intent'].items() if k in ('objective','selection_reason','assumptions','milestones','reconsider_when')},change_reason='Observed stall')
                case['reply']['operation_focus']['revision']=8
            result=self.run_case(case)
            with self.subTest(decision=decision):
                self.assertTrue(result['accepted'],result)
                self.assertEqual(result['candidate']['strategy_update']['decision'],decision)
