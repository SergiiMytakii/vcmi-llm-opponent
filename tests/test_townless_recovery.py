"""Townless survival constrains the real native strategic-decision boundary."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from fixtures.strategic_intent import with_intent
ROOT=Path(__file__).resolve().parents[1]
DRIVER=ROOT/'.build/background-values/nullkiller3-campaign-driver'


def fixture():
    world=dict(day=42,player=0,resources=[0,0,0,0,0,0,1000],capabilities=['land'],
        towns=[],heroes=[dict(ref='main',id=0,army_value=1000)],frontiers=[],enemy_players=[1],
        objects=[dict(ref='town',kind='town',owner=1,visible=True,position=[3,3,0])],
        victory=dict(townless_defeat=dict(status='public_rule',turns=7,own_elapsed_turns=6)),
        forecasts=dict(routes=[dict(target_ref='town',own_arrivals=[dict(hero_ref='main',day=42,
            army_value=1000,army_loss_estimate=0)])]))
    goal=dict(id='recapture',kind='capture_target',actor_ref='main',target_ref='town',deadline_day=42,
        priority=100,building_id=-1,min_army_value=1000,depends_on=[],required_capabilities=['land'],
        complete_when=dict(kind='target_owned',value=0),risk=None)
    plan=dict(version=3,revision=1,approach='expansion',horizon_days=3,goals=[goal],reserves=[],
        policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
    request=dict(protocol=2,request_id='townless',identity=dict(instance='proof',generation='proof',player=0,day=42,revision=0),
        observation=copy.deepcopy(world),campaign=None,strategic_intent=None,evidence_refs=['observation:victory'],
        memory={},signals=[dict(question='townless_survival',facts='last day',critical=True)],budget=dict(wait_ms=80000,tokens=120000))
    reply=dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
        reason='Return a town before elimination',evidence_refs=request['evidence_refs'],victory_method='Conquest',
        assignments=[dict(hero_ref='main',role='main')],
        alternatives=[dict(approach='expansion',benefit='Survive',cost='Force',uncertainty='Route'),
                      dict(approach='offense',benefit='Base denial',cost='Force',uncertainty='Enemy')],
        reconsider_when=[dict(goal_id='recapture',kind='deadline_missed')],plan=plan,
        usage=dict(known=True,input_tokens=0,output_tokens=0))
    return dict(world=world,request=request,reply=with_intent(request,reply))


@unittest.skipUnless(DRIVER.is_file(),'requires native decision driver')
class TownlessRecoveryTest(unittest.TestCase):
    def call(self,case):
        result=subprocess.run([str(DRIVER),'--decision'],input=json.dumps(case),text=True,capture_output=True,check=True)
        return json.loads(result.stdout)

    def test_day_42_cannot_postpone_city_to_day_43(self):
        case=fixture();case['reply']['plan']['goals'][0]['deadline_day']=43
        result=self.call(case)
        self.assertFalse(result['accepted'],result)
        self.assertEqual(result['reason'],'townless_goal_after_defeat')

    def test_city_requires_supported_arrival_before_the_last_turn_ends(self):
        for mutation in ('missing_route','late_route','too_weak','excess_loss'):
            case=fixture();route=case['world']['forecasts']['routes'][0]['own_arrivals'][0]
            if mutation=='missing_route':case['world']['forecasts']['routes']=[]
            elif mutation=='late_route':route['day']=43
            elif mutation=='too_weak':route['army_value']=999
            else:route['army_loss_estimate']=201
            with self.subTest(mutation=mutation):
                result=self.call(case)
                self.assertFalse(result['accepted'],result)
                self.assertEqual(result['reason'],'townless_recovery_not_supported')

    def test_supported_city_on_last_day_is_accepted(self):
        self.assertTrue(self.call(fixture())['accepted'])

    def test_unknown_counter_unknown_rule_and_owned_town_do_not_invent_limits(self):
        for mutation in ('unknown_counter','unknown_rule','owned_town'):
            case=fixture();case['reply']['plan']['goals'][0]['deadline_day']=43
            if mutation=='unknown_counter':case['world']['victory']['townless_defeat']['own_elapsed_turns']=None
            elif mutation=='unknown_rule':case['world']['victory']['townless_defeat']['status']='unsupported_or_unknown'
            else:case['world']['towns']=[dict(ref='home',buildings=[])]
            with self.subTest(mutation=mutation):self.assertTrue(self.call(case)['accepted'])

    def test_map_specific_period_is_used_instead_of_fixed_seven(self):
        case=fixture();case['world']['victory']['townless_defeat'].update(turns=5,own_elapsed_turns=3)
        case['reply']['plan']['goals'][0]['deadline_day']=43
        self.assertTrue(self.call(case)['accepted'])
        case['reply']['plan']['goals'][0]['deadline_day']=44
        self.assertEqual(self.call(case)['reason'],'townless_goal_after_defeat')

    def test_retaining_old_saved_late_plan_cannot_bypass_survival(self):
        case=fixture();old=copy.deepcopy(case['reply']['plan']);old['goals'][0]['deadline_day']=43
        case['current']=old;case['request']['campaign']=old
        case['reply'].update(decision='retain',plan=None)
        self.assertEqual(self.call(case)['reason'],'townless_goal_after_defeat')

    def test_unconfirmed_dependency_cannot_claim_a_ready_return(self):
        case=fixture();mine=dict(ref='mine',kind='resource',owner=-2,visible=True,position=[2,2,0])
        case['world']['objects'].append(mine)
        prepare=copy.deepcopy(case['reply']['plan']['goals'][0]);prepare.update(id='mine_first',kind='secure_resource',target_ref='mine',complete_when=dict(kind='reserve_at_least',value=1000))
        case['reply']['plan']['goals'].insert(0,prepare)
        case['reply']['plan']['goals'][1]['depends_on']=['mine_first']
        case['world']['forecasts']['routes'].append(dict(target_ref='mine',own_arrivals=[dict(hero_ref='main',day=42,army_value=1000,army_loss_estimate=0)]))
        case['reply']=with_intent(case['request'],case['reply'])
        self.assertEqual(self.call(case)['reason'],'townless_recovery_not_supported')
        case['world']['confirmed_resource_pickups']=['mine']
        self.assertTrue(self.call(case)['accepted'])


class TownlessSchemaTest(unittest.TestCase):
    def test_malformed_goal_id_remains_a_schema_rejection(self):
        from controller.native_strategy import validate_reply
        case=fixture();case['reply']['plan']['goals'][0]['id']=[]
        with self.assertRaises(ValueError):validate_reply(case['request'],case['reply'],wire=True)

    def test_schema_caps_new_goals_at_the_last_capture_day(self):
        from controller.native_strategy import reply_schema,validate_reply
        case=fixture();request=case['request'];reply=case['reply']
        validate_reply(request,reply,wire=True)
        reply['plan']['goals'][0]['deadline_day']=43
        with self.assertRaises(ValueError):validate_reply(request,reply,wire=True)
        schema=reply_schema(request)
        for branch in schema['properties']['plan']['anyOf']:
            if branch.get('type')=='null':continue
            for variant in branch['properties']['goals']['items']['anyOf']:
                if 'enum' not in variant:
                    self.assertEqual(variant['properties']['deadline_day']['maximum'],42)


@unittest.skipUnless(__import__('os').environ.get('VCMI_NK3_BACKGROUND_CONFIG'),'requires isolated native runtime')
class NativeTownlessRecoveryTest(unittest.TestCase):
    def test_late_resource_plan_rejected_city_captured_and_normal_work_resumes(self):
        self.run_case('late')

    def test_model_selected_recovery_is_not_replaced_by_nearer_native_town(self):
        self.run_case('choice')

    def run_case(self,case):
        import os,re,shutil,sys,tempfile,time,zipfile
        from scripts.create_scenario import scenario,template
        from playtesting.runs import copy_snapshot_file
        from test_background_integration import records
        config=json.loads(Path(os.environ['VCMI_NK3_BACKGROUND_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='native-townless-',dir=ROOT/'.build/background-proof'))
        fixture_path=output/'fixture'
        shutil.copytree(config['profile_template'],fixture_path,copy_function=copy_snapshot_file)
        data=scenario();objects=data['objects.json']
        for name in list(objects):
            if objects[name]['type'] in ('monster','mine','resource') or (objects[name]['type']=='hero' and objects[name]['options']['owner']=='blue'):del objects[name]
        hero=next(o for o in objects.values() if o['type']=='hero')
        hero['options']['army']=[dict(type='core:archer',amount=100)]
        town=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
        town.update(x=24,y=22);town['options'].pop('owner')
        data['header.json']['players']['red'].pop('mainTown',None)
        data['header.json']['players']['blue']['heroes']={}
        data['header.json']['players']['blue'].pop('mainHero',None)
        for name,x,y,subtype,amount in [('near_gold',7,11,'gold',1000),('after_city',24,23,'wood',10)]:
            objects[name]=dict(type='resource',subtype=subtype,x=x,y=y,l=0,
                template=template('AVTGOLD0' if subtype=='gold' else 'AVTWOOD0',['VA']),options=dict(amount=amount))
        maps=fixture_path/'Library/Application Support/vcmi/Maps'
        with zipfile.ZipFile(maps/'TownlessProof.vmap','x') as archive:
            for name,value in data.items():archive.writestr(name,json.dumps(value))
        controller=ROOT/'tests/fixtures/townless_recovery.py'
        config.update(profile_template=str(fixture_path),map_resource='Maps/TownlessProof.vmap',
            players=dict(red='Nullkiller3',blue='Nullkiller2'),controller=[sys.executable,str(controller)],
            controller_sources=[str(controller),str(ROOT/'tests/fixtures/strategic_intent.py')],
            case_id='townless-recovery',max_seconds=60,experience_mode='off',headless=True,review_interval_days=0)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,VCMI_AI_OPEN_MAP='1',NK3_TOWNLESS_CASE=case,NK3_TOWNLESS_MARKER=str(run/'profile'/'.townless-bad-sent'))
        with (output/'driver.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                end=time.monotonic()+62
                while process.poll() is None and time.monotonic()<end:
                    history=records(run/'runtime.log','NK3_EXECUTION')
                    returned=[t for t in history if t.get('action',{}).get('before',{}).get('towns')==[] and t.get('action',{}).get('after',{}).get('towns')]
                    if case=='choice' and returned:break
                    if returned and any(t.get('sequence',0)>returned[0]['sequence'] and t.get('action',{}).get('before',{}).get('towns')
                        and t.get('action',{}).get('resource_delta',[0]*7)[0]>0 for t in history):break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True);process.wait(timeout=15)
        print('Native townless proof:',case,output,flush=True)
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        invalid=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/result.json')]
        if case=='late':self.assertTrue(any(t.get('status')=='invalid_reply' and t.get('error')=='townless_goal_after_defeat' for t in invalid),str(output))
        history=records(run/'runtime.log','NK3_EXECUTION')
        returned=[t for t in history if t.get('action',{}).get('before',{}).get('towns')==[] and t.get('action',{}).get('after',{}).get('towns')]
        self.assertTrue(returned,str(output));capture=returned[0]
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        countdowns=[r['observation']['victory']['townless_defeat'] for r in requests if r['identity']['day']==capture['day'] and not r['observation']['towns']]
        self.assertTrue(countdowns,str(output));counter=countdowns[-1]
        self.assertLess(counter['own_elapsed_turns'],counter['turns'])
        if case=='choice':
            selected=[]
            for path in (run/'decisions').glob('*/stdout.bin'):
                raw=path.read_text()
                if not raw.strip():continue
                reply=json.loads(raw)
                if reply.get('identity',{}).get('day')==capture['day'] and reply.get('plan'):
                    selected += [g['target_ref'] for g in reply['plan']['goals'] if g['kind']=='capture_target']
            self.assertTrue(selected,str(output))
            self.assertEqual(capture['action']['after']['towns'][0]['ref'],selected[0],str(output))
            return
        self.assertTrue(any(t.get('sequence',0)>capture['sequence'] and t.get('action',{}).get('before',{}).get('towns')
            and t.get('action',{}).get('resource_delta',[0]*7)[0]>0 for t in history),str(output))
        self.assertFalse(any(t['day']>=2 and t.get('sequence',0)<capture['sequence'] and t.get('action',{}).get('goal',{}).get('kind')=='secure_resource' for t in history),str(output))
