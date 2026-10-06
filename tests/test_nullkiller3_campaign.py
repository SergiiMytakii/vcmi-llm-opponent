"""Executable native campaign, reserves and save/load through the owned game."""
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

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/playtest.py'


def campaign_records(run):
    path = run / 'engine-logs/VCMI_Client_log.txt'
    if not path.exists(): return []
    text = path.read_text(errors='replace')
    result = []
    decoder = json.JSONDecoder()
    for match in re.finditer('NK3_CAMPAIGN ', text):
        start = match.end()
        while start < len(text) and text[start].isspace(): start += 1
        try: result.append(decoder.raw_decode(text, start)[0])
        except ValueError: pass
    return result


def seed_campaign():
    def goal(name, building, dependencies):
        return dict(id=name, kind='develop_town', actor_ref=None, target_ref='object:1',
                    deadline_day=6, priority=75, building_id=building, min_army_value=0,
                    depends_on=dependencies, required_capabilities=['build'],
                    complete_when=dict(kind='building_present', value=building))
    return dict(version=3, revision=1, approach='economy', horizon_days=5,
                goals=[goal('guild1', 0, []), goal('guild2', 1, ['guild1'])],
                reserves=[dict(goal_id='guild2', resources=[5,4,5,4,4,4,2000], force_value=0)],
                policy=dict(max_loss_ratio=.2, allow_route_repair=True,
                            allow_helper_replacement=True, critical_towns=['object:1']))


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires a separate NK3 build and private native fixture')
class NativeCampaignTest(unittest.TestCase):
    def test_explicit_build_dependency_spends_own_reserve_and_does_not_replay_after_load(self):
        config = json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-campaign-', dir=ROOT / '.build/playtests'))
        print('\nNK3 campaign evidence:', output, flush=True)
        seed = output / 'campaign.json'
        seed.write_text(json.dumps(seed_campaign()))
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'}, nk3_mode='native', purpose='integration',
                      case_id='nk3-campaign', headless=False, max_seconds=40, references={})
        config.pop('save_resource', None)
        def prepare(name):
            path = output / (name + '.json'); path.write_text(json.dumps(config))
            run = output / name
            subprocess.run([sys.executable, str(CLI), 'prepare', '--config', str(path), '--out', str(run)],
                           capture_output=True, check=True)
            return run
        def drive(run, saving):
            environment = dict(os.environ)
            environment.pop('VCMI_NK3_SEED_CAMPAIGN', None)
            if saving: environment['VCMI_NK3_SEED_CAMPAIGN'] = str(seed)
            with (run / 'driver.log').open('w') as log:
                child = subprocess.Popen([sys.executable, str(CLI), 'run', '--run', str(run)],
                                         stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                         env=environment)
                sent = reached = False
                try:
                    deadline = time.monotonic() + 45
                    while child.poll() is None and time.monotonic() < deadline:
                        records = campaign_records(run)
                        if saving:
                            first_complete=any(r['statuses']['guild1']['state']=='completed' and r['statuses']['guild2']['state']!='completed' for r in records)
                            if first_complete and not sent:
                                child.stdin.write(b'save Saves/NK3CampaignProbe\n'); child.stdin.flush(); sent=True
                            path = run / 'engine-logs/VCMI_Client_log.txt'
                            reached = path.exists() and 'Game has been successfully saved!' in path.read_text(errors='replace')
                        else:
                            reached = any(r['statuses']['guild2']['state'] == 'completed' for r in records)
                        if reached: break
                        time.sleep(.02)
                finally:
                    (run / 'STOP').touch(exist_ok=True)
                    child.wait(timeout=15); child.stdin.close()
            self.assertTrue(reached, str(run))
            launch = json.loads((run / 'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']); self.assertTrue(launch['protected_files_unchanged'])
            report = json.loads((run / 'report.json').read_text()); self.assertTrue(report['assignment_matches'])
            self.assertFalse(list((run / 'decisions').iterdir()), 'native campaign called a model')
            return campaign_records(run)
        first = prepare('save'); before = drive(first, True)
        self.assertTrue(any(r['statuses']['guild1']['state']=='completed' and r['statuses']['guild2']['state']!='completed' for r in before))
        self.assertEqual(before[0]['reserves'], [5,4,5,4,4,4,2000])
        # Actual native purchase and construction may use only unreserved funds
        # until the second building consumes its own commitment.
        for record in before:
            if record['statuses']['guild2']['state'] != 'completed':
                self.assertTrue(all(a >= b for a,b in zip(record['resources'], record['reserves'])))
        config.update(profile_template=str(first / 'profile'), save_resource='Saves/NK3CampaignProbe.vsgm1')
        restored = prepare('load'); after = drive(restored, False)
        self.assertTrue(after)
        self.assertEqual(after[0]['statuses']['guild1']['state'], 'completed')
        final = next(r for r in after if r['statuses']['guild2']['state'] == 'completed')
        self.assertEqual(final['reserves'], [0]*7)
        text = (restored / 'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertNotIn('will build building.core.castle.mageGuild1.name', text)
        self.assertLessEqual(text.count('will build building.core.castle.mageGuild2.name'), 1)
        (output / 'results.json').write_text(json.dumps(dict(before=before, after=after), indent=2))

    def test_delivery_uses_current_route_keeps_courier_force_and_holds_without_repeated_visits(self):
        config = json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-delivery-', dir=ROOT / '.build/playtests'))
        print('\nNK3 delivery evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture)
        config.update(profile_template=str(fixture), map_resource='Maps/NK3Delivery.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'}, nk3_mode='native', purpose='integration',
                      case_id='nk3-delivery', headless=True, max_seconds=35, references={})
        config.pop('save_resource', None)
        def goal(name, kind, actor, target, priority, minimum, predicate):
            return dict(id=name, kind=kind, actor_ref=actor, target_ref=target, deadline_day=6,
                        priority=priority, building_id=-1, min_army_value=minimum, depends_on=[],
                        required_capabilities=['land','transfer'] if kind == 'reinforce_hero' else ['land'],
                        complete_when=predicate)
        seed = dict(version=3, revision=1, approach='offense', horizon_days=5,
                    goals=[goal('deliver','reinforce_hero','object:0','object:1',80,12000,
                                dict(kind='army_at_least',value=12000)),
                           goal('courier','preserve_force','object:1','object:2',10,1000,
                                dict(kind='force_preserved_until',value=6))],
                    reserves=[dict(goal_id='courier',resources=[0]*7,force_value=1000)],
                    policy=dict(max_loss_ratio=.2,allow_route_repair=True,
                                allow_helper_replacement=True,critical_towns=['object:2']))
        seed_path = output / 'campaign.json'; seed_path.write_text(json.dumps(seed))
        results = {}
        for name, x, y in [('near',8,8), ('detour',34,22)]:
            with self.subTest(route=name):
                world = variants()['base']
                objects = world['objects.json']
                source = copy.deepcopy(next(v for v in objects.values()
                                           if v['type']=='hero' and v['options']['owner']=='red'))
                source.update(x=x,y=y); source['options']['type']='christian'
                source['options']['army']=[dict(type='core:pikeman',amount=100)]
                objects['hero_999'] = source
                with zipfile.ZipFile(fixture / 'Library/Application Support/vcmi/Maps/NK3Delivery.vmap','w') as archive:
                    for filename, value in world.items(): archive.writestr(filename,json.dumps(value))
                path = output / (name+'.json'); path.write_text(json.dumps(config)); run=output/name
                subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],
                               check=True,capture_output=True)
                environment=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path))
                with (run/'driver.log').open('w') as log:
                    child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                                           env=environment,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        deadline=time.monotonic()+40
                        while child.poll() is None and time.monotonic()<deadline:
                            records=campaign_records(run)
                            completed=[r for r in records if r['statuses']['deliver']['state']=='completed']
                            holding=[r for r in completed if r['statuses']['courier']['reason']=='holding_preserved_force']
                            if len(holding)>=3: break
                            time.sleep(.02)
                    finally:
                        (run/'STOP').touch(exist_ok=True); child.wait(timeout=15)
                records=campaign_records(run)
                index=next((i for i,r in enumerate(records) if r['statuses']['deliver']['state']=='completed'),None)
                self.assertIsNotNone(index,'no confirmed delivery: '+str(run))
                delivered=records[index]; previous=records[index-1]
                recipient=next(h for h in delivered['heroes'] if h['ref']=='object:0')
                courier=next(h for h in delivered['heroes'] if h['ref']=='object:1')
                self.assertGreaterEqual(recipient['army_value'],12000)
                self.assertGreaterEqual(courier['army_value'],1000)
                self.assertGreater(recipient['army_value'],next(h for h in previous['heroes'] if h['ref']=='object:0')['army_value'])
                self.assertLess(courier['army_value'],next(h for h in previous['heroes'] if h['ref']=='object:1')['army_value'],
                                'recipient threshold came from recruitment instead of a handoff')
                self.assertLessEqual(delivered['day'],6,'delivery missed its deadline')
                self.assertEqual(sum(h['army_value'] for h in previous['heroes']),
                                 sum(h['army_value'] for h in delivered['heroes']), 'handoff lost army')
                # The long route can meet away from town. Preservation becomes
                # a hold only after the courier returns; that return is useful.
                hold_index=next((i for i,r in enumerate(records[index:],index)
                                 if r['statuses']['courier']['reason']=='holding_preserved_force'),None)
                self.assertIsNotNone(hold_index,'courier did not return to its preservation area')
                hold=records[hold_index]
                held_courier=next(h for h in hold['heroes'] if h['ref']=='object:1')
                for record in records[hold_index:]:
                    if record['day'] != hold['day']: break
                    current=next(h for h in record['heroes'] if h['ref']=='object:1')
                    self.assertEqual(current['movement'],held_courier['movement'],'courier repeated a useless rendezvous')
                for record in records[:index]:
                    main=next(h for h in record['heroes'] if h['ref']=='object:0')
                    self.assertGreaterEqual(main['army_value'],5900,'delivery sent recipient army backwards')
                for record in records:
                    helper=next(h for h in record['heroes'] if h['ref']=='object:1')
                    self.assertGreaterEqual(helper['army_value'],1000,'courier force reserve was violated')
                if name=='detour': self.assertGreaterEqual(delivered['day'],2,'fixture did not exercise multi-day replanning')
                text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
                self.assertIn('Exchange between heroes',text)
                self.assertIn('Hero exchange for hero.core.catherine.name',text)
                launch=json.loads((run/'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete']); self.assertTrue(launch['protected_files_unchanged'])
                self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])
                results[name]=records
        (output/'results.json').write_text(json.dumps(results,indent=2))


if __name__ == '__main__': unittest.main()
