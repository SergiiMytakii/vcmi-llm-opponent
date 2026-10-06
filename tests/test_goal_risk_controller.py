"""Combat risk grants remain local while legacy plans keep the ordinary ceiling."""
import copy
import unittest
from controller.native_strategy import reply_schema, validate_reply
from test_nullkiller3_controller import strategic_request
from test_helper_hiring_controller import reply


class GoalRiskControllerTest(unittest.TestCase):
    def test_grant_is_explicit_bounded_combat_only_and_global_unchanged(self):
        request = strategic_request()
        request['observation']['enemy_players'] = [1]
        request['observation']['objects'].append(dict(ref='enemy',kind='hero',owner=1,visible=True))
        goal = dict(id='decisive',kind='intercept_hero',actor_ref='object:0',target_ref='enemy',deadline_day=3,
                    priority=90,building_id=-1,min_army_value=5000,depends_on=[],required_capabilities=['land'],
                    complete_when=dict(kind='enemy_engaged',value=0))
        answer = reply(request,goal)
        validate_reply(request,answer)  # Legacy omitted field.
        answer['plan']['goals'][0]['risk'] = None
        validate_reply(request,answer)
        answer['plan']['goals'][0]['risk'] = dict(max_loss_ratio=.7,reason='Remove the main force before securing its remaining bases')
        validate_reply(request,answer)
        self.assertEqual(answer['plan']['policy']['max_loss_ratio'],.25)
        for value in [-.1,1.01]:
            bad=copy.deepcopy(answer);bad['plan']['goals'][0]['risk']['max_loss_ratio']=value
            with self.assertRaises(ValueError): validate_reply(request,bad)
        bad=copy.deepcopy(answer);bad['plan']['goals'][0]['risk']['reason']=''
        with self.assertRaises(ValueError): validate_reply(request,bad)
        bad=copy.deepcopy(answer);bad['plan']['policy']['max_loss_ratio']=.7
        with self.assertRaises(ValueError): validate_reply(request,bad)
        bad=copy.deepcopy(answer);bad['plan']['goals'][0].update(kind='scout_frontier',target_ref='tile:frontier',
                                                              complete_when=dict(kind='frontier_observed',value=0))
        with self.assertRaises(ValueError): validate_reply(request,bad)
        schema=reply_schema(request)
        variants=schema['properties']['plan']['anyOf'][1]['properties']['goals']['items']['anyOf']
        self.assertTrue(all('risk' in variant['required'] for variant in variants))

    def test_legacy_completed_interception_accepts_explicit_null_without_changing_identity(self):
        request=strategic_request()
        request['observation']['enemy_players']=[1]
        request['observation']['objects'].append(dict(ref='enemy',kind='hero',owner=1,visible=False))
        goal=dict(id='decisive',kind='intercept_hero',actor_ref='object:0',target_ref='enemy',deadline_day=3,
                  priority=90,building_id=-1,min_army_value=5000,depends_on=[],required_capabilities=['land'],
                  complete_when=dict(kind='enemy_engaged',value=0))
        request['campaign']=reply(request,goal)['plan']
        request['observation']['goal_statuses']={'decisive':{'state':'completed'}}
        request['observation']['confirmed_interceptions']=[dict(goal=copy.deepcopy(goal),day=1,won=True)]
        answer=reply(request,copy.deepcopy(goal));answer['plan']['revision']=2
        answer['plan']['goals'][0]['risk']=None
        validate_reply(request,answer)
        self.assertNotIn('risk',request['observation']['confirmed_interceptions'][0]['goal'])
        for key,value in [('min_army_value',4999),('risk',dict(max_loss_ratio=.7,reason='Different risk operation'))]:
            bad=copy.deepcopy(answer);bad['plan']['goals'][0][key]=value
            with self.assertRaises(ValueError):validate_reply(request,bad)
