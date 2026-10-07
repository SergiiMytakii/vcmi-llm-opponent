"""Guide access through the controller's actual stdin and CLI process boundary."""
from fixtures.strategic_intent import with_intent
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
MODEL = r'''
import json,os,pathlib,sys,subprocess
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin);a=sys.argv
config={v.split('=',1)[0]:json.loads(v.split('=',1)[1]) for v in a if '=' in v}
i=pathlib.Path(config['model_instructions_file']).read_text()
p=pathlib.Path(os.environ['CAPTURE']);n=len(list(p.glob('call-*.json')))+1
(p/f'call-{n}.json').write_text(json.dumps({'request':r,'schema':json.loads(pathlib.Path(a[a.index('--output-schema')+1]).read_text()),'instructions':i}))
for namespace,tool,mode,ids_default in [('strategy_guide','read_strategy_guide','GUIDE','["opening","defense"]'),('game_rules','read_game_rules','RULES','["day_and_week","town_economy"]')]:
 if os.environ.get(mode+'_TEST_MODE') not in ('consult','consult_timeout'):continue
 key='mcp_servers.nk3_'+namespace+'.'
 command=[config[key+'command']]+config[key+'args']
 child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
 def call(method,params):
  child.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n');child.stdin.flush()
  return json.loads(child.stdout.readline())
 call('initialize',{'protocolVersion':'2024-11-05'})
 tools=call('tools/list',{})
 (p/(namespace+'-tools.json')).write_text(json.dumps(tools))
 result=call('tools/call',{'name':tool,'arguments':{'ids':json.loads(os.environ.get(mode+'_TEST_IDS',ids_default))}})
 if os.environ.get(mode+'_TEST_MODE')=='consult_timeout':
  import time
  (p/'model-pid').write_text(str(os.getpid()));(p/'tool-pid').write_text(str(child.pid));time.sleep(10)
 child.stdin.close();child.wait(timeout=2)
 (p/('tool-result.json' if namespace=='strategy_guide' else 'rules-result.json')).write_text(json.dumps(result))
 if 'error' in result:sys.exit(4)
 print(json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call','server':'nk3_'+namespace,'tool':tool}}))
pathlib.Path(a[a.index('-o')+1]).write_text(os.environ['FINAL_REPLY'])
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':40}}))
'''

def final_reply(request):
    return with_intent(request,dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
        reason='Develop income',evidence_refs=['town:object:1'],victory_method='Fund conquest',assignments=[],
        alternatives=[dict(approach='economy',benefit='Income',cost='Resources',uncertainty='Threats'),
                      dict(approach='offense',benefit='Pressure',cost='Army',uncertainty='Routes')],
        reconsider_when=[dict(goal_id='guild',kind='deadline_missed')],
        plan=dict(version=3,revision=1,approach='economy',horizon_days=5,
            goals=[dict(id='guild',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=3,
                priority=80,building_id=0,min_army_value=0,depends_on=[],required_capabilities=['build'],
                complete_when=dict(kind='building_present',value=0))],reserves=[],
            policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))))

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
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        call=json.loads((self.folder/'call-1.json').read_text())
        self.assertNotIn('kind',call['schema']['properties'])
        self.assertIn('read_strategy_guide',call['instructions'])
        self.assertEqual(json.loads(result.stderr)['strategy_guide']['requested_ids'],[])

    def test_selected_cards_inside_single_call_even_with_small_budget(self):
        self.env['GUIDE_TEST_MODE']='consult';self.request['budget']['tokens']=1
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
        self.assertEqual(json.loads(result.stdout)['usage'],dict(input_tokens=120,output_tokens=40,known=True))
        info=json.loads(result.stderr)
        self.assertEqual(info['strategy_guide']['requested_ids'],['opening','defense'])
        sections=json.loads(json.loads((self.folder/'tool-result.json').read_text())['result']['content'][0]['text'])
        self.assertEqual([s['id'] for s in sections],['opening','defense'])
        self.assertEqual(sections[0]['text'],(ROOT/'controller/strategy_guide/rules/opening.md').read_text())

    def test_invalid_tool_selection_is_rejected(self):
        self.env.update(GUIDE_TEST_MODE='consult',GUIDE_TEST_IDS='["opening","opening"]')
        result=self.exchange();self.assertNotEqual(result.returncode,0)
        self.assertIn('error',json.loads((self.folder/'tool-result.json').read_text()))
        self.assertEqual(result.stdout,'')

    def test_global_course_advice_is_loaded_on_demand_in_the_same_call(self):
        self.env.update(GUIDE_TEST_MODE='consult',GUIDE_TEST_IDS='["global_strategy"]')
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
        sections=json.loads(json.loads((self.folder/'tool-result.json').read_text())['result']['content'][0]['text'])
        self.assertEqual([s['id'] for s in sections],['global_strategy'])
        self.assertEqual(sections[0]['text'],(ROOT/'controller/strategy_guide/rules/global_strategy.md').read_text())
        call=json.loads((self.folder/'call-1.json').read_text())
        self.assertNotIn('production-led expansion',call['instructions'])

    def test_off_mode_uses_one_normal_decision_without_catalog(self):
        self.env['VCMI_STRATEGY_GUIDE_MODE']='off'
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Strategy guide catalog',json.loads((self.folder/'call-1.json').read_text())['instructions'])

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
