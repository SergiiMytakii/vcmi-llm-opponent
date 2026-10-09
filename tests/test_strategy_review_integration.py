"""Refused conquest review returns next turn and executes its named correction."""
import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from codex_fixture import codex_fixture
from test_background_integration import records
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get('VCMI_NK3_REVIEW_CONFIG'),'requires isolated runtime')
class StrategyReviewIntegrationTest(unittest.TestCase):
    def test_save_during_review_cancels_exchange_and_reopens_next_turn(self):
        config=json.loads(Path(os.environ['VCMI_NK3_REVIEW_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='review-save-',dir=ROOT/'.build/strategy-loop'))
        env={**os.environ,**codex_fixture(output,'''
import json,os,pathlib,sys,time
if sys.argv[1:]==['--version']:print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
sys.path.insert(0,os.environ['REVIEW_FIXTURES'])
from nk3_strategy_review import answer
if r.get('mode')=='prepare_next_turn':sys.exit(1)
if os.environ.get('REVIEW_SAVING')=='1' and any(s['question']=='strategy:no_progress:conquest' for s in r['signals']):time.sleep(12)
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer(r)))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':10}}))
'''),'REVIEW_FIXTURES':str(ROOT/'tests/fixtures'),'VCMI_AI_OPEN_MAP':'1'}
        config.update(players={'blue':'Nullkiller3','red':'EmptyAI'},max_seconds=60,
            case_id='review-save',headless=False,strategy_guide={'mode':'off'},game_rules={'mode':'off'},purpose='integration')
        def prepare(name):
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            return run
        def requests(run):
            return [json.loads(p.read_text()) for p in run.glob('decisions/*/request.json')]
        def drive(run,saving):
            sent=None;reached=False
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                    env=dict(env,REVIEW_SAVING='1' if saving else '0'),stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+62
                    while child.poll() is None and time.monotonic()<deadline:
                        if saving:
                            reviews=[r for r in requests(run) if not r.get('mode') and any(s['question']=='strategy:no_progress:conquest' for s in r['signals'])]
                            if reviews and sent is None:
                                sent=reviews[0];child.stdin.write(b'save Saves/StrategyReviewExchange\n');child.stdin.flush()
                            native=run/'engine-logs/VCMI_Client_log.txt'
                            reached=native.exists() and 'Game has been successfully saved!' in native.read_text(errors='replace')
                        else:
                            reached=any(e.get('action',{}).get('goal_id')=='review-attack' and e['action'].get('acknowledgment')=='acknowledged' for e in records(run/'runtime.log','NK3_EXECUTION'))
                        if reached:break
                        time.sleep(.1)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15);child.stdin.close()
            self.assertTrue(reached,str(run));self.assertEqual(child.returncode,0,str(run))
            launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            return sent
        first=prepare('save');before=drive(first,True)
        self.assertFalse(any(s.get('accepted') and s.get('request_id')==before['request_id'] for s in records(first/'runtime.log','NK3_STRATEGY')))
        config.update(profile_template=str(first/'profile'),save_resource='Saves/StrategyReviewExchange.vsgm1')
        loaded=prepare('load');drive(loaded,False)
        restored=requests(loaded);day=before['identity']['day']
        exact=next(s for s in before['signals'] if s['question']=='strategy:no_progress:conquest')
        self.assertFalse(any(not r.get('mode') and r['identity']['day']==day and exact in r['signals'] for r in restored))
        self.assertTrue(any(r['identity']['day']>day and any(s['question']==exact['question'] for s in r['signals']) for r in restored))
        accepted=[s for s in records(loaded/'runtime.log','NK3_STRATEGY') if s.get('accepted') and s['day']>day]
        receipts=[e['action'] for e in records(loaded/'runtime.log','NK3_EXECUTION') if e.get('action',{}).get('goal_id')=='review-attack' and e['action'].get('acknowledgment')=='acknowledged']
        self.assertTrue(any(a['campaign_revision']==s['revision'] for a in receipts for s in accepted),str(loaded))
        print('Strategy review in-flight save proof:',output,flush=True)

    def test_controller_refusal_returns_next_turn_and_corrected_operation_executes(self):
        config=json.loads(Path(os.environ['VCMI_NK3_REVIEW_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='review-caller-',dir=ROOT/'.build/strategy-loop'))
        env={**os.environ,**codex_fixture(output,'''
import json,os,pathlib,sys
if sys.argv[1:]==['--version']:print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
sys.path.insert(0,os.environ['REVIEW_FIXTURES'])
from nk3_strategy_review import answer
if r.get('mode')=='prepare_next_turn':sys.exit(1)
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer(r)))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':10}}))
'''), 'REVIEW_FIXTURES':str(ROOT/'tests/fixtures'),'VCMI_AI_OPEN_MAP':'1',
             'VCMI_STRATEGY_GUIDE_MODE':'off','VCMI_GAME_RULES_MODE':'off'}
        config.update(players={'blue':'Nullkiller3','red':'EmptyAI'},max_seconds=55,case_id='review-caller',
                      strategy_guide={'mode':'off'},game_rules={'mode':'off'},purpose='integration')
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),
                        '--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+58
                while child.poll() is None and time.monotonic()<deadline:
                    if any(e.get('action',{}).get('goal_id')=='review-attack' and e['action'].get('acknowledgment')=='acknowledged'
                           for e in records(run/'runtime.log','NK3_EXECUTION')):break
                    time.sleep(.1)
            finally:(run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        print('Strategy review caller proof:',output,flush=True)
        strategy=records(run/'runtime.log','NK3_STRATEGY')
        rejected=[s for s in strategy if s.get('fallback_reason')=='unsupported_wait_purpose']
        self.assertTrue(rejected,str(output))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        retried=[r for r in requests if r['identity']['day']>rejected[0]['day'] and any(s['question']=='strategy:no_progress:conquest' for s in r['signals'])]
        self.assertTrue(retried,str(output))
        self.assertEqual(retried[0]['observation']['decision_feedback']['failure']['code'],'unsupported_wait_purpose')
        accepted=[s for s in strategy if s.get('accepted') and s['day']>=5]
        self.assertTrue(accepted,str(output))
        receipts=[e for e in records(run/'runtime.log','NK3_EXECUTION') if e.get('action',{}).get('goal_id')=='review-attack' and e['action'].get('acknowledgment')=='acknowledged']
        self.assertTrue(receipts,str(output))
        self.assertEqual(receipts[0]['action']['campaign_revision'],accepted[0]['revision'])
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
