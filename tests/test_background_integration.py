"""Actual callback/own-turn callers; controlled transport, never a user's game."""
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
from fixtures.background_maps import safe_map,partial_map,allocation_map,stabilization_map
from playtesting.runs import copy_snapshot_file
ROOT=Path(__file__).resolve().parents[1]


def records(path,marker):
    if not path.exists():return []
    result=[];text=path.read_text(errors='replace');decoder=json.JSONDecoder()
    for match in re.finditer(marker+r' (\{)',text):
        try:result.append(decoder.raw_decode(text[match.start(1):])[0])
        except ValueError:pass
    return result


@unittest.skipUnless(os.environ.get('VCMI_NK3_BACKGROUND_CONFIG'),'requires isolated built native fixture')
class BackgroundIntegrationTest(unittest.TestCase):
    def test_partial_admission_preserves_secondary_hero_need_before_spending(self):
        self.run_barrier('partial')

    def test_allocation_question_survives_routine_reserves_before_spending(self):
        self.run_barrier('allocation')

    def test_urgent_purchase_cannot_erase_captured_defense_question(self):
        self.run_barrier('stabilization')

    def run_barrier(self,case):
        config=json.loads(Path(os.environ['VCMI_NK3_BACKGROUND_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='native-background-'+case+'-',dir=ROOT/'.build/background-proof'))
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        data={'partial':partial_map,'allocation':allocation_map,'stabilization':stabilization_map}[case]()
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/BackgroundBarrier.vmap','x') as archive:
            for name,value in data.items():archive.writestr(name,json.dumps(value))
        settings_path=fixture/'Library/Application Support/vcmi/config/ai/nk2ai/nk2ai-settings.json'
        runtime=Path(config['engine']).parents[1]/'Resources/Data/config/ai/nk2ai/nk2ai-settings.json'
        settings=json.loads(re.sub(r'//[^\n]*','',runtime.read_text()))
        for node in settings.values():
            if isinstance(node,dict):node.update(maxPass=1,maxPriorityPass=1)
        settings_path.parent.mkdir(parents=True,exist_ok=True);settings_path.write_text(json.dumps(settings))
        controller=ROOT/'tests/fixtures/nk3_background_cases.py'
        config.update(profile_template=str(fixture),map_resource='Maps/BackgroundBarrier.vmap',
            controller=[sys.executable,str(controller)],controller_sources=[str(controller),str(ROOT/'tests/fixtures/strategic_intent.py')],
            case_id='background-'+case,max_seconds=50,experience_mode='off',headless=True,review_interval_days=0)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_BG_BARRIER_CASE=case,VCMI_AI_OPEN_MAP='1')
        target_day=7 if case=='allocation' else 2
        with (output/'driver.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+52
                while process.poll() is None and time.monotonic()<deadline:
                    if any(t.get('player')==0 and t.get('day')==target_day and t.get('accepted') is True
                           for t in records(run/'runtime.log','NK3_STRATEGY')):break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True);process.wait(timeout=15)
        print('Native caller barrier proof:',case,output,flush=True)
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        ordinary=[r for r in requests if r['identity']['player']==0 and r['identity']['day']==target_day and not r.get('mode')]
        self.assertTrue(ordinary,str(output));fresh=ordinary[-1]
        admissions=[t for t in records(run/'runtime.log','NK3_BACKGROUND') if t.get('phase')=='admit' and t.get('execution_day')==target_day]
        if case=='stabilization':
            self.assertFalse(admissions,str(output))
            self.assertTrue(any(s['question'].startswith('defense:') for s in fresh['signals']),str(output))
            self.assertTrue(all(d['status']=='conditional_force_available' for d in fresh['observation']['forecasts']['defenses']),str(output))
            self.assertTrue(any(t['player']==0 and t['day']==2 and t['action']['kind']=='recruit'
                for t in records(run/'runtime.log','NK3_EXECUTION')),str(output))
            self.assertTrue(any(e['day']==2 and e['action']['kind']=='recruit'
                for e in fresh['memory'].get('recent_results',[])),str(output))
        else:
            self.assertTrue(admissions,str(output));admission=admissions[-1]
            self.assertIn('prepared-town',[g['id'] for g in fresh['campaign']['goals']],str(output))
            self.assertIn('prepared-town',[v['goal_id'] for v in fresh['campaign']['reserves']],str(output))
            if case=='allocation':
                self.assertTrue(any(s['question']=='checkpoint:allocation' for s in fresh['signals']),str(output))
                self.assertTrue(any('investment_cost' in s['facts'] for s in fresh['signals'] if s['question']=='checkpoint:allocation'))
            else:
                self.assertEqual(sum(g['accepted'] for g in admission['groups']),2,str(output))
                self.assertEqual(len(admission['groups']),3,str(output))
                rejected=next(g for g in admission['groups'] if not g['accepted'])['goal_ids'][0]
                hero=next(g['actor_ref'] for g in admission['raw_reply']['plan']['goals'] if g['id']==rejected)
                self.assertTrue(any(s['question']=='routine:'+hero for s in fresh['signals']),str(output))
                self.assertNotIn(rejected,[g['id'] for g in fresh['campaign']['goals']])
                prepared=next(r for r in requests if r.get('mode')=='prepare_next_turn'
                    and r['request_id']==admission['request_id'])
                covered_refs={g['actor_ref'] for g in fresh['campaign']['goals'] if g['id'].startswith('prepared-')}
                covered_refs.update(g['target_ref'] for g in fresh['campaign']['goals'] if g['id'].startswith('prepared-'))
                for need in prepared['routine_needs']:
                    if need['ref'] in covered_refs:
                        self.assertFalse(any(s['question']=='routine:'+need['ref'] for s in fresh['signals']),str(output))
        # Every native expense already in the foreground DTO precedes its
        # transport; no prepared expense is allowed in that pre-choice history.
        history=fresh['memory'].get('recent_results',[])
        self.assertFalse(any(e.get('action',{}).get('goal_id','').startswith('prepared-') for e in history),str(output))

    def test_pending_crash_invalid_and_oversized_replies_start_ordinary_transport(self):
        for case in ('pending','crash','invalid','oversized'):
            with self.subTest(case=case):self.run_case(case)

    def test_late_background_completes_during_own_turn_without_replacing_fresh_plan(self):
        self.run_case('late')

    def test_ready_town_task_executes_without_second_call_for_covered_need(self):
        self.run_case('ready')

    def run_case(self,case):
        config=json.loads(Path(os.environ['VCMI_NK3_BACKGROUND_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='native-background-'+case+'-',dir=ROOT/'.build/background-proof'))
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/BackgroundSafe.vmap','x') as archive:
            for name,value in safe_map().items():archive.writestr(name,json.dumps(value))
        controller=ROOT/'tests/fixtures/nk3_background_transport.py'
        config.update(profile_template=str(fixture),map_resource='Maps/BackgroundSafe.vmap',controller=[sys.executable,str(controller)],controller_sources=[str(controller),str(ROOT/'tests/fixtures/strategic_intent.py')],
            case_id='background-'+case,max_seconds=20,experience_mode='off',headless=True,review_interval_days=0)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_BACKGROUND_CASE=case,VCMI_AI_OPEN_MAP='1')
        with (output/'driver.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+22
                while process.poll() is None and time.monotonic()<deadline:
                    if case=='late':
                        traces=records(run/'runtime.log','NK3_BACKGROUND')
                        staged=next((t for t in traces if t.get('phase')=='staged' and t.get('observed_day')==1),{})
                        if any(t.get('request_id')==staged.get('request_id') and t.get('phase')=='discard'
                               and t.get('reason') in ('stale_preparation','critical_question') for t in traces):break
                    elif case=='ready':
                        if any(r.get('phase')=='admit' for r in records(run/'runtime.log','NK3_BACKGROUND')) and any(r.get('day')==2 for r in records(run/'runtime.log','NK3_EXECUTION')):break
                    else:
                        if any(q.get('mode')!='prepare_next_turn' and q['identity']['player']==0 and q['identity']['day']==2
                               for q in (json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json'))):break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True);process.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete'],str(output));self.assertTrue(launch['protected_files_unchanged'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        background=[q for q in requests if q.get('mode')=='prepare_next_turn' and q['identity']['player']==0 and q['identity']['day']==1]
        self.assertEqual(len(background),1,str(output))
        ordinary=[q for q in requests if q.get('mode')!='prepare_next_turn' and q['identity']['player']==0 and q['identity']['day']==2]
        if case!='ready':self.assertTrue(ordinary,str(output))
        else:
            self.assertFalse(ordinary,str(output))
            self.assertTrue(any(r.get('phase')=='admit' and r.get('execution_day')==2 for r in records(run/'runtime.log','NK3_BACKGROUND')),str(output))
        if case=='late':
            traces=records(run/'runtime.log','NK3_BACKGROUND');request_id=background[0]['request_id']
            self.assertTrue(any(t.get('phase')=='pending' and t.get('request_id')==request_id for t in traces),str(output))
            self.assertFalse(any(t.get('phase')=='cancel' and t.get('request_id')==request_id for t in traces),str(output))
            completed=[]
            for path in (run/'decisions').glob('*/request.json'):
                if json.loads(path.read_text())['request_id']==request_id:
                    result=path.parent/'result.json'
                    if result.exists():completed.append(json.loads(result.read_text()))
            self.assertEqual([v['status'] for v in completed],['reply_valid'],str(output))
            self.assertTrue(any(t.get('request_id')==request_id and t.get('phase')=='ready' for t in traces),str(output))
            self.assertTrue(any(t.get('request_id')==request_id and t.get('phase')=='discard'
                                and t.get('reason') in ('stale_preparation','critical_question') for t in traces),str(output))
            self.assertFalse(any(t.get('request_id')==request_id and t.get('phase')=='admit' for t in traces),str(output))
            self.assertTrue(any(t.get('day')==2 and t.get('accepted') is True
                                for t in records(run/'runtime.log','NK3_STRATEGY')),str(output))
        print('Native background proof:',case,output,flush=True)
