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
read_sections=[]
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
 batches=json.loads(os.environ.get(mode+'_TEST_BATCHES','null')) or [json.loads(os.environ.get(mode+'_TEST_IDS',ids_default))]
 results=[]
 for ids in batches:
  result=call('tools/call',{'name':tool,'arguments':{'ids':ids}})
  results.append(result)
  if 'error' not in result:
   read_sections.extend(json.loads(result['result']['content'][0]['text']))
  if os.environ.get(mode+'_TEST_MODE')=='consult_timeout':
   import time
   (p/'model-pid').write_text(str(os.getpid()));(p/'tool-pid').write_text(str(child.pid));time.sleep(10)
  if 'error' in result:break
  print(json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call','server':'nk3_'+namespace,'tool':tool}}))
 child.stdin.close();child.wait(timeout=2)
 (p/('tool-result.json' if namespace=='strategy_guide' else 'rules-result.json')).write_text(json.dumps(result))
 (p/(namespace+'-results.json')).write_text(json.dumps(results))
 if 'error' in result:sys.exit(4)
reply=json.loads(os.environ['FINAL_REPLY'])
if os.environ.get('TEST_CONTINUITY')=='on':
 reply['reason']=read_sections[0]['text'].splitlines()[0]+' -> '+read_sections[-1]['text'].splitlines()[0]
pathlib.Path(a[a.index('-o')+1]).write_text(json.dumps(reply))
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

    def test_successive_reference_reads_share_one_model_decision_and_keep_earlier_results(self):
        guide_batches=[['opening','defense','exploration'],['endgame','development'],['global_strategy']]
        rules_batches=[['hero_army','town_economy','combat_strength'],['mana_magic']]
        self.env.update(GUIDE_TEST_MODE='consult',RULES_TEST_MODE='consult',
            VCMI_GAME_RULES_MODE='on',GUIDE_TEST_BATCHES=json.dumps(guide_batches),
            RULES_TEST_BATCHES=json.dumps(rules_batches),TEST_CONTINUITY='on')
        self.env.pop('VCMI_GAME_RULES',None)
        result=self.exchange();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(list(self.folder.glob('call-*.json'))),1)
        reply=json.loads(result.stdout)
        self.assertEqual(reply['request_id'],self.request['request_id'])
        self.assertEqual(reply['identity'],self.request['identity'])
        # The final reply consumes text from the first and last tool reads.
        self.assertEqual(reply['reason'],'# Opening -> # Mana and magic readiness')
        info=json.loads(result.stderr)
        for namespace,batches in [('strategy_guide',guide_batches),('game_rules',rules_batches)]:
            self.assertEqual([c['ids'] for c in info[namespace]['calls']],batches)
            self.assertEqual(info[namespace]['requested_ids'],[i for batch in batches for i in batch])
            responses=json.loads((self.folder/(namespace+'-results.json')).read_text())
            self.assertEqual(len(responses),len(batches))
            for response,ids in zip(responses,batches):
                sections=json.loads(response['result']['content'][0]['text'])
                self.assertEqual([s['id'] for s in sections],ids)
                for section in sections:
                    self.assertEqual(section['text'],(ROOT/'controller'/namespace/section['file']).read_text())
        events=[json.loads(line) for line in (self.folder/'model-call-1/codex-events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e.get('type')=='turn.completed' for e in events),1)
        self.assertEqual(sum(e.get('item',{}).get('type')=='mcp_tool_call' for e in events),5)

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
