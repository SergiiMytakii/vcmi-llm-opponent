"""A new unallocated investment/army choice reaches the real model boundary."""
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
from playtesting.runs import copy_snapshot_file
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a private ordinary native strategy build')
class NativeCheckpointTest(unittest.TestCase):
    def test_completed_short_commitment_opens_one_three_day_allocation_review(self):
        self.run_choice(4)

    def test_pre_growth_allocation_review_keeps_the_supported_long_commitment(self):
        self.run_choice(7)

    def run_choice(self,release_day):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        out=Path(tempfile.mkdtemp(prefix='nk3-allocation-checkpoint-',dir=ROOT/'.build/playtests'))
        print('\nNK3 allocation checkpoint evidence:',out,flush=True)
        fixture=out/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in list(objects):
            if objects[name]['type'] in ('mine','resource','monster'):del objects[name]
        town=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','citadel','castle','blacksmith','marketplace','mageGuild1',
            'tavern','dwellingLvl1','dwellingLvl7','dwellingUpLvl7',
            'townHall' if release_day==4 else 'villageHall']
        town['options']['buildings']['noneOf']=['shipyard']+[
            'dwellingLvl'+str(i) for i in range(2,7)]+[
            'dwellingUpLvl'+str(i) for i in range(1,7)]
        world['header.json']['allowedHeroes']={'anyOf':['core:catherine','core:roland','core:christian']}
        main=next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red')
        helper=copy.deepcopy(main);helper.update(y=12)
        helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
        objects['hero_helper']=helper
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3AllocationCheckpoint.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        def hold(name,hero,until,minimum):
            return dict(id=name,kind='preserve_force',actor_ref=hero,target_ref='object:2',deadline_day=until,
                priority=80,building_id=-1,min_army_value=minimum,depends_on=[],required_capabilities=['land'],
                complete_when=dict(kind='force_preserved_until',value=until))
        long_reserve=4000 if release_day==4 else 6300
        plan=dict(version=3,revision=1,approach='defense',horizon_days=7,
            goals=[hold('main','object:0',8,5900),hold('short','object:1',release_day,89)],
            reserves=[dict(goal_id='short',resources=[15,7,15,7,7,7,10000-long_reserve],force_value=0),
                      dict(goal_id='main',resources=[0,0,0,0,0,0,long_reserve],force_value=0)],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[]))
        seed=out/'campaign.json';seed.write_text(json.dumps(plan))
        probe=ROOT/'tests/fixtures/nk3_retention_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3AllocationCheckpoint.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',purpose='integration',
            case_id='nk3-allocation-checkpoint',headless=True,max_seconds=20,references={},experience_mode='off',
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        config.pop('save_resource',None)
        path=out/'config.json';path.write_text(json.dumps(config));run=out/'game'
        subprocess.run([sys.executable,'scripts/playtest.py','prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (run/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,'scripts/playtest.py','run','--run',str(run)],
                env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>release_day for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'campaign did not run: '+str(run))
        self.assertTrue(any(r['statuses']['short']['state']=='completed' for r in records))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        checkpoints=[r for r in requests if any(s['question']=='checkpoint:allocation' for s in r['signals'])]
        self.assertEqual(len(checkpoints),1,'the newly unallocated funded choice was not reviewed once: '+str(run))
        review=checkpoints[0];self.assertEqual(review['identity']['day'],release_day)
        self.assertTrue(not [r for r in requests if r['identity']['day']<release_day],
                        'ordinary protected income requested the model: '+str(run))
        self.assertEqual([s['question'] for s in review['signals']],['checkpoint:allocation'])
        self.assertEqual(review['identity']['revision'],1)
        self.assertEqual(review['observation']['goal_statuses']['main']['state'],'waiting')
        facts=next(s['facts'] for s in review['signals'] if s['question']=='checkpoint:allocation')
        quotes=[];decoder=json.JSONDecoder()
        while facts.strip():
            quote,end=decoder.raw_decode(facts.lstrip())
            quotes.append(quote);facts=facts.lstrip()[end:]
        self.assertTrue(quotes,'checkpoint contains no investment/army alternatives')
        for quote in quotes:
            cost=sum(u['count']*u['unit_cost'][6] for u in quote['recruitment_stock'])
            protected=sum(r['resources'][6] for r in review['campaign']['reserves']
                          if review['observation']['goal_statuses'][r['goal_id']]['state']!='completed')
            gold=review['observation']['resources'][6]-protected
            self.assertLessEqual(cost,gold);self.assertLessEqual(quote['investment_cost'][6],gold)
            self.assertGreater(cost+quote['investment_cost'][6],gold)
        self.assertTrue(all(h['army_value']>=5900 for r in records for h in r['heroes'] if h['ref']=='object:0'))
        launch=json.loads((run/'launch.json').read_text());report=json.loads((run/'report.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(report['assignment_matches'])


if __name__=='__main__':unittest.main()
