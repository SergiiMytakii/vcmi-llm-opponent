"""Guide access through the controller's actual stdin and CLI process boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture
from test_nullkiller3_controller import strategic_request

ROOT = Path(__file__).resolve().parents[1]
MODEL = '''
import json,os,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin);a=sys.argv
s=json.loads(pathlib.Path(a[a.index('--output-schema')+1]).read_text())
instructions=next(v.split('=',1)[1] for v in a if v.startswith('model_instructions_file='))
i=pathlib.Path(json.loads(instructions)).read_text()
p=pathlib.Path(os.environ['CAPTURE']);n=len(list(p.glob('call-*.json')))+1
(p/f'call-{n}.json').write_text(json.dumps({'request':r,'schema':s,'instructions':i}))
reply=json.loads(os.environ['FINAL_REPLY'])
mode=os.environ.get('GUIDE_TEST_MODE','decision')
answer={'kind':'decision','decision':reply,'guide_request':None}
if mode=='off':answer=reply
if mode not in ('decision','off') and n==1:
 answer={'kind':'guide_request','decision':None,'guide_request':{'ids':['opening','defense'],'reason':'Compare current risks'}}
 if mode=='duplicate':answer['guide_request']['ids']=['opening','opening']
 if mode=='unknown':answer['guide_request']['ids']=['secret']
 if mode=='inconsistent':answer['decision']=reply
 if mode=='empty_reason':answer['guide_request']['reason']=' '
if n==2:
 if mode=='recursive':answer={'kind':'guide_request','decision':None,'guide_request':{'ids':['recovery'],'reason':'Again'}}
 else:answer=reply
 if mode=='second_exit':sys.exit(4)
 if mode=='second_timeout':
  import time
  (p/'second-pid').write_text(str(os.getpid()));time.sleep(10)
if mode=='first_exhausted':usage={'input_tokens':11960,'output_tokens':40}
elif mode=='first_tight':usage={'input_tokens':11000,'output_tokens':40}
elif mode=='first_unknown':usage=None
elif n==2:usage={'input_tokens':180,'output_tokens':60}
else:usage={'input_tokens':120,'output_tokens':40}
pathlib.Path(a[a.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':usage}))
'''

def final_reply(request):
    return dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
        reason='Develop income',evidence_refs=['town:object:1'],victory_method='Fund conquest',assignments=[],
        alternatives=[dict(approach='economy',benefit='Income',cost='Resources',uncertainty='Threats'),
                      dict(approach='offense',benefit='Pressure',cost='Army',uncertainty='Routes')],
        reconsider_when=[dict(goal_id='guild',kind='deadline_missed')],
        plan=dict(version=3,revision=1,approach='economy',horizon_days=5,
            goals=[dict(id='guild',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=3,
                priority=80,building_id=0,min_army_value=0,depends_on=[],required_capabilities=['build'],
                complete_when=dict(kind='building_present',value=0))],reserves=[],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1'])))

class StrategyGuideTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.request=strategic_request()
        self.env={**os.environ,**codex_fixture(self.folder,MODEL),
            'CAPTURE':str(self.folder),'FINAL_REPLY':json.dumps(final_reply(self.request)),
            'VCMI_EXPERIENCE_MODE':'off','VCMI_STRATEGY_GUIDE_MODE':'on',
            'VCMI_PLAYTEST_DECISION_DIR':str(self.folder)}
        self.env.pop('VCMI_STRATEGY_GUIDE',None)

    def exchange(self):
        return subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(self.request),
            text=True,capture_output=True,timeout=10,env=self.env)

    def test_catalog_only_then_one_decision(self):
        result=self.exchange()
        self.assertEqual(result.returncode,0,result.stderr)
        reply=json.loads(result.stdout);info=json.loads(result.stderr)
        self.assertEqual(reply['identity'],self.request['identity'])
        self.assertEqual(reply['usage'],dict(input_tokens=120,output_tokens=40,known=True))
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
        call=json.loads((self.folder/'call-1.json').read_text())
        self.assertIn('opening',call['instructions'])
        self.assertNotIn('rules/opening.md',call['instructions'])
        self.assertEqual(info['strategy_guide']['requested_ids'],[])

    def test_selected_cards_only_and_usage_of_both_calls(self):
        self.env['GUIDE_TEST_MODE']='consult'
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['usage'],dict(input_tokens=300,output_tokens=100,known=True))
        calls=[json.loads((self.folder/f'call-{n}.json').read_text()) for n in (1,2)]
        self.assertEqual(calls[0]['request'],calls[1]['request'])
        for name in ('opening','defense'):
            body=(ROOT/'controller/strategy_guide/rules'/f'{name}.md').read_text()
            self.assertNotIn(body,calls[0]['instructions'])
            # Cards appear as JSON strings in the separate consultation result.
            self.assertIn(json.dumps(body,ensure_ascii=False)[1:-1],calls[1]['instructions'])
        self.assertNotIn('rules/recovery.md',calls[1]['instructions'])
        info=json.loads(result.stderr)
        self.assertEqual(info['strategy_guide']['requested_ids'],['opening','defense'])
        self.assertEqual(len(info['model_calls']),2)
        for number in (1,2):
            self.assertTrue((self.folder/f'model-call-{number}'/'codex-answer.json').is_file())
            self.assertTrue((self.folder/f'model-call-{number}'/'codex-instructions.txt').is_file())

    def test_bad_requests_and_budget_stop_before_second_call(self):
        for mode in ('duplicate','unknown','inconsistent','empty_reason','first_unknown','first_exhausted','first_tight'):
            with self.subTest(mode=mode):
                for capture in self.folder.glob('call-*.json'):capture.unlink()
                for call in self.folder.glob('model-call-*'):
                    import shutil
                    shutil.rmtree(call)
                self.env['GUIDE_TEST_MODE']=mode
                result=self.exchange()
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')
                self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
                info=json.loads(result.stderr)
                if mode!='first_unknown':self.assertEqual(info['usage']['output_tokens'],40)

    def test_second_failure_retains_first_cost_and_never_becomes_a_command(self):
        self.env['GUIDE_TEST_MODE']='second_exit'
        result=self.exchange()
        self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'')
        info=json.loads(result.stderr)
        self.assertEqual(info['usage'],dict(input_tokens=120,output_tokens=40))
        self.assertFalse(info['usage_complete'])
        self.assertEqual(info['model_calls'][1]['status'],'failed')

    def test_second_consultation_is_impossible(self):
        self.env['GUIDE_TEST_MODE']='recursive'
        result=self.exchange()
        self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'')
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),2)
        self.assertEqual(json.loads(result.stderr)['usage'],dict(input_tokens=300,output_tokens=100))

    def test_shared_deadline_reaps_second_process(self):
        self.env['GUIDE_TEST_MODE']='second_timeout'
        self.request['budget']['wait_ms']=2700
        result=self.exchange();self.assertEqual(result.returncode,75,result.stderr)
        self.assertEqual(result.stdout,'')
        self.assertEqual(json.loads(result.stderr)['usage'],dict(input_tokens=120,output_tokens=40))
        if os.name!='nt':
            pid=int((self.folder/'second-pid').read_text())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_editing_card_changes_the_actual_consultation(self):
        import shutil
        guide=self.folder/'guide';shutil.copytree(ROOT/'controller/strategy_guide',guide)
        (guide/'rules/opening.md').write_text('# Unique edited opening\nUse current routes.\n')
        self.env.update(VCMI_STRATEGY_GUIDE=str(guide),GUIDE_TEST_MODE='consult')
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Unique edited opening',json.loads((self.folder/'call-2.json').read_text())['instructions'])

    def test_oversized_allowed_consultation_is_rejected_before_paid_call(self):
        import shutil
        guide=self.folder/'guide';shutil.copytree(ROOT/'controller/strategy_guide',guide)
        for name in ('opening','development','defense'):
            (guide/'rules'/f'{name}.md').write_bytes(b'x'*4096)
        self.env['VCMI_STRATEGY_GUIDE']=str(guide)
        result=self.exchange()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),0)
        self.assertIn('consultation exceeds byte limit',json.loads(result.stderr)['reason'])

    def test_off_mode_uses_one_normal_decision_without_catalog(self):
        self.env.update(VCMI_STRATEGY_GUIDE_MODE='off',GUIDE_TEST_MODE='off')
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
        call=json.loads((self.folder/'call-1.json').read_text())
        self.assertNotIn('Strategy guide catalog',call['instructions'])
        self.assertNotIn('kind',call['schema']['properties'])
        self.assertEqual(json.loads(result.stderr)['strategy_guide']['mode'],'off')

    def test_catalog_rejects_escape_symlink_duplicates_sizes_and_non_utf8(self):
        import shutil
        from controller.strategy_guide import StrategyGuide
        for mode in ('escape','symlink','duplicate','oversize','utf8'):
            with self.subTest(mode=mode):
                guide=self.folder/mode;shutil.copytree(ROOT/'controller/strategy_guide',guide)
                catalog=json.loads((guide/'catalog.json').read_text())
                card=guide/'rules/opening.md'
                if mode=='escape':catalog['cards'][0]['file']='rules/../../outside.md'
                if mode=='duplicate':catalog['cards'][1]['id']='opening'
                if mode=='symlink':
                    card.unlink();card.symlink_to(ROOT/'controller/strategy_guide/rules/opening.md')
                if mode=='oversize':card.write_bytes(b'x'*4097)
                if mode=='utf8':card.write_bytes(b'\xff')
                (guide/'catalog.json').write_text(json.dumps(catalog))
                with self.assertRaises((ValueError,OSError)):StrategyGuide(guide)

if __name__=='__main__':unittest.main()
