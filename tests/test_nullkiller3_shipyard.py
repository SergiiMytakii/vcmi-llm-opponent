"""A crossing may spend its own boat reserve and must preserve others' funds."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from playtesting.runs import copy_snapshot_file
from playtesting.reports import native_records as execution_records
from test_nullkiller3_water import water_world
from test_nullkiller3_campaign import campaign_records
from test_nullkiller3_native import native_records
from test_nullkiller3_strategy_visibility import permitted_request

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


def shipyard_world():
    world=water_world();objects=world['objects.json'];del objects['boat_900']
    helper=copy.deepcopy(next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red'))
    helper.update(x=6,y=12);helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
    objects['hero_902']=helper
    objects['shipyard_900']=dict(type='shipyard',subtype='object',x=7,y=14,l=0,options=dict(owner='red'),
        template=dict(animation='AVXSHYD0',editorAnimation='AVXSHYD0',mask=['VVV','VVV','BAB'],
                      visitableFrom=['---','+-+','+++']))
    world['header.json'].update(name='Nullkiller3 - Reserved Boat Construction',
        description='An owned shipyard and known water crossing; no existing boats. Control both towns to win.')
    return world


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires the isolated private NK3 game bundle')
class NativeShipyardTest(unittest.TestCase):
    def test_crossing_builds_a_real_boat_from_its_own_reserve(self):self.run_case(True)

    def test_other_obligation_wood_is_not_spent_on_a_boat(self):self.run_case(False)

    def test_hidden_water_boats_and_shipyards_do_not_change_construction_or_inputs(self):
        results={}
        for name in ('base','hidden_boat','hidden_coast','hidden_shipyard'):
            world=shipyard_world()
            # Keep the later model boundary on this side of the map too. The
            # native scout may otherwise reveal the distant variants after
            # completing the mine, invalidating the equal-observation premise.
            for row in world['surface_terrain.json']:row[20]=row[21]='wt20_'
            if name=='hidden_boat':
                boat=copy.deepcopy(water_world()['objects.json']['boat_900']);boat.update(x=33,y=20)
                world['objects.json']['boat_999']=boat
                world['surface_terrain.json'][20][32]='wt20_'
            elif name=='hidden_coast':
                for y in range(19,22):
                    for x in range(30,33):world['surface_terrain.json'][y][x]='wt20_'
            elif name=='hidden_shipyard':
                yard=copy.deepcopy(world['objects.json']['shipyard_900'])
                yard.update(x=33,y=20);yard['options']['owner']='blue'
                world['objects.json']['shipyard_999']=yard
            result=self.run_case(True,world,after_request=True)
            results[name]=result['equivalence']
            if name!='base':
                self.assertTrue(results[name]==results['base'],
                    'hidden variant changed permitted inputs, native rankings or the crossing: '+str(result['run']))

    def test_unowned_and_occupied_shipyards_offer_no_construction_quote(self):
        for name in ('neutral','enemy','occupied'):
            world=shipyard_world()
            if name=='occupied':
                # The engine can choose another empty launch tile. Occupy all
                # three water candidates rather than only the first choice.
                for y in (13,14,15):
                    boat=copy.deepcopy(water_world()['objects.json']['boat_900']);boat.update(x=9,y=y)
                    world['objects.json']['boat_'+str(990+y)]=boat
            else:world['objects.json']['shipyard_900']['options']['owner']='neutral' if name=='neutral' else 'blue'
            result=self.run_case(True,world,opening_only=True)
            self.assertEqual(result['requests'][0]['observation']['shipyards'],[],
                'unowned or occupied shipyard offered a construction quote: '+str(result['run']))

    def run_case(self,funded,world=None,after_request=False,opening_only=False):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-shipyard-',dir=ROOT/'.build/playtests'))
        print('\nNK3 shipyard evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        if world is None:world=shipyard_world()
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Shipyard.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_shipyard_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Shipyard.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],purpose='integration',case_id='nk3-shipyard',headless=True,
            max_seconds=15,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_SHIPYARD_MODE='funded' if funded else 'blocked');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (run/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if opening_only and records:break
                    completed=next((r for r in records if r['statuses'].get('across_water',{}).get('state')=='completed'),None)
                    if funded and completed:
                        current_requests=[]
                        for p in (run/'decisions').glob('*/request.json'):
                            try:current_requests.append(json.loads(p.read_text()))
                            except json.JSONDecodeError:continue # An exchange may still be writing its request.
                        if not after_request or any(r['identity']['day']>=completed['day'] for r in current_requests):break
                    if not funded and any(r['day']>=4 for r in records):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        records=campaign_records(run)
        self.assertTrue(records and 'hold' in records[0]['statuses'],'reserve plan was not accepted: '+str(run))
        requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                        key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        self.assertTrue(requests,'no opening request: '+str(run))
        if opening_only:return dict(run=run,requests=requests)
        hold=records[0]['reserves']
        minimum_wood=hold[0]-(10 if funded else 0);minimum_gold=hold[6]-(1000 if funded else 0)
        for record in records:
            if record['day']>4 or record['statuses']['hold']['state']=='completed':continue
            self.assertGreaterEqual(record['resources'][0],minimum_wood,'boat consumed another live wood reserve')
            self.assertGreaterEqual(record['resources'][6],minimum_gold,'boat consumed another live gold reserve')
        completed=any(r['statuses'].get('across_water',{}).get('state')=='completed' for r in records)
        if funded:
            self.assertTrue(completed,'no real boat creation and mine capture from the goal reserve: '+str(run))
            self.assertTrue(any(h['in_boat'] for r in records for h in r['heroes']),'no actual embark on a newly created boat')
            self.assertIn('build_boat',requests[0]['observation']['capabilities'])
            self.assertEqual(requests[0]['observation']['shipyards'],[
                dict(ref='object:4',boat_position=[8,14,0],cost=[10,0,0,0,0,0,1000])])
            executions,errors=execution_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
            self.assertEqual(errors,0,'incomplete execution evidence')
            build=next((r for r in executions if r['action'].get('goal_id')=='across_water'
                and r['action'].get('resource_delta')==[-10,0,0,0,0,0,-1000]),None)
            self.assertIsNotNone(build,'no acknowledged exact boat cost: '+str(run))
            self.assertEqual(build['action']['acknowledgment'],'acknowledged')
            self.assertTrue(any(h['in_boat'] for h in build['action']['after']['heroes']))
            if after_request:
                completed=next(r for r in records if r['statuses'].get('across_water',{}).get('state')=='completed')
                after=next((r for r in requests if r['identity']['day']>=completed['day']),None)
                self.assertIsNotNone(after,'no model input after construction: '+str(run))
                native=native_records(run)
                boundary=next((r for r in native if any(h['position']==[8,14,0] for h in r['heroes'])),None)
                self.assertIsNotNone(boundary,'no native ranking after construction: '+str(run))
                equivalence=dict(opening=permitted_request(requests[0]),after=permitted_request(after),
                    native_before=native[0],native_after=boundary,completed_day=completed['day'])
                (output/'proof.json').write_text(json.dumps(dict(completed_day=completed['day'],
                    cost=build['action']['resource_delta'],cleanup_complete=True,protected_files_unchanged=True),indent=2))
                return dict(run=run,requests=requests,equivalence=equivalence)
        else:
            self.assertFalse(any(h['in_boat'] for r in records if r['day']<=4 for h in r['heroes']),
                             'boat creation bypassed a current live resource reserve')


if __name__=='__main__':unittest.main()
