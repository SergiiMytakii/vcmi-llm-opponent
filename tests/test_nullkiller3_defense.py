"""Observed defense questions must account for the available owned force."""
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

from fixtures.fog_maps import variants
from playtesting.runs import copy_snapshot_file

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a private NK3 bundle')
class NativeDefenseTest(unittest.TestCase):
    def test_stationed_force_wins_a_real_attack_and_the_critical_town_remains_owned(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-real-defense-',dir=ROOT/'.build/playtests'))
        print('\nNK3 real defense evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=12,y=11);enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy['options']['secondarySkills'].append(dict(skill='scouting',level='expert'))
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3RealDefense.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        # The controlled attacker uses its own offered actions only. A forced
        # weak attack proves defense execution, not comparative playing strength.
        probe=output/'attacker.py';probe.write_text('''import json,sys
r=json.load(sys.stdin)
attacks=[a for a in r['actions'] if a['kind']=='attack' and a.get('owner')==0 and a.get('object_type')==98]
action=attacks[0] if attacks else next(a for a in r['actions'] if a['kind']=='end_turn')
print(json.dumps(dict(protocol=1,request_id=r['request_id'],action_id=action['id'])))
''')
        goal=dict(id='home',kind='defend_area',actor_ref='object:0',target_ref='object:1',
            deadline_day=3,priority=80,building_id=-1,min_army_value=5900,depends_on=[],
            required_capabilities=['land'],complete_when=dict(kind='held_until',value=3))
        plan=dict(version=3,revision=1,approach='defense',horizon_days=5,goals=[goal],reserves=[],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3RealDefense.vmap',
            players={'red':'Nullkiller3','blue':'ExternalAI'},nk3_mode='native',references={},
            purpose='integration',case_id='nk3-real-defense',headless=True,max_seconds=15,experience_mode='off',
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        from test_nullkiller3_campaign import campaign_records
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=3 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        report=json.loads((run/'report.json').read_text());self.assertTrue(report['assignment_matches'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(requests,'attacker did not receive public offered actions')
        self.assertTrue(any(a['kind']=='attack' and a.get('owner')==0 and a.get('object_type')==98
                            for r in requests for a in r['actions']),'attacker could not see the defended town')
        battles=[r for r in report['native_execution'] if r['action']['kind']=='battle']
        self.assertEqual(len(battles),1,'no single acknowledged own defense battle: '+str(run))
        battle=battles[0];self.assertEqual(battle['outcome'],'battle_won')
        self.assertEqual(battle['action']['player'],0);self.assertEqual(battle['action']['actor_ref'],'object:0')
        self.assertGreaterEqual(battle['action']['army_value_before'],5900,
            'stationed defender lost its initial force before the attack')
        records=campaign_records(run);self.assertTrue(any(r['day']>=3 for r in records))
        self.assertTrue(all(next(h for h in r['heroes'] if h['ref']=='object:0')['position']==[5,11,0]
                            for r in records if r['day']==1),'the own hero attacked instead of defending the town')
        self.assertTrue(all('object:1' in [t['ref'] for t in r['towns']] for r in records),'critical town was lost')
        self.assertTrue(any(r['statuses']['home']['state']=='completed' for r in records),'defense did not complete')

    def test_visiting_defender_completes_held_until_before_any_town_army_exchange(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-visiting-defense-',dir=ROOT/'.build/playtests'))
        print('\nNK3 visiting defense evidence:',output,flush=True)
        goal=dict(id='home',kind='defend_area',actor_ref='object:0',target_ref='object:1',
            deadline_day=1,priority=80,building_id=-1,min_army_value=5900,depends_on=[],
            required_capabilities=['land'],complete_when=dict(kind='held_until',value=1))
        plan=dict(version=3,revision=1,approach='defense',horizon_days=3,goals=[goal],reserves=[],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,
                        critical_towns=['object:1']))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='native',references={},
            purpose='integration',case_id='nk3-visiting-defense',headless=True,max_seconds=12,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        from test_nullkiller3_campaign import campaign_records
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+16
                while child.poll() is None and time.monotonic()<deadline:
                    if campaign_records(run):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])
        records=campaign_records(run);self.assertTrue(records,'no initial campaign observation')
        first=records[0];hero=next(h for h in first['heroes'] if h['ref']=='object:0')
        town=next(t for t in first['towns'] if t['ref']=='object:1')
        self.assertEqual(first['day'],1)
        self.assertEqual(hero['position'],[5,11,0]);self.assertEqual(hero['army_value'],5900)
        self.assertEqual(town['army_holder_ref'],'object:1');self.assertEqual(town['defense_value'],0)
        self.assertEqual(first['statuses']['home']['state'],'completed',
            'the stationed visiting defender was omitted before any native exchange')
        self.assertFalse(list((run/'decisions').glob('*/request.json')),'native hold called a model')

    def test_critical_defense_recruits_before_economic_construction_and_records_the_reserve_override(self):
        self.run_defense_spending(False)

    def test_urgent_recruitment_is_acknowledged_before_waiting_for_the_shared_model(self):
        self.run_defense_spending(True)

    def run_defense_spending(self,waiting):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-defense-spending-',dir=ROOT/'.build/playtests'))
        print('\nNK3 defense spending evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        own['options']['army']=[dict(type='core:pikeman',amount=1)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=9,y=13);enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall','blacksmith','marketplace','mageGuild1','tavern','dwellingLvl1']
        town['options']['buildings']['noneOf']=['shipyard']
        world['header.json']['allowedHeroes']={'anyOf':['core:catherine','core:roland']}
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3DefenseSpending.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        goal=dict(id='income',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=6,
                  priority=80,building_id=12,min_army_value=0,depends_on=[],required_capabilities=['build'],
                  complete_when=dict(kind='building_present',value=12))
        plan=dict(version=3,revision=1,approach='economy',horizon_days=5,goals=[goal],
                  reserves=[dict(goal_id='income',resources=[0,0,0,0,0,0,10000],force_value=0)],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
        seed=output/'campaign.json';seed.write_text(json.dumps(plan))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3DefenseSpending.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model' if waiting else 'native',references={},purpose='integration',
            case_id='nk3-defense-spending',headless=True,max_seconds=15,experience_mode='off')
        config.pop('save_resource',None)
        if waiting:
            probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
            config.update(controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        from test_nullkiller3_campaign import campaign_records
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed),NK3_PROBE_MODE='slow'),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    if waiting:
                        if list((run/'decisions').glob('*/request.json')):break
                    elif any(r['statuses']['income']['state']=='completed' for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'economic commitment was not installed')
        initial=next(r for r in records if r.get('forecasts'))
        defense=next(d for d in initial['forecasts']['defenses'] if d['town_ref']=='object:1')
        self.assertEqual(defense['status'],'insufficient_current_force','fixture has no insufficient visible critical defense')
        self.assertEqual(initial['reserves'][6],10000)
        report=json.loads((run/'report.json').read_text())
        effects=[r for r in report['native_execution'] if r['outcome']=='effects_observed']
        self.assertTrue(effects,'no real native resource consequence')
        first=effects[0]['action']
        self.assertEqual(first['kind'],'recruit','economic priority pass spent before urgent defense')
        self.assertGreater(first['after']['heroes'][0]['army_value'],first['before']['heroes'][0]['army_value'])
        spent=-first['resource_delta'][6];self.assertGreater(spent,0);self.assertLessEqual(spent,980)
        self.assertEqual(first['reservation_override'][6],spent,'emergency spending did not report its actual reserve breach')
        if not waiting:self.assertTrue(any(r['statuses']['income']['state']=='completed' for r in records),'economic obligation could not continue after defense')
        if waiting:
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            self.assertTrue(requests,'fixture did not reach a strategic wait')
            request=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
            self.assertGreater(request['observation']['heroes'][0]['army_value'],first['before']['heroes'][0]['army_value'],
                'the model snapshot preceded acknowledged urgent recruitment')
        else:
            self.assertFalse(list((run/'decisions').glob('*/request.json')),'native urgency called a model')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

    def test_weak_visible_front_does_not_request_an_insufficient_defense_review_when_own_hero_can_return_today(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-defense-',dir=ROOT/'.build/playtests'))
        print('\nNK3 defense evidence:',output,flush=True)
        fixture=output/'fixture'
        shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        hero['options']['army']=[dict(type='core:archangel',amount=20)]
        hero['options']['secondarySkills'].append(dict(skill='logistics',level='expert'))
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=13,y=10);enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Defense.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Defense.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-defense',headless=True,max_seconds=15,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        def requests():
            return sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                          key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        env=dict(os.environ,NK3_PROBE_MODE='reachable_fronts');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['observation']['forecasts']['threats'] for r in requests()):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        items=requests();revealed=next((r for r in items if r['observation']['forecasts']['threats']),None)
        self.assertIsNotNone(revealed,'the real scout did not reveal the enemy: '+str(run))
        observation=revealed['observation'];threat=observation['forecasts']['threats'][0]
        own=observation['heroes'][0]
        route=next(r for r in observation['forecasts']['routes'] if r['target_ref']==threat['town_ref'])
        timely=[a for a in route['own_arrivals'] if a['hero_ref']==own['ref'] and a['day']==observation['day'] and a['army_loss_estimate']==0]
        self.assertTrue(timely,'fixture has no safe same-day return route')
        self.assertGreater(own['army_value'],threat['army_interval']['upper']*100)
        self.assertFalse([s for s in revealed['signals'] if s['question'].startswith('defense:')],
                         'a covered weak front was classified as insufficient defense')
        defense=next(d for d in observation['forecasts']['defenses'] if d['town_ref']==threat['town_ref'])
        self.assertEqual(defense['status'],'conditional_force_available')
        self.assertEqual(defense['allocated_hero_refs'],[own['ref']])
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
