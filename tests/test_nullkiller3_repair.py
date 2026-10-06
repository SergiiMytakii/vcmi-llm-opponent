"""Native delivery continues after the named helper is lost in a real battle."""
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

from fixtures.fog_maps import variants
from test_nullkiller3_campaign import campaign_records
from playtesting.runs import copy_snapshot_file

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires a separate NK3 build and private native fixture')
class NativeRepairTest(unittest.TestCase):
    def test_adjacent_small_replacement_delivers_after_the_named_courier_is_lost(self):
        self.run_helper_loss(False,adjacent=True)

    def test_lost_courier_is_replaced_without_changing_the_recipient_or_replaying_a_handoff(self):
        self.run_helper_loss(False)

    def test_replacement_survives_save_load_during_a_multiday_delivery(self):
        self.run_helper_loss(True)

    def test_lost_defense_courier_is_replaced_and_the_recipient_holds_the_critical_town(self):
        self.run_helper_loss(False,defense=True)

    def test_feasible_courier_replacement_does_not_request_a_strategic_repair(self):
        self.run_helper_loss(False,review=True)

    def test_lost_courier_without_unpledged_replacement_force_receives_a_strategic_review(self):
        self.run_helper_loss(False,review=True,unrepairable=True)

    def run_helper_loss(self, restoring,defense=False,review=False,unrepairable=False,adjacent=False):
        config = json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-helper-loss-', dir=ROOT / '.build/playtests'))
        print('\nNK3 helper-loss evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture,copy_function=copy_snapshot_file)
        world = variants()['base']
        objects = world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']: del objects[name]
        original = next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        courier = copy.deepcopy(original)
        courier.update(x=34,y=22)
        courier['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
        helper = copy.deepcopy(original)
        helper.update(x=18,y=22)
        helper['options'].update(type='adela',army=[dict(type='core:pikeman',amount=100)])
        if adjacent:
            original['options']['army']=[dict(type='core:'+kind,amount=count) for kind,count in
                (('warUnicorn',18),('grandElf',68),('dendroidSoldier',27),('silverPegasus',35),
                 ('centaurCaptain',85),('centaur',96),('battleDwarf',77))]
            helper.update(x=5,y=12)
            helper['options']['army']=[dict(type='core:'+kind,amount=count) for kind,count in
                (('pegasus',5),('silverPegasus',2),('gremlin',16))]
        objects['hero_900']=courier
        objects['hero_999']=helper
        if restoring:
            helper.update(x=34,y=5)
            helper['options']['army'][0]['amount']=120
            town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
            town['options']['buildings']['allOf']=['fort','townHall']
            town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
            second=copy.deepcopy(town);second.update(x=34,y=5);objects['town_999']=second
            settings=fixture/'Library/Application Support/vcmi/config/settings.json'
            values=json.loads(settings.read_text());values.setdefault('adventure',{})['enemyMoveTime']=100
            settings.write_text(json.dumps(values))
        enemy = next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy.update(x=34,y=21)
        enemy['options']['army']=[dict(type='core:archer',amount=20)]
        with zipfile.ZipFile(fixture / 'Library/Application Support/vcmi/Maps/NK3HelperLoss.vmap','w') as archive:
            for filename,value in world.items(): archive.writestr(filename,json.dumps(value))
        def goal(name,kind,actor,target,building,minimum,dependencies,predicate):
            return dict(id=name,kind=kind,actor_ref=actor,target_ref=target,building_id=building,
                        deadline_day=6,priority=80,min_army_value=minimum,depends_on=dependencies,
                        required_capabilities=['build'] if kind=='develop_town' else ['land','transfer'],
                        complete_when=predicate)
        seed=dict(version=3,revision=1,approach='offense',horizon_days=5,
                  goals=[goal('guild1','develop_town',None,'object:3',0,0,[],dict(kind='building_present',value=0)),
                         goal('guild2','develop_town',None,'object:3',1,0,['guild1'],dict(kind='building_present',value=1)),
                         goal('deliver','reinforce_hero','object:0','object:1',-1,12000,['guild2'],dict(kind='army_at_least',value=12000))],
                  reserves=[],policy=dict(max_loss_ratio=.2,allow_route_repair=True,
                                           allow_helper_replacement=True,critical_towns=['object:3']))
        if adjacent:
            seed['goals'][-1].update(min_army_value=132436,complete_when=dict(kind='army_at_least',value=133496))
            # Replacement is permitted, but a speculative frontier step must
            # not mask rejection of the already known direct handoff route.
            seed['policy']['allow_route_repair']=False
        if restoring:
            seed['goals'].append(goal('backup','preserve_force','object:2','object:4',-1,1000,[],dict(kind='force_preserved_until',value=6)))
            seed['goals'][-1]['required_capabilities']=['land']
            seed['reserves']=[dict(goal_id='backup',resources=[0]*7,force_value=1000)]
        if unrepairable:
            seed['goals'].append(goal('backup','preserve_force','object:2','object:3',-1,8900,[],dict(kind='force_preserved_until',value=6)))
            seed['goals'][-1]['required_capabilities']=['land']
            seed['reserves']=[dict(goal_id='backup',resources=[0]*7,force_value=8900)]
        if defense:
            seed['approach']='defense'
            seed['goals'].append(goal('home','defend_area','object:0','object:3',-1,12000,['deliver'],dict(kind='held_until',value=6)))
            seed['goals'][-1]['required_capabilities']=['land']
        seed_path=output/'campaign.json'; seed_path.write_text(json.dumps(seed))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3HelperLoss.vmap',
                      players={'red':'Nullkiller3','blue':'Nullkiller2'},nk3_mode='native',purpose='integration',
                      case_id='nk3-helper-loss',headless=not restoring,max_seconds=45 if restoring else 25,references={})
        if review:
            probe=ROOT/'tests/fixtures/nk3_retention_probe.py'
            config.update(nk3_mode='model',controller=[sys.executable,str(probe)],controller_sources=[str(probe)],experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json'; path.write_text(json.dumps(config)); run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (run/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                                   env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path)),stdin=subprocess.PIPE if restoring else None,
                                   stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+50 if restoring else time.monotonic()+30
                sent=False
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if restoring:
                        if not sent and any((r.get('local_repairs') or {}).get('deliver') and r['statuses']['deliver']['state']!='completed' for r in records):
                            child.stdin.write(b'save Saves/NK3ReplacementProbe\n');child.stdin.flush();sent=True
                        logfile=run/'engine-logs/VCMI_Client_log.txt'
                        if sent and 'Game has been successfully saved!' in logfile.read_text(errors='replace'): break
                    elif defense:
                        if any(r['statuses']['home']['state']=='completed' for r in records):break
                    elif unrepairable:
                        if any(r['day']>=3 for r in records):break
                    elif any(r['statuses']['deliver']['state']=='completed' and (r.get('local_repairs') or {}).get('deliver') for r in records): break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True); child.wait(timeout=15)
                if child.stdin: child.stdin.close()
        original_run=run
        if restoring:
            self.assertTrue(sent,'replacement was not observable before completion: '+str(run))
            config.update(profile_template=str(run/'profile'),save_resource='Saves/NK3ReplacementProbe.vsgm1',headless=True,max_seconds=30)
            path=output/'restored.json';path.write_text(json.dumps(config));run=output/'restored'
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            env=dict(os.environ);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+35
                    while child.poll() is None and time.monotonic()<deadline:
                        records=campaign_records(run)
                        if any(r['statuses']['deliver']['state']=='completed' for r in records): break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        if unrepairable:
            self.assertTrue(records,'campaign did not run: '+str(run))
            lost=[r for r in records if all(h['ref']!='object:1' for h in r['heroes'])]
            self.assertTrue(lost,'courier was not lost: '+str(run))
            self.assertTrue(all(not (r.get('local_repairs') or {}).get('deliver') for r in lost),
                            'replacement took already pledged force: '+str(run))
            self.assertTrue(all(r['statuses']['deliver']['state']!='completed' for r in lost))
            self.assertTrue(all(h['army_value']>=8900 for r in lost for h in r['heroes'] if h['ref']=='object:2'))
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            reviews=[r for r in requests if any(s['question']=='battle_loss:object:1' for s in r['signals'])]
            self.assertEqual(len(reviews),1,'unrepairable courier loss was not reviewed once: '+str(run))
            self.assertEqual(reviews[0]['identity']['day'],lost[0]['day'])
            report=json.loads((run/'report.json').read_text())
            self.assertTrue(any(b['action']['kind']=='battle' and b['action'].get('actor_ref')=='object:1'
                                and b['outcome']=='battle_lost' for b in report['native_execution']))
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            self.assertTrue(report['assignment_matches'])
            return
        if restoring:
            self.assertTrue(records,'restored campaign did not run')
            self.assertNotEqual(records[0]['statuses']['deliver']['state'],'completed','save missed the interrupted meeting')
            self.assertEqual((records[0].get('local_repairs') or {})['deliver']['to'],'object:2','saved helper choice was lost')
            self.assertGreaterEqual(len({r['day'] for r in records}),2,'delivery did not span several days after loading')
        repairs=[r for r in records if (r.get('local_repairs') or {}).get('deliver')]
        self.assertTrue(repairs,'no native helper replacement: '+str(run))
        self.assertTrue(any(all(h['ref']!='object:1' for h in r['heroes']) for r in repairs),'original helper still owned')
        self.assertTrue(all(r['local_repairs']['deliver']['to']=='object:2' for r in repairs),'replacement changed between passes')
        done=next((i for i,r in enumerate(records) if r['statuses']['deliver']['state']=='completed'),None)
        self.assertIsNotNone(done,'replacement did not deliver: '+str(run))
        delivered=records[done]; before=records[done-1]
        armies=lambda record: {h['ref']:h['army_value'] for h in record['heroes']}
        self.assertGreater(armies(delivered)['object:0'],armies(before)['object:0'])
        self.assertLess(armies(delivered)['object:2'],armies(before)['object:2'],'completion came from recruitment rather than handoff')
        self.assertLessEqual(delivered['day'],6)
        if review:
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            repair_requests=[r for r in requests if r['identity']['day']<=delivered['day']
                             and any(s['question'].startswith(('battle_loss:','commitment:','repair_exhausted')) for s in r['signals'])]
            self.assertTrue(not repair_requests,'a feasible local courier repair was discussed before native continuation: '+str(run))
        if restoring:
            for record in records:
                self.assertGreaterEqual(armies(record)['object:2'],1000,'replacement spent its own force floor')
        self.assertEqual(sum(armies(delivered).values()),sum(armies(before).values()),'handoff changed total own army')
        text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertIn('Exchange between heroes',text)
        if defense:
            held=next((r for r in records if r['statuses']['home']['state']=='completed'),None)
            self.assertIsNotNone(held,'replacement did not supply the critical-town defense by its deadline: '+str(run))
            self.assertEqual(held['statuses']['home']['completed_day'],6)
            defender=next(h for h in held['heroes'] if h['ref']=='object:0')
            self.assertEqual(defender['position'],[5,11,0]);self.assertGreaterEqual(defender['army_value'],12000)
            self.assertTrue(all(any(t['ref']=='object:3' for t in r['towns']) for r in records),'critical town was lost')
            battles=json.loads((run/'report.json').read_text())['native_execution']
            self.assertTrue(any(b['action']['kind']=='battle' and b['action'].get('actor_ref')=='object:1'
                                and b['outcome']=='battle_lost' for b in battles),'courier loss has no acknowledged battle evidence')
        for checked in {run,original_run}:
            launch=json.loads((checked/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']); self.assertTrue(launch['protected_files_unchanged'])
            self.assertTrue(json.loads((checked/'report.json').read_text())['assignment_matches'])


if __name__ == '__main__': unittest.main()
