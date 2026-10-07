"""Native proposal generation is bounded before expensive route quotations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
DRIVER=Path(os.environ.get('STRATEGIC_CANDIDATES_DRIVER',ROOT/'.build/nk3-ranking-contract-drivers/strategic-candidates-driver'))


@unittest.skipUnless(DRIVER.is_file(),'build strategic-candidates-driver')
class StrategicCandidatesTest(unittest.TestCase):
    def call(self,data):
        result=subprocess.run([str(DRIVER)],input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def fixture(self,count=40):
        hero={'ref':'hero','position':[0,0,0],'sight_radius':5,'army_value':10000,'minimum_retained_army_value':100}
        world={'day':10,'player':1,'heroes':[hero],'towns':[{'ref':'home','position':[0,1,0]}],
            'visible_objects':[],'objects':[],'frontiers':[],'observed_frontiers':['old-frontier'],
            'frontier_options':[],'scouting_options':[], 'forecasts':{'routes':[],
                'threats':[{'town_ref':'home','source_ref':'enemy','uncertainty':'unknown route'}],
                'defenses':[{'town_ref':'home','status':'insufficient_current_force'}]},
            'goal_statuses':{},'goal_feedback':[],'resources':[0,0,0,0,0,0,5000]}
        coverage=[]
        for i in range(count):
            position=[i+1,1,i%2];ref='tile:'+json.dumps(position)
            route={'hero_ref':'hero','day':11,'movement_cost':1+i/100,
                'army_value':10000,'army_loss_estimate':0,'fighting_strength_estimate':10000}
            world['frontiers'].append(ref)
            world['frontier_options'].append({'ref':ref,'position':position,'own_arrivals':[route]})
            world['scouting_options'].append({'ref':ref,'position':position,'own_arrivals':[route]})
            coverage.append({'position':position,'cells':[f'area-{i//3}-{j}' for j in range(20)]})
        return {'world':world,'plan':{'goals':[],'policy':{'max_loss_ratio':.25,'critical_towns':['home']}},
            'coverage':coverage,'memory':{'known_objects':[]}}

    def test_mod_scoped_income_configuration_is_plain_json_on_the_model_wire(self):
        data=self.fixture(0)
        data['configured_income_bonus']={'gold':200,'wood':100,'ore':100,'crystal':200,'gems':200,'sulfur':200,'mercury':200}
        result=self.call(data)
        self.assertEqual(result['economic_observation']['weekly_bonus_percent'],data['configured_income_bonus'])

    def test_repeated_viewpoints_become_few_distinct_directions_before_quoting(self):
        data=self.fixture(1000);result=self.call(data)
        options=result['scouts']['scouting']
        self.assertLessEqual(len(options),6)
        self.assertLessEqual(result['scouts']['probes'],18)
        positions=[o['position'] for o in options]
        self.assertEqual({p[2] for p in positions},{0,1})
        footprints={tuple(v['position']):set(v['cells']) for v in data['coverage']}
        unions=set()
        for p in positions:
            self.assertTrue(footprints[tuple(p)]-unions,'selected overlapping center adds no information')
            unions.update(footprints[tuple(p)])
        self.assertEqual(result['view']['forecasts']['threats'],data['world']['forecasts']['threats'])
        self.assertEqual(result['view']['towns'],data['world']['towns'])

    def test_failed_best_viewpoint_gets_a_supported_replacement(self):
        data=self.fixture();data['world']['scouting_options'][0]['own_arrivals']=[]
        result=self.call(data)
        self.assertGreater(result['scouts']['probes'],len(result['scouts']['scouting']))
        self.assertTrue(result['scouts']['scouting'])
        self.assertNotIn(data['world']['scouting_options'][0]['ref'],[o['ref'] for o in result['scouts']['scouting']])

    def test_unreachable_level_does_not_starve_reachable_exploration(self):
        data=self.fixture(100)
        for option in data['world']['scouting_options']:
            if option['position'][2]==1:option['own_arrivals']=[]
        result=self.call(data)
        self.assertGreaterEqual(len(result['scouts']['scouting']),4)
        self.assertEqual({o['position'][2] for o in result['scouts']['scouting']},{0})
        self.assertLessEqual(result['scouts']['probes'],18)

    def test_candidate_selection_is_independent_of_map_iteration_order(self):
        data=self.fixture(100);reverse=copy.deepcopy(data)
        reverse['world']['frontier_options'].reverse()
        self.assertEqual(self.call(data)['scouts'],self.call(reverse)['scouts'])

    def test_required_goals_and_defense_survive_optional_quotas(self):
        data=self.fixture();refs=[o['ref'] for o in data['world']['frontier_options'][-8:]]
        data['plan']['goals']=[{'kind':'scout_area','target_ref':ref,'actor_ref':'hero'} for ref in refs]
        result=self.call(data)
        self.assertTrue(set(refs)<={o['ref'] for o in result['scouts']['scouting']})
        self.assertEqual(result['view']['forecasts']['defenses'],data['world']['forecasts']['defenses'])
        self.assertEqual(result['view']['resources'],data['world']['resources'])

    def test_object_classes_do_not_crowd_out_each_other_or_required_target(self):
        data=self.fixture(0)
        for kind in ('town','hero','mine','subterranean_gate','obelisk'):
            for i in range(100):
                ref=f'{kind}-{i}';pos=[i+1,2,0]
                obj={'ref':ref,'kind':kind,'owner':0,'position':pos,'visible':True,'visited':False}
                data['world']['visible_objects'].append(obj);data['world']['objects'].append(obj)
                data['memory']['known_objects'].append(obj)
                data['world']['forecasts']['routes'].append({'target_ref':ref,'own_arrivals':[
                    {'hero_ref':'hero','day':11,'movement_cost':1,'army_loss_estimate':0,'army_value':10000}]})
        data['plan']['goals']=[{'kind':'capture_target','actor_ref':'hero','target_ref':'mine-99'}]
        result=self.call(data);refs={r['target_ref'] for r in result['targets']['routes']}
        self.assertIn('mine-99',refs)
        for kind in ('town','hero','mine','subterranean_gate','obelisk'):
            self.assertGreaterEqual(sum(ref.startswith(kind+'-') for ref in refs),4)
        self.assertLessEqual(result['targets']['probes'],60)
        self.assertLess(len(result['view']['objects']),30)
        self.assertEqual(len([o for o in result['view']['visible_objects'] if o['kind']=='hero']),100)

    def test_risky_nearby_targets_do_not_use_up_the_usable_target_quota(self):
        data=self.fixture(0)
        for i in range(10):
            obj={'ref':f'mine-{i}','kind':'mine','owner':0,'position':[i+1,1,0]}
            data['world']['visible_objects'].append(obj)
            data['world']['objects'].append(obj)
            data['world']['forecasts']['routes'].append({'target_ref':obj['ref'],'own_arrivals':[
                {'hero_ref':'hero','day':11,'movement_cost':1,'army_value':10000,
                 'army_loss_estimate':5000 if i<5 else 0}]})
        result=self.call(data);refs={r['target_ref'] for r in result['targets']['routes']}
        self.assertEqual({ref for ref in refs if ref.startswith('mine-')},{'mine-0','mine-5','mine-6','mine-7','mine-8'})

    def test_fast_lossy_and_slow_safe_routes_are_both_preserved(self):
        data=self.fixture(1);route=data['world']['scouting_options'][0]['own_arrivals'][0]
        fast={**route,'day':10,'movement_cost':.5,'army_loss_estimate':500}
        data['world']['scouting_options'][0]['own_arrivals']=[route,fast]
        result=self.call(data);arrivals=result['scouts']['scouting'][0]['own_arrivals']
        self.assertEqual({r['army_loss_estimate'] for r in arrivals},{0,500})

    def test_xl_size_does_not_increase_route_probe_budget(self):
        small=self.call(self.fixture(100));large=self.call(self.fixture(5000))
        self.assertLessEqual(large['scouts']['probes'],18)
        self.assertLessEqual(len(large['scouts']['scouting']),6)
        self.assertLess(len(json.dumps(large['view'])),20000)

    def add_objects(self,data,count=12):
        for i in range(count):
            item={'ref':f'mine-{i}','kind':'mine','owner':0,'position':[i+1,2,0],
                  'visible':True,'production_per_day':2,'resource_type':'wood'}
            data['world']['visible_objects'].append(item)
            data['world']['objects'].append(item)
            data['world']['forecasts']['routes'].append({'target_ref':item['ref'],'own_arrivals':[
                {'hero_ref':'hero','day':11,'movement_cost':1,'army_value':10000,'army_loss_estimate':0}]})
        data['world']['map_size']=[144,144,2]

    def test_initial_overview_includes_far_visible_target_beyond_route_quota(self):
        data=self.fixture(0);self.add_objects(data)
        result=self.call(data)
        self.assertNotIn('mine-11',{o['ref'] for o in result['view']['objects']})
        self.assertIn('mine-11',{o['ref'] for o in result['overview']['objects']})
        self.assertTrue(result['overview']['coverage']['complete'])
        self.assertEqual(result['overview']['map_size'],[144,144,2])

    def test_milestone_pins_target_and_actor_without_creating_hidden_objects(self):
        data=self.fixture(0);self.add_objects(data)
        data['intent']={'milestones':[{'id':'capture','complete_when':{'kind':'target_owned',
            'target_ref':'mine-11','actor_ref':'hero'}}],'progress':{}}
        result=self.call(data)
        self.assertIn('mine-11',{o['ref'] for o in result['view']['objects']})
        data['world']['visible_objects']=[o for o in data['world']['visible_objects'] if o['ref']!='mine-11']
        data['world']['objects']=[o for o in data['world']['objects'] if o['ref']!='mine-11']
        result=self.call(data)
        self.assertNotIn('mine-11',{o['ref'] for o in result['overview']['objects']})
        self.assertNotIn('mine-11',{o['ref'] for o in result['view']['objects']})

    def test_compact_overview_keeps_completed_milestone_current_state(self):
        data=self.fixture(0);self.add_objects(data)
        data['compact']=True
        data['intent']={'milestones':[{'id':'capture','complete_when':{'kind':'target_owned','target_ref':'mine-11'}}],
                        'progress':{'capture':{'state':'completed'}}}
        result=self.call(data)
        self.assertIn('mine-11',{o['ref'] for o in result['overview']['objects']})
        self.assertNotIn('mine-11',{o['ref'] for o in result['view']['objects']})
        self.assertLess(len(result['overview']['objects']),result['overview']['coverage']['known_objects'])

    def test_last_seen_object_keeps_observation_age_and_is_not_currently_visible(self):
        data=self.fixture(0);self.add_objects(data)
        data['world']['visible_objects']=[]
        for object in data['world']['objects']:
            object.update(stale=True,last_seen_day=3,not_seen_at_last_position=True)
        result=self.call(data)['overview']
        stale=next(o for o in result['objects'] if o['ref']=='mine-11')
        self.assertFalse(stale['visible'])
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['last_seen_day'],3)
        self.assertTrue(stale['not_seen_at_last_position'])

    def test_overview_cap_is_deterministic_and_reports_omission(self):
        data=self.fixture(0);self.add_objects(data,500)
        reverse=copy.deepcopy(data)
        reverse['world']['visible_objects'].reverse();reverse['world']['objects'].reverse()
        result=self.call(data)['overview']
        self.assertEqual(result,self.call(reverse)['overview'])
        self.assertLessEqual(len(result['objects']),384)
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['coverage']['shown_objects']+result['coverage']['omitted_objects'],502)
        self.assertIn('home',{o['ref'] for o in result['objects']})

    def test_whole_request_cap_preserves_intent_and_cleans_removed_evidence(self):
        data=self.fixture(0)
        intent={'objective':'retain course','milestones':[]}
        data['request']={'observation':{'map_overview':{'objects':[
            {'ref':'kept','kind':'town','effects':'small'},
            {'ref':'removed','kind':'artifact','effects':' \" большой текст '*10000}],
            'coverage':{'known_objects':2}}},'strategic_intent':intent,
            'evidence_refs':['target:kept','target:removed']}
        data['max_bytes']=1000
        result=self.call(data)
        self.assertTrue(result['request_fits'])
        self.assertLessEqual(result['request_bytes'],1000)
        self.assertEqual(result['bounded_request']['strategic_intent'],intent)
        self.assertEqual(result['bounded_request']['evidence_refs'],['target:kept'])
        self.assertEqual(result['bounded_request']['observation']['map_overview']['coverage']['omitted_objects'],1)
        data['request']['strategic_intent']['objective']='x'*2000
        result=self.call(data)
        self.assertFalse(result['request_fits'])
        self.assertEqual(result['bounded_request']['strategic_intent'],data['request']['strategic_intent'])

    def test_default_wire_cap_counts_utf8_and_escaping_in_entire_request(self):
        data=self.fixture(0)
        data['request']={'strategic_intent':{'objective':'a'*200000},'observation':{'map_overview':{
            'objects':[{'ref':'first','effects':'\\" текст '*20000},
                       {'ref':'last','effects':'\\" текст '*20000}],
            'coverage':{'known_objects':2}}},'evidence_refs':['target:first','target:last']}
        result=self.call(data)
        self.assertTrue(result['request_fits'])
        self.assertLessEqual(result['request_bytes'],512*1024)
        self.assertEqual(len(result['bounded_request']['observation']['map_overview']['objects']),1)
        expected=json.dumps(result['bounded_request'],ensure_ascii=False,separators=(',',':')).encode('utf-8')
        self.assertEqual(result['request_bytes'],len(expected))

    def test_ai_bonus_matches_native_integer_distribution_custom_week_and_cap(self):
        data=self.fixture(0)
        cases=[{'base':3,'bonus':50,'day_of_week':day,'days_in_week':5,'cap':100000} for day in range(1,6)]
        cases += [{'base':137,'bonus':25,'day_of_week':day,'days_in_week':7,'cap':100000} for day in range(1,8)]
        cases += [{'base':999,'bonus':100,'day_of_week':7,'days_in_week':7,'cap':1000},
                  {'base':10,'bonus':0,'day_of_week':7,'days_in_week':7,'cap':1000}]
        data['income_cases']=cases
        values=self.call(data)['effective_incomes']
        self.assertEqual(values,[min(c['cap'],c['base']+(c['base']*c['bonus']*c['day_of_week']//c['days_in_week']//100)
            -(c['base']*c['bonus']*(c['day_of_week']-1)//c['days_in_week']//100)) for c in cases])
        self.assertEqual(sum(values[:5]),16)


if __name__=='__main__':unittest.main()
