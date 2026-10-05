"""Real goal selection and acknowledged commands under permuted native ways."""
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
from playtesting.reports import native_records
from playtesting.runs import copy_snapshot_file

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(os.environ.get('VCMI_NK3_RANKING_CONFIG'),'requires a private ranking observer bundle')
class NativeRankingTest(unittest.TestCase):
    def test_same_goal_uses_native_preference_before_conflict_filtering_in_both_input_orders(self):
        config=json.loads(Path(os.environ['VCMI_NK3_RANKING_CONFIG']).read_text())
        out=Path(tempfile.mkdtemp(prefix='nk3-ranking-',dir=ROOT/'.build/playtests'))
        print('\nNK3 ranking evidence:',out,flush=True)
        fixture=out/'fixture'
        shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file,
                        ignore=shutil.ignore_patterns('cache','logs','extracted','Saves'))
        world=variants()['base'];objects=world['objects.json']
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
        mine=copy.deepcopy(next(v for v in objects.values() if v['type']=='mine'))
        for name in [k for k,v in objects.items() if v['type'] in ('resource','mine','monster')]:del objects[name]
        mine.update(x=8,y=13);objects['mine_target']=mine
        for name,x,y,kind in [('helper_a',7,10,'christian'),('helper_b',7,13,'adela')]:
            helper=copy.deepcopy(own);helper.update(x=x,y=y)
            helper['options'].update(type=kind,army=[dict(type='core:pikeman',amount=15)])
            objects[name]=helper
            world['header.json']['players']['red']['heroes'][name]={'type':kind}
        map_path=fixture/'Library/Application Support/vcmi/Maps/NK3Ranking.vmap'
        with zipfile.ZipFile(map_path,'w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        controller=ROOT/'tests/fixtures/nk3_ranking_strategy.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Ranking.vmap',players={'red':'Nullkiller3','blue':'EmptyAI'},
                      nk3_mode='model',purpose='integration',case_id='nk3-ranking',headless=True,max_seconds=15,
                      references={},experience_mode='off',controller=[sys.executable,str(controller)],controller_sources=[str(controller)])
        config.pop('save_resource',None)
        observed=[];effects=[]
        runs=[('worst',config),('best',config)]
        if os.environ.get('VCMI_NK3_RANKING_ORDINARY_CONFIG'):
            ordinary=json.loads(Path(os.environ['VCMI_NK3_RANKING_ORDINARY_CONFIG']).read_text())
            ordinary.update({k:v for k,v in config.items() if k not in ('engine','engine_sources')})
            runs.append(('ordinary',ordinary))
        for order,run_config in runs:
            path=out/(order+'.json');path.write_text(json.dumps(run_config));run=out/order
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            env=dict(os.environ,NK3_RANK_ORDER=order);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+18
                    while child.poll() is None and time.monotonic()<deadline:
                        records,_=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
                        if any(r.get('action',{}).get('goal_id')=='capture' and r['outcome']=='effects_observed' for r in records):break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            log_path=run/'engine-logs/VCMI_Client_log.txt'
            if order!='ordinary':
                choices,errors=native_records(log_path,'NK3_TEST_RANK_CHOICES');self.assertFalse(errors)
                selections,errors=native_records(log_path,'NK3_TEST_RANK_SELECTED');self.assertFalse(errors)
                choice=next((r for r in choices if len(r.get('choices',[]))>=2),None)
                self.assertIsNotNone(choice,'fixture exposed no competing native ways: '+str(run))
                alternatives=[x for x in choice['choices'] if x['goal']=='capture']
                ranks={(x['tier'],x['score']) for x in alternatives}
                self.assertGreater(len(ranks),1,'native evaluator did not distinguish the ways: '+str(run))
                # Reference comes from the unchanged NK2 evaluator in the observer,
                # independently of the campaign's ranking implementation.
                preferred=min(alternatives,key=lambda x:(x['tier'],-x['score']))
                selected=next(x for r in selections if r['pass']==choice['pass'] for x in r['selected'] if x['goal']=='capture')
                expected={k:v for k,v in preferred.items() if k not in ('tier','score')}
                self.assertEqual(selected,expected,'campaign discarded native preference: '+str(run))
                observed.append(selected)
                if config.get('ranking_contracts'):
                    contracts,errors=native_records(log_path,'NK3_TEST_RANK_CONTRACT');self.assertFalse(errors)
                    self.assertEqual({r['case'] for r in contracts},{'earlier_tier','strategy_priority','equal_goal_order',
                        'equal_rank_stable','all_zero_admitted','urgent_preempts','native_baseline'})
                    self.assertTrue(all(r['passed'] for r in contracts),str(contracts))
            report=json.loads((run/'report.json').read_text())
            effect=next((r for r in report['native_execution'] if r.get('action',{}).get('goal_id')=='capture'
                         and r['outcome']=='effects_observed'),None)
            self.assertIsNotNone(effect,'selected operation produced no acknowledged effect: '+str(run))
            effects.append(effect['action']['after'])
            self.assertTrue(report['assignment_matches'])
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertEqual(observed[0],observed[1],'native choice depends on task enumeration')
        self.assertTrue(all(after==effects[0] for after in effects),'ordinary engine executed a different operation')


if __name__=='__main__':unittest.main()
