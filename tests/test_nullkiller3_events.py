"""Independent critical events and repeated blockers through the real engine."""
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
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires the private strategy bundle')
class StrategicEventsTest(unittest.TestCase):
    def test_two_days_without_building_progress_are_reviewed_before_the_deadline(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-building-stagnation-',dir=ROOT/'.build/playtests'))
        print('\nNK3 building-stagnation evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        own['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy_town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='blue')
        enemy.update(x=enemy_town['x']-1,y=enemy_town['y'])
        enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3BuildingStagnation.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        goal=dict(id='guild4',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=7,
                  priority=80,building_id=3,min_army_value=0,depends_on=[],required_capabilities=['build'],
                  complete_when=dict(kind='building_present',value=3))
        plan=dict(version=3,revision=1,approach='economy',horizon_days=6,goals=[goal],reserves=[],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3BuildingStagnation.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-building-stagnation',headless=True,max_seconds=20,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='retain_seed',VCMI_NK3_SEED_CAMPAIGN=str(seed))
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=6 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        self.assertTrue(any(r['day']>=6 for r in records),'fixture did not reach the observation day: '+str(run))
        buildings=[(r['day'],tuple(r['towns'][0]['buildings'])) for r in records if r['towns']]
        self.assertTrue(any(0 in b for day,b in buildings),'a real prerequisite was not built')
        self.assertTrue(all(3 not in b for day,b in buildings),'fixture unexpectedly completed Mage Guild 4')
        related=[(day,tuple(i for i in b if i in (0,1,2,3))) for day,b in buildings]
        changes=[day for i,(day,b) in enumerate(related) if i and b!=related[i-1][1]]
        self.assertTrue(changes and max(changes)<=4,'fixture did not stop building for two own days: '+str(changes))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        stagnation=[r for r in requests if 4<=r['identity']['day']<=6
                    and any(s['question'].startswith('stagnation:') for s in r['signals'])]
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertEqual(len(stagnation),1,'unchanged stalled building must be reviewed once before expiry: '+str(run))
        self.assertEqual(stagnation[0]['identity']['day'],4,'unrelated construction reset the objective progress clock')

    def test_forecast_cash_wait_is_not_building_stagnation(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-building-cash-wait-',dir=ROOT/'.build/playtests'))
        print('\nNK3 building cash-wait evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall','blacksmith','marketplace','mageGuild1','tavern']
        town['options']['buildings']['noneOf'].remove('tavern')
        world['header.json']['allowedHeroes']={'anyOf':['core:catherine','core:roland']}
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        own.update(x=town['x']-1,y=town['y']);own['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy_town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='blue')
        enemy.update(x=enemy_town['x']-1,y=enemy_town['y']);enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3BuildingCashWait.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        goals=[dict(id='city',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=7,
                    priority=80,building_id=12,min_army_value=0,depends_on=[],required_capabilities=['build'],
                    complete_when=dict(kind='building_present',value=12)),
               dict(id='hold',kind='preserve_force',actor_ref='object:0',target_ref='object:1',deadline_day=7,
                    priority=40,building_id=-1,min_army_value=89,depends_on=[],required_capabilities=['land'],
                    complete_when=dict(kind='force_preserved_until',value=7))]
        plan=dict(version=3,revision=1,approach='economy',horizon_days=6,goals=goals,
                  reserves=[dict(goal_id='hold',resources=[0,0,0,0,0,0,9500],force_value=0)],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3BuildingCashWait.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-building-cash-wait',headless=True,max_seconds=20,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='retain_seed',VCMI_NK3_SEED_CAMPAIGN=str(seed))
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['statuses'].get('city',{}).get('state')=='completed' for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        waited=[r for r in records if r['day']>=3 and r['statuses'].get('city',{}).get('state')!='completed'
                and any(c['goal_id']=='city' and c['status']=='conditional' and c['schedule'][0]['day']>r['day']
                        for c in r.get('forecasts',{}).get('commitments',[]))]
        self.assertTrue(waited,'fixture did not wait two own days for forecast income: '+str(run))
        self.assertTrue(any(r['statuses'].get('city',{}).get('state')=='completed' for r in records),
                        'the forecast wait did not end in an actual building: '+str(run))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertFalse([s for r in requests for s in r['signals'] if s['question'].startswith('stagnation:')],
                         'planned own income was treated as useless repeated work')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

    @unittest.skipUnless(os.environ.get('VCMI_NK3_EVENTS_CONFIG'),'requires the independent-event packet probe')
    def test_three_independent_force_floor_breaches_can_be_reviewed_in_one_turn(self):
        config=json.loads(Path(os.environ['VCMI_NK3_EVENTS_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-three-events-',dir=ROOT/'.build/playtests'))
        print('\nNK3 three-event evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        own.update(x=9,y=11);own['options']['army']=[dict(type='core:archangel',amount=20),dict(type='core:pikeman',amount=1)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=34,y=22)
        enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy_town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='blue')
        enemy_town.update(x=35,y=22)
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['army']=[]
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
        for index,(x,y,kind) in enumerate([(town['x'],town['y'],'christian'),(18,20,'adela'),(28,4,'caitlin')]):
            source=copy.deepcopy(town);source.update(x=x,y=y)
            if index:objects['town_'+str(900+index)]=source
            holder=copy.deepcopy(own);holder.update(x=x-1,y=y)
            holder['options'].update(type=kind,army=[dict(type='core:'+unit,amount=1) for unit in
                ('imp','skeleton','goblin','troglodyte','gnoll','halfling','peasant')])
            objects['hero_'+str(1000+index)]=holder
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3ThreeEvents.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3ThreeEvents.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-three-events',headless=True,max_seconds=20,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='three_force_events',VCMI_NK3_EVENT_LOG=str(run/'engine-logs/VCMI_Client_log.txt'))
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=3 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                        key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        critical=[r for r in requests if r['identity']['day']==2
                  and any(s['question'].startswith('commitment:') and s['critical'] for s in r['signals'])]
        self.assertGreaterEqual(len(critical),3,'three actual independent critical reviews were not made: '+str(run))
        questions=[{s['question'] for s in r['signals'] if s['question'].startswith('commitment:')} for r in critical]
        self.assertEqual(sum(map(len,questions)),3,'the same broken commitment was queried repeatedly')
        self.assertEqual(len(set().union(*questions)),3,'events were not independent owned obligations')
        self.assertEqual([sum(s['reason']=='force_floor_breached' for s in r['observation']['goal_statuses'].values())
                          for r in critical[:3]],[1,2,3],'losses were coalesced before the preceding review')
        text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        changes=re.findall(r'NK3_TEST_INDEPENDENT_LOSS day=2 ordinal=(\d+) hero=(\d+) before=(\d+) after=(\d+)',text)
        self.assertEqual([int(c[0]) for c in changes],[1,2,3])
        self.assertEqual(len({c[1] for c in changes}),3)
        self.assertTrue(all(int(c[2])>int(c[3]) for c in changes),'a question did not follow an actual acknowledged force change')
        decoder=json.JSONDecoder();finished=[]
        for match in re.finditer('NK3_STRATEGY ',text):
            record,end=decoder.raw_decode(text[match.end():].lstrip())
            if record.get('day')==2 and record.get('requested') and any(s['question'].startswith('commitment:') for s in record['signals']):
                finished.append((record,match.end()+end))
        self.assertGreaterEqual(len(finished),3,'third review did not finish')
        self.assertTrue(all(r.get('accepted') is True for r,end in finished[:3]),'a critical strategy was not retained')
        following=[]
        for match in re.finditer('NK3_EXECUTION ',text[finished[2][1]:]):
            record,end=decoder.raw_decode(text[finished[2][1]+match.end():].lstrip())
            action=record['action']
            if action['before']['day']==2 and record['outcome']=='effects_observed':
                following.append(action['before']['heroes'][0]['position']!=action['after']['heroes'][0]['position'])
        self.assertTrue(any(following),'native movement did not continue after the third critical review')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

    def test_renumbered_unchanged_blocker_does_not_retry_the_model(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-critical-events-',dir=ROOT/'.build/playtests'))
        print('\nNK3 critical-events evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        own['options']['army']=[dict(type='core:archangel',amount=20)]
        own['options']['secondarySkills'].append(dict(skill='logistics',level='expert'))
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=11,y=10);enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        for name,x,kind in [('hero_900',17,'christian'),('hero_999',23,'adela')]:
            other=copy.deepcopy(enemy);other['x']=x;other['options']['type']=kind;objects[name]=other
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3CriticalEvents.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3CriticalEvents.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-critical-events',headless=True,max_seconds=8,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        def requests():return sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                                     key=lambda r:int(r['request_id'].split(':')[-1]))
        env=dict(os.environ,NK3_PROBE_MODE='fronts');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35
                while child.poll() is None and time.monotonic()<deadline:
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        items=requests()
        text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        repeated=[s['facts'] for r in items for s in r['signals'] if s['question']=='repair_exhausted']
        self.assertTrue(repeated,'fixture did not create a real blocked intention')
        self.assertEqual(len(repeated),len(set(repeated)),'a new revision replayed an unchanged repair question')
        self.assertTrue('"accepted" : true' in text,'renumbered model intentions were not installed')
        self.assertTrue('NK3_NATIVE' in text,'native continuation was not observed')


if __name__=='__main__':unittest.main()
