"""One strategic exchange creates a goal and native play continues on rejection."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a separate NK3 build and private strategic fixture')
class NativeStrategicExchangeTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('VCMI_NK3_HOLDING_CONFIG'),
                         'requires the explicit saved S-duel holding reproduction')
    def test_holding_preserves_movement_after_unproductive_visit(self):
        config=json.loads(Path(os.environ['VCMI_NK3_HOLDING_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-holding-',dir=ROOT/'.build/playtests'))
        print('\nNK3 holding evidence:',output,flush=True)
        # The supplied completed-day-9 save recreates days 10 and 11. This is
        # a separate native-only copy, not the supervised GPT continuation.
        config.update(nk3_mode='native',experience_mode='off',review_interval_days=2,
                      purpose='integration',case_id='nk3-holding',headless=True,max_seconds=30)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35
                while child.poll() is None and time.monotonic()<deadline:
                    state_path=run/'turn-review/state.json'
                    if state_path.exists() and json.loads(state_path.read_text()).get('status')=='paused':break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        state=json.loads((run/'turn-review/state.json').read_text())
        self.assertEqual((state['status'],state['completed_day']),('paused',11),str(output))
        turns=[json.loads(line) for line in (run/'turn-review/turns.jsonl').read_text().splitlines()]
        start=next(t for t in turns if t['day']==10 and t['player']==1 and t['phase']=='start')
        main_id=max(start['heroes'],key=lambda h:h['army_value'])['id']
        for day in (10,11):
            end=next(t for t in turns if t['day']==day and t['player']==1 and t['phase']=='end')
            hero=next(h for h in end['heroes'] if h['id']==main_id)
            self.assertGreater(hero['movement'],0,
                f'day {day}: holding repeated the same visit until movement was exhausted')
            begin=next(t for t in turns if t['day']==day and t['player']==1 and t['phase']=='start')
            movement=next(h for h in begin['heroes'] if h['id']==main_id)['movement']
            self.assertLess(hero['movement'],movement,'new turn incorrectly suppressed every holding attempt')
        # A confirmed approach remains useful. The main hero must still reach
        # the refuge vicinity; suppressing all holding movement cannot pass.
        text=re.sub(r'\x1b\[[0-9;]*m','',(run/'runtime.log').read_text(errors='replace'))
        decoder=json.JSONDecoder();approaches=[]
        for match in re.finditer(r'NK3_EXECUTION (\{)',text):
            try:record=decoder.raw_decode(text[match.start(1):])[0]
            except ValueError:continue
            action=record['action']
            if record['day']==10 and action.get('goal_id')=='strengthen-last-town':
                before,after=action['before']['heroes'][0],action['after']['heroes'][0]
                if before['position']!=after['position']:approaches.append((before,after))
        self.assertTrue(approaches,'holding no longer executes a useful approach to the refuge')

    def test_native_rejection_is_visible_to_next_strategy_request(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-feedback-',dir=ROOT/'.build/playtests'))
        print('\nNK3 feedback evidence:',output,flush=True)
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      controller_sources=[str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      purpose='integration',case_id='nk3-feedback',headless=True,max_seconds=30,
                      decision_timeout_seconds=5,experience_mode='off',review_interval_days=0)
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='rejection_feedback');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        records=[];decoder=json.JSONDecoder()
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+35
                while child.poll() is None and time.monotonic()<deadline:
                    text=(run/'runtime.log').read_text(errors='replace') if (run/'runtime.log').exists() else ''
                    text=re.sub(r'\x1b\[[0-9;]*m','',text);records=[]
                    for match in re.finditer(r'NK3_STRATEGY (\{)',text):
                        try:record=decoder.raw_decode(text[match.start(1):])[0]
                        except ValueError:continue
                        if record.get('requested'):records.append(record)
                    if len(records)>=4:break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        self.assertTrue(json.loads((run/'launch.json').read_text())['cleanup_complete'])
        self.assertTrue(json.loads((run/'launch.json').read_text())['protected_files_unchanged'])
        self.assertGreaterEqual(len(records),4,str(output))
        self.assertTrue(records[0]['accepted'])
        self.assertFalse(records[1]['accepted'])
        self.assertEqual(records[1]['fallback_reason'],'conflicting_hero_obligations')
        requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                        key=lambda x:int(x['request_id'].rsplit(':',1)[1]))
        self.assertEqual(requests[0]['observation'].get('strategy_assignments'),[],
                         'opening hides the explicitly empty native role state')
        expected=[dict(hero_ref=requests[0]['observation']['heroes'][0]['ref'],role='defender')]
        self.assertEqual(requests[1]['observation'].get('strategy_assignments'),expected,
                         'next request hides the accepted roles required for retain')
        self.assertEqual(requests[2]['observation'].get('strategy_assignments'),expected,
                         'rejected roles replaced the authoritative assignments')
        result=next((item for item in requests[2]['memory']['recent_results']
                     if item['outcome']=='strategy_rejected'),None)
        self.assertIsNotNone(result,'next model request hides native strategic rejection')
        self.assertEqual(result['action']['kind'],'strategic_decision')
        self.assertEqual(result['action']['request_id'],requests[1]['request_id'])
        self.assertEqual(result['action']['reason'],'conflicting_hero_obligations')
        self.assertEqual(result['action']['installed_revision'],records[0]['revision'])
        self.assertEqual([g['id'] for g in result['action']['proposed_goals']],['hold-a','hold-b'])
        self.assertTrue(records[2]['accepted'],'controller did not use native rejection feedback')
        self.assertEqual(requests[3]['observation']['strategy_assignments'],
                         [dict(hero_ref=requests[0]['observation']['heroes'][0]['ref'],role='main')])
        self.assertTrue(records[3]['accepted'],'native rejected retain with the exact accepted role echo')
        echoed=next(json.loads(p.read_text()) for p in (run/'decisions').glob('*/stdout.bin')
                    if json.loads(p.read_text()).get('request_id')==requests[3]['request_id'])
        self.assertEqual(echoed['decision'],'retain')


    def test_rejected_initial_reply_keeps_absent_course_null_in_next_request(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-null-course-',dir=ROOT/'.build/playtests'))
        print('\nNK3 null-course evidence:',output,flush=True)
        script=output/'no-answer.py';script.write_text('import sys; sys.stdin.read(); sys.exit(75)')
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
            controller=[sys.executable,str(script)],controller_sources=[str(script)],
            purpose='integration',case_id='nk3-null-course',headless=True,max_seconds=12,
            decision_timeout_seconds=2,experience_mode='off',review_interval_days=0)
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                env={**os.environ,'VCMI_AI_OPEN_MAP':'1'},stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+17
                while child.poll() is None and time.monotonic()<deadline:
                    files=list((run/'decisions').glob('*/result.json'))
                    if len(files)>=2 and all(json.loads(p.read_text()).get('status')!='started' for p in files):break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertGreaterEqual(len(requests),2,'native proof did not reach a later permitted request')
        for request in requests:self.assertIsNone(request['strategic_intent'])

    def test_strategy_goal_and_invalid_reply_fallback_through_recorder(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-strategy-',dir=ROOT/'.build/playtests'))
        print('\nNK3 strategy evidence:',output,flush=True)
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      controller_sources=[str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],
                      purpose='integration',case_id='nk3-strategy',headless=True,max_seconds=25,
                      decision_timeout_seconds=1,experience_mode='off')
        config.pop('save_resource',None)
        for mode in ['valid','resource','stale','invalid','timeout']:
            with self.subTest(mode=mode):
                goal_id='supply' if mode=='resource' else 'guild'
                path=output/(mode+'.json');path.write_text(json.dumps(config));run=output/mode
                subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
                env=dict(os.environ,NK3_PROBE_MODE=mode);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
                with (run/'driver.log').open('w') as log:
                    child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        deadline=time.monotonic()+30
                        while child.poll() is None and time.monotonic()<deadline:
                            records=campaign_records(run)
                            if mode in ('valid','resource') and any(r['statuses'].get(goal_id,{}).get('state')=='completed' for r in records):break
                            logpath=run/'engine-logs/VCMI_Client_log.txt'
                            if mode not in ('valid','resource') and logpath.exists():
                                text=logpath.read_text(errors='replace')
                                if 'NK3_STRATEGY' in text and 'Player 0 (red) ends turn' in text:break
                            time.sleep(.03)
                    finally:
                        (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
                decisions=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/result.json')),key=lambda d:d['started_at'])
                self.assertTrue(decisions,'no actual strategic exchange')
                first=decisions[0]
                self.assertEqual(first['protocol'],2)
                self.assertEqual(first['action_count'],0)
                request=json.loads((run/'decisions'/first['decision_id']/'request.json').read_text())
                self.assertNotIn('actions',request)
                text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
                if mode in ('valid','resource'):
                    self.assertEqual(first['status'],'reply_valid')
                    self.assertTrue(any(r['statuses'].get(goal_id,{}).get('state')=='completed' for r in campaign_records(run)),
                                    'structured goal did not execute')
                    if mode=='valid':self.assertIn('will build building.core.castle.mageGuild1.name',text)
                    else:self.assertEqual(campaign_records(run)[0]['statuses']['supply']['state'],'ready','existing gold bypassed actual pickup')
                    self.assertGreaterEqual(len(request['observation']['forecasts']['alternatives']),2)
                else:
                    self.assertNotEqual(first['status'],'reply_valid')
                    self.assertFalse(campaign_records(run),'invalid model policy was partially installed')
                    self.assertIn('NK3_NATIVE',text)
                    self.assertIn('will build ',text,'fallback lost useful native work')
                    openings=0
                    for decision in decisions:
                        entry=json.loads((run/'decisions'/decision['decision_id']/'request.json').read_text())
                        openings+=any(s['question']=='opening' for s in entry['signals'])
                    self.assertEqual(openings,1,'same failed opening question retried')
                launch=json.loads((run/'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
                self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])


if __name__=='__main__':unittest.main()
