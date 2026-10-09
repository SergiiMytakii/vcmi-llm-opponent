"""An accepted town-source reinforcement must prove its physical handoff."""
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
from test_nullkiller3_campaign import campaign_records
from playtesting.runs import copy_snapshot_file

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires a private NK3 bundle')
class NativeTownDeliveryTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('VCMI_NK3_GARRISON_CONFIG'),'requires a private garrison-state probe')
    def test_recruitment_with_seven_occupied_slots_keeps_the_garrison_floor_at_every_acknowledgment(self):
        config=json.loads(Path(os.environ['VCMI_NK3_GARRISON_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-seven-slots-',dir=ROOT/'.build/playtests'))
        print('\nNK3 seven-slot evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red');hero.update(x=9,y=11)
        helper=copy.deepcopy(hero);helper.update(x=6,y=11)
        helper['options'].update(type='christian',army=[dict(type='core:'+kind,amount=1) for kind in
            ('imp','skeleton','goblin','troglodyte','gnoll','halfling','peasant')])
        objects['hero_garrison']=helper
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall','dwellingLvl1']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl')
            for level in range(1,8) if not (prefix=='dwellingLvl' and level==1)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3SevenSlots.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3SevenSlots.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',experience_mode='off',purpose='integration',case_id='nk3-seven-slots',
            headless=True,max_seconds=10,references={},controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='garrison_slots');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+15
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=2 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'seven-slot plan was not accepted')
        initial=records[0]['heroes'][1]['army_value']
        text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        source=re.search(r'NK3_TEST_GARRISON town=\d+ hero=(\d+) army=(\d+)',text)
        self.assertIsNotNone(source,'no acknowledged garrison state')
        self.assertEqual(int(source[2]),initial)
        changes=[(int(day),int(army),int(slots)) for day,hero_id,army,slots in
            re.findall(r'NK3_TEST_ARMY day=(\d+) hero=(\d+) army=(\d+) slots=(\d+)',text)
            if int(hero_id)==int(source[1]) and int(day)<=6]
        self.assertTrue(changes,'no actual garrison packet observations')
        self.assertTrue(all(army>=initial for day,army,slots in changes),
            'dismiss-before-recruit breached the accepted force floor: '+str(changes)+' '+str(run))
        self.assertTrue(any(slots==7 for day,army,slots in changes),'fixture did not contain seven occupied slots')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

    def test_owned_town_donates_its_army_and_confirms_the_named_delivery(self):
        self.run_delivery(False)

    @unittest.skipUnless(os.environ.get('VCMI_NK3_GARRISON_CONFIG'),'requires a private garrison-state probe')
    def test_town_source_uses_its_garrison_hero_pool_and_keeps_that_heros_force_floor(self):
        self.run_delivery(True)

    def test_town_delivery_forecast_funds_recruitment_from_its_current_stock(self):
        self.run_delivery(False,recruit=True)

    def test_town_delivery_forecast_waits_for_weekly_growth_and_acknowledges_the_final_handoff(self):
        self.run_delivery(False,recruit=True,weekly=True)

    def test_supported_weekly_delivery_wait_does_not_trigger_a_stagnation_review(self):
        self.run_delivery(False,recruit=True,weekly=True,review=True)

    def test_town_delivery_without_unpledged_or_funded_force_is_blocked_before_movement(self):
        self.run_delivery(False,protected=True)

    def run_delivery(self,garrison,recruit=False,weekly=False,review=False,protected=False):
        key='VCMI_NK3_GARRISON_CONFIG' if garrison else 'VCMI_NK3_CAMPAIGN_CONFIG'
        config=json.loads(Path(os.environ[key]).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-town-delivery-',dir=ROOT/'.build/playtests'))
        print('\nNK3 town-delivery evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red');hero.update(x=9,y=11)
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['army']=[] if garrison else [dict(type='core:pikeman',amount=45 if recruit else 100)]
        if garrison:
            helper=copy.deepcopy(hero);helper.update(x=6,y=11)
            helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=100)])
            objects['hero_garrison']=helper
            world['header.json']['players']['red']['heroes']['hero_garrison']={'type':'christian'}
        if protected:
            helper=copy.deepcopy(hero);helper.update(x=6,y=11)
            helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=100)])
            objects['hero_defender']=helper
            world['header.json']['players']['red']['heroes']['hero_defender']={'type':'christian'}
        town_ref='object:2' if garrison or protected else 'object:1'
        town['options']['buildings']['allOf']=['fort','townHall']+(['dwellingLvl1'] if recruit else [])
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8) if not (recruit and prefix=='dwellingLvl' and level==1)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3TownDelivery.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        required=10000 if recruit and not weekly else 12000
        source_initial=4005 if recruit else 8900
        deadline_day=8 if weekly else 6
        seed=dict(version=3,revision=1,approach='offense',horizon_days=7 if weekly else 5,
                  goals=[dict(id='deliver',kind='reinforce_hero',actor_ref='object:0',target_ref=town_ref,deadline_day=deadline_day,
                              priority=80,building_id=-1,min_army_value=required,depends_on=[],required_capabilities=['land','transfer'],
                              complete_when=dict(kind='army_at_least',value=required))],reserves=[],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town_ref]))
        if garrison:
            seed['goals'].append(dict(id='hold',kind='preserve_force',actor_ref='object:1',target_ref=town_ref,deadline_day=deadline_day,
                priority=40,building_id=-1,min_army_value=1000,depends_on=[],required_capabilities=['land'],
                complete_when=dict(kind='force_preserved_until',value=6)))
        if protected:
            seed['goals'].append(dict(id='hold',kind='defend_area',actor_ref='object:1',target_ref=town_ref,
                deadline_day=6,priority=40,building_id=-1,min_army_value=8900,depends_on=[],
                required_capabilities=['land'],complete_when=dict(kind='held_until',value=6)))
        seed_path=output/'campaign.json';seed_path.write_text(json.dumps(seed))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3TownDelivery.vmap',players={'red':'Nullkiller3','blue':'EmptyAI'},
                      nk3_mode='native',experience_mode='off',purpose='integration',case_id='nk3-town-delivery',headless=True,max_seconds=60 if weekly else 20,references={})
        if protected:config['review_interval_days']=1
        if review or protected:
            probe=ROOT/'tests/fixtures/nk3_retention_probe.py'
            config.update(nk3_mode='model',controller=[sys.executable,str(probe)],controller_sources=[str(probe)],experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                                   env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+(65 if weekly else 25)
                while child.poll() is None and time.monotonic()<deadline:
                    if protected:
                        state=run/'turn-review/state.json'
                        if state.exists() and json.loads(state.read_text()).get('status')=='paused':break
                    if any(r['heroes'][0]['army_value']>=required for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        if protected:
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            first_day=[r for r in records if r['day']==1]
            self.assertTrue(first_day,'no accepted native campaign observation')
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            self.assertTrue(any(s['question']=='repair_exhausted' and 'source_force_unavailable' in s['facts']
                for r in requests if r['observation']['day']==1 for s in r['signals']),
                'unfundable town delivery repeated without immediate repair feedback: '+str(run))
            self.assertFalse(any(r['confirmed_deliveries'] for r in first_day),'protected town produced a false receipt')
            turns=[json.loads(line) for line in (run/'turn-review/turns.jsonl').read_text().splitlines()]
            end=next(r for r in turns if r['player']==0 and r['phase']=='end')
            recipient=next(h for h in end['heroes'] if h['name']=='hero.core.catherine.name')
            self.assertGreater(recipient['movement'],0,'futile delivery attempts spent the main army movement')
            self.assertEqual(recipient['army_value'],5900)
            return
        if review:
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            self.assertFalse(any(s['question'].startswith('stagnation:') for r in requests for s in r['signals']),
                             'a supported weekly stock wait was mistaken for stagnation: '+str(run))
        self.assertTrue(records,'town-source plan was not installed')
        self.assertEqual(records[0]['heroes'][0]['army_value'],5900)
        completed=[r for r in records if r['statuses']['deliver']['state']=='completed']
        self.assertTrue(completed,'physical town handoff did not confirm the accepted goal: '+str(run))
        receipt=next(d for d in completed[0]['confirmed_deliveries'] if d['goal']['id']=='deliver')
        self.assertEqual(receipt['source_ref'],town_ref)
        self.assertGreaterEqual(receipt['recipient_after'],required)
        self.assertLess(receipt['source_after'],source_initial,'town did not contribute army')
        if not garrison:
            first=next(r for r in records if isinstance(r.get('forecasts'),dict))
            deliveries=first['forecasts'].get('deliveries',[])
            self.assertTrue(deliveries,'accepted delivery has no route/force forecast')
            if recruit and not weekly:
                army_branch=next(a for a in first['forecasts']['alternatives'] if a['approach']=='offense' and a['town_ref']==town_ref)
                recruited=receipt['recipient_after']+receipt['source_after']-5900-source_initial
                self.assertEqual(army_branch['army_purchased_value'],recruited,'recruitment uses a different troop-value unit from actual own armies')
            predicted=next(d for d in deliveries if d['goal_id']=='deliver')
            self.assertEqual(predicted['status'],'conditional')
            self.assertEqual(predicted['arrival_day'],receipt['day'])
            self.assertGreaterEqual(predicted['recipient_possible_value'],required)
            if recruit:
                self.assertTrue(predicted.get('recruitment_schedule'),'stock was omitted from funded reinforcement forecast')
                if weekly:
                    self.assertEqual(receipt['day'],8,'delivery ignored the first weekly growth boundary')
                    self.assertEqual([s['day'] for s in predicted['recruitment_schedule']],[1,8])
                self.assertGreater(receipt['recipient_after']+receipt['source_after'],5900+source_initial,'no new troops actually joined the handoff')

        if garrison:
            self.assertIn('NK3_TEST_GARRISON',(run/'engine-logs/VCMI_Client_log.txt').read_text())
            self.assertEqual(records[0]['heroes'][1]['army_value'],8900)
            self.assertGreaterEqual(receipt['source_after'],1000,'named town delivery spent its garrison hero floor')
            self.assertEqual(receipt['source_after']+receipt['recipient_after'],14800,'handoff did not conserve the two owned armies')
            self.assertTrue(all(r['heroes'][1]['army_value']>=1000 for r in records if r['day']<=6))
        if not review:
            self.assertFalse(list((run/'decisions').glob('*/request.json')))
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
