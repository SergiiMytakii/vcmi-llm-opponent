"""Intermediate access options delivered through the native preparation seam."""
import json
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('INTERMEDIATE_PREPARATION_DRIVER'),
                     'requires the intermediate-preparation native driver')
class IntermediatePreparation(unittest.TestCase):
    def request(self):
        world = dict(day=60, player=1, resources=[0]*7, capabilities=['land'],
                     heroes=[dict(ref='main',army_value=10000,movement=1500),
                             dict(ref='helper',army_value=1000,movement=1500)],
                     towns=[dict(ref='home',owner=1)],
                     visible_objects=[dict(ref='tent',kind='keymaster_tent',visible=True,visited=False,
                                           key_owned=False,key_color=7,matching_visible_refs=['border']),
                                      dict(ref='portal',kind='portal',visible=True,position=[4,5,0]),
                                      dict(ref='border',kind='border_gate',visible=True,visited=False,
                                           key_owned=False,eligible_hero_refs=[]),
                                      dict(ref='used',kind='keymaster_tent',visible=True,visited=True,key_owned=True)],
                     forecasts=dict(routes=[dict(target_ref='tent',own_arrivals=[
                         dict(hero_ref='main',army_value=10000,army_loss_estimate=400,day=63),
                         dict(hero_ref='helper',army_value=1000,army_loss_estimate=300,day=62)]),
                         dict(target_ref='portal',own_arrivals=[dict(hero_ref='main',army_value=10000,army_loss_estimate=800,day=64)])]))
        world['observed_passages']=[{'from':[4,5,0],'to':[8,9,1],'bidirectional':False}]
        goal=dict(id='hold',kind='preserve_force',actor_ref='main',target_ref='home',deadline_day=63,
                  priority=100,building_id=-1,min_army_value=8000,depends_on=[],required_capabilities=['land'],
                  complete_when=dict(kind='force_preserved_until',value=63))
        plan=dict(version=3,revision=1,approach='defense',horizon_days=3,goals=[goal],reserves=[],
                  policy=dict(max_loss_ratio=.15,allow_route_repair=True,allow_helper_replacement=False,critical_towns=[]))
        return dict(campaign=plan,observation=world)

    def test_access_options_include_each_actor_and_preserve_uncertainty(self):
        request=self.request()
        result=subprocess.run([os.environ['INTERMEDIATE_PREPARATION_DRIVER']],input=json.dumps(request),text=True,capture_output=True,check=True)
        options={o['target_ref']:o for o in json.loads(result.stdout)['intermediate_options']}
        self.assertEqual(set(options),{'tent','portal'})
        self.assertEqual(options['tent']['matching_visible_refs'],['border'])
        actors={a['actor_ref']:a for a in options['tent']['actor_options']}
        self.assertTrue(actors['main']['supported'])
        self.assertEqual(actors['main']['assigned_routes'][0]['day'],63)
        self.assertFalse(actors['helper']['supported'])
        self.assertIn('loss_exceeds_policy',actors['helper']['assigned_routes'][0]['issues'])
        self.assertIn('unknown',options['portal']['onward_access'])
        self.assertEqual(options['portal']['observed_connections'][0]['to'],[8,9,1])
        self.assertFalse(options['portal']['observed_connections'][0]['bidirectional'])

    def test_water_access_keeps_construction_and_onward_admission_conditional(self):
        request=self.request();world=request['observation']
        world['visible_objects'] += [dict(ref='boat',kind='boat',visible=True)]
        world['forecasts']['routes'] += [dict(target_ref='boat',own_arrivals=[
            dict(hero_ref='helper',army_value=1000,army_loss_estimate=0,day=61)])]
        world['shipyards']=[dict(ref='yard',boat_position=[4,5,0],cost=[10,0,0,0,0,0,1000])]
        result=subprocess.run([os.environ['INTERMEDIATE_PREPARATION_DRIVER']],input=json.dumps(request),text=True,capture_output=True,check=True)
        options={o['target_ref']:o for o in json.loads(result.stdout)['water_options']}
        self.assertEqual(set(options),{'boat','yard'})
        self.assertEqual(options['boat']['actor_options'][0]['actor_ref'],'helper')
        self.assertIn('native embark',options['boat']['actor_options'][0]['action_admission'])
        self.assertEqual(options['yard']['construction_quote']['cost'],[10,0,0,0,0,0,1000])
        self.assertIn('funds',options['yard']['action_admission'])
        self.assertIn('unknown',options['yard']['onward_access'])

    def test_candidate_screening_quotes_boats_and_shipyards(self):
        request=self.request();world=request['observation']
        world['heroes'][0]['position']=[0,0,0];world['heroes'][1]['position']=[1,0,0]
        world['visible_objects']=[dict(ref='boat',kind='boat',visible=True,owner=-1,position=[2,0,0]),
                                  dict(ref='yard',kind='shipyard',visible=True,owner=1,position=[3,0,0])]
        world['forecasts']['routes']=[dict(target_ref=ref,own_arrivals=[
            dict(hero_ref='helper',army_value=1000,army_loss_estimate=0,day=61)]) for ref in ('boat','yard')]
        result=subprocess.run([os.environ['INTERMEDIATE_PREPARATION_DRIVER'],'--candidates'],
                              input=json.dumps(request),text=True,capture_output=True,check=True)
        routes={r['target_ref']:r for r in json.loads(result.stdout)['routes']}
        self.assertTrue(routes['boat']['own_arrivals'])
        self.assertTrue(routes['yard']['own_arrivals'])
