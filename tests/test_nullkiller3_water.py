"""Existing visible boats through real embark, sailing and disembark commands."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import variants
from playtesting.runs import copy_snapshot_file
from playtesting.reports import native_records as execution_records
from test_nullkiller3_campaign import campaign_records
from test_nullkiller3_native import native_records
from test_nullkiller3_strategy_visibility import permitted_request

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


def water_world():
    world=variants()['base'];objects=world['objects.json']
    world['header.json'].update(name='Nullkiller3 - Existing Boat Crossing',
        description='Two Castle starts separated by water. Existing boats permit crossings; adventure movement spells are forbidden. Control both towns to win.')
    ore=copy.deepcopy(next(o for o in objects.values() if o['type']=='mine' and o['subtype']=='orePit'))
    for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
    own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
    own.update(x=8,y=11);own['options']['army']=[dict(type='core:archangel',amount=20)]
    enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
    enemy.update(x=31,y=11);enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
    for row in world['surface_terrain.json']:
        row[8]=row[9]='wt20_'
    objects['boat_900']=dict(type='boat',subtype='evil',x=9,y=11,l=0,options={},
        template=dict(animation='AVXBOAT0',editorAnimation='AVXBOAT0',mask=['VVV','VAV'],
                      visitableFrom=['+++','+-+','+++']))
    ore.update(x=12,y=11);objects['mine_901']=ore
    return world


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires the isolated private NK3 game bundle')
class NativeWaterTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('VCMI_NK3_WATER_SAVE_CONFIG'),'requires a private exact-embark checkpoint probe')
    def test_saved_embarked_hero_continues_the_capture_after_loading(self):
        ordinary=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        config=json.loads(Path(os.environ['VCMI_NK3_WATER_SAVE_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-water-save-',dir=ROOT/'.build/playtests'))
        print('\nNK3 saved boat evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        settings=fixture/'Library/Application Support/vcmi/config/settings.json'
        values=json.loads(settings.read_text());values.setdefault('adventure',{})['enemyMoveTime']=1000
        settings.write_text(json.dumps(values))
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3SavedBoat.vmap','w') as archive:
            for name,value in water_world().items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_water_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3SavedBoat.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],purpose='integration',case_id='nk3-saved-boat',headless=False,
            max_seconds=45,experience_mode='off')
        config.pop('save_resource',None)
        def prepare(name):
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            return run
        env=dict(os.environ,VCMI_NK3_TURN_LOSS_PROBE_MODE='embark_save');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        first=prepare('save')
        with (first/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(first)],env=env,
                                   stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35
                logfile=first/'engine-logs/VCMI_Client_log.txt'
                while child.poll() is None and time.monotonic()<deadline:
                    if logfile.exists() and 'NK3_TEST_EMBARKED_SAVE' in logfile.read_text(errors='replace'):break
                    time.sleep(.02)
                self.assertTrue(logfile.exists() and 'NK3_TEST_EMBARKED_SAVE' in logfile.read_text(errors='replace'),
                                'no acknowledged embarked checkpoint: '+str(first))
                self.assertTrue('Game has been successfully saved!' in logfile.read_text(errors='replace'),
                                'the console checkpoint was not confirmed')
            finally:
                (first/'STOP').touch(exist_ok=True);child.wait(timeout=15);child.stdin.close()
        launch=json.loads((first/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        config.update(engine=ordinary['engine'],engine_sources=ordinary['engine_sources'],
                      profile_template=str(first/'profile'),save_resource='Saves/NK3EmbarkedProbe.vsgm1',headless=True,max_seconds=15)
        env.pop('VCMI_NK3_TURN_LOSS_PROBE_MODE',None)
        restored=prepare('load')
        with (restored/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(restored)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['statuses'].get('across_water',{}).get('state')=='completed' for r in campaign_records(restored)):break
                    time.sleep(.03)
            finally:
                (restored/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(restored)
        self.assertTrue(records,'loaded NK3 did not restore its campaign')
        self.assertTrue(any(h['in_boat'] for h in records[0]['heroes']),
                        'checkpoint did not contain an embarked hero: '+str(restored))
        self.assertEqual(records[0]['revision'],1,'the accepted campaign was replaced at load')
        self.assertTrue(any(r['statuses'].get('across_water',{}).get('state')=='completed' for r in records),
                        'loaded boat did not disembark and capture the mine: '+str(restored))
        executions,errors=execution_records(restored/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
        self.assertEqual(errors,0)
        self.assertTrue(executions and executions[0]['outcome']=='reconciled_unknown',
                        'the interrupted embark was attributed as a completed command')
        for execution in executions:
            action=execution['action']
            if execution['outcome']!='effects_observed' or action.get('goal_id')!='across_water':continue
            before={h['ref']:h for h in action['before']['heroes']}
            self.assertFalse(any(h['ref'] in before and h['in_boat'] and not before[h['ref']]['in_boat']
                                 for h in action['after']['heroes']),
                             'loaded goal replayed embark instead of continuing from its actual boat')
        requests=[json.loads(p.read_text()) for p in (restored/'decisions').glob('*/request.json')]
        self.assertFalse(any(s['question']=='opening' for r in requests for s in r['signals']),
                         'loading the boat erased the accepted plan')
        launch=json.loads((restored/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

    def test_observed_boat_crosses_water_and_captures_the_visible_mine(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-water-',dir=ROOT/'.build/playtests'))
        print('\nNK3 water evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Water.vmap','w') as archive:
            for name,value in water_world().items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_water_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Water.vmap',references={},
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
            case_id='nk3-water',headless=True,max_seconds=12,experience_mode='off')
        config.pop('save_resource',None)
        results={}
        for name,ai in [('control','Nullkiller2'),('campaign','Nullkiller3')]:
            config.update(players={'red':ai,'blue':'EmptyAI'},max_seconds=4 if name=='control' else 12)
            if ai=='Nullkiller3':config['nk3_mode']='model'
            else:config.pop('nk3_mode',None)
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            env=dict(os.environ);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+17
                    while child.poll() is None and time.monotonic()<deadline:
                        if name=='campaign' and any(r['statuses'].get('across_water',{}).get('state')=='completed'
                                                   for r in campaign_records(run)):break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            results[name]=run
        control=(results['control']/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        moves=re.findall(r'Hero hero.core.catherine.name moved from \((\d+) (\d+) (\d+)\) to \((\d+) (\d+) (\d+)\)',control)
        self.assertTrue(any(int(m[3]) in (8,9) for m in moves) and any(int(m[3])>=10 for m in moves),
                        'ordinary NK2 did not demonstrate movement on and across the water strip: '+str(results['control']))
        records=campaign_records(results['campaign'])
        self.assertTrue(any(r['statuses'].get('across_water',{}).get('state')=='completed' for r in records),
                        'native campaign did not cross observed water and capture the mine: '+str(results['campaign']))
        self.assertTrue(any(h['position'][0] in (8,9) and h['in_boat'] for r in records for h in r['heroes']),
                        'no acknowledged own position on the water strip')
        completed=next(r for r in records if r['statuses'].get('across_water',{}).get('state')=='completed')
        self.assertTrue(any(h['position'][0]>=10 and not h['in_boat'] for h in completed['heroes']),
                        'capture was not followed by an acknowledged disembarked own hero')
        requests=[json.loads(p.read_text()) for p in (results['campaign']/'decisions').glob('*/request.json')]
        self.assertIn('water',requests[0]['observation']['capabilities'])
        self.assertNotIn('water',requests[0]['observation']['unsupported_capabilities'])
        opening=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        self.assertTrue(any(o['kind']=='boat' and o['position']==[8,11,0]
                            for o in opening['observation']['visible_objects']),
                        'the model cannot identify the current visible boat supporting this route')

    def test_hidden_boats_and_water_do_not_change_the_observed_crossing_and_a_missing_boat_blocks_it(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-water-visibility-',dir=ROOT/'.build/playtests'))
        print('\nNK3 water visibility evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        probe=ROOT/'tests/fixtures/nk3_water_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3WaterVisibility.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
            case_id='nk3-water-visibility',headless=True,max_seconds=12,experience_mode='off')
        config.pop('save_resource',None)
        results={}
        for name in ('base','hidden_boat','hidden_water','missing_boat'):
            world=water_world()
            if name.startswith('hidden'):
                for y in range(6,9):
                    for x in range(26,29):world['surface_terrain.json'][y][x]='wt20_'
                if name=='hidden_boat':
                    boat=copy.deepcopy(world['objects.json']['boat_900']);boat.update(x=28,y=7)
                    world['objects.json']['boat_999']=boat
            elif name=='missing_boat':del world['objects.json']['boat_900']
            with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3WaterVisibility.vmap','w') as archive:
                for filename,value in world.items():archive.writestr(filename,json.dumps(value))
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            env=dict(os.environ);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+17
                    while child.poll() is None and time.monotonic()<deadline:
                        records=campaign_records(run)
                        completed=next((r for r in records if r['statuses'].get('across_water',{}).get('state')=='completed'),None)
                        if name!='missing_boat' and completed:
                            current_requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
                            if any(r['identity']['day']>=completed['day'] for r in current_requests):break
                        if name=='missing_boat' and any(r['day']>=4 for r in records):break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            records=campaign_records(run)
            requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                            key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
            self.assertTrue(requests,'no player-visible strategic boundary: '+str(run))
            results[name]=dict(opening=permitted_request(requests[0]))
            completed=next((r for r in records if r['statuses'].get('across_water',{}).get('state')=='completed'),None)
            if name=='missing_boat':
                self.assertIsNone(completed,'a crossing was invented without an existing boat')
                self.assertFalse(any(h['in_boat'] for r in records for h in r['heroes']),'native code created an unsupported boat')
                self.assertTrue(any(s['question']=='repair_exhausted' for r in requests for s in r['signals']),
                                'a missing-boat precondition was not surfaced after native repair')
                continue
            self.assertIsNotNone(completed,'paired game did not complete the real crossing: '+str(run))
            boarded=next((r for r in records if any(h['in_boat'] for h in r['heroes'])),None)
            self.assertIsNotNone(boarded,'no observed boat movement: '+str(run))
            native=native_records(run)
            boundary=next((i for i,r in enumerate(native) if any(h['position'][0] in (8,9) for h in r['heroes'])),None)
            self.assertIsNotNone(boundary,'no native ranking boundary after actual embark: '+str(run))
            results[name].update(boarded=boarded,completed_day=completed['day'],native_before=native[0],native_after=native[boundary])
            after_request=next((r for r in requests if r['identity']['day']>=completed['day']),None)
            self.assertIsNotNone(after_request,'no model input after the actual crossing: '+str(run))
            results[name]['after_request']=permitted_request(after_request)
            if name!='base':
                self.assertEqual(results[name],results['base'],'hidden water/boat changed permitted input, native ranking or actual crossing')
        (output/'proof.json').write_text(json.dumps(dict(runs=list(results),equivalent=['base','hidden_boat','hidden_water'],
            completed_day=results['base']['completed_day'],missing_boat_blocks=True),indent=2))


if __name__=='__main__':unittest.main()
