"""Next-turn decisions retain observed identity and the accepted global course."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture
from controller.native_strategy import validate_request, validate_reply, reply_schema
import test_global_strategy_controller
from test_strategy_guide import final_reply


def prepared():
    request=test_global_strategy_controller.GlobalStrategyControllerTest().installed()
    request.update(mode='prepare_next_turn',execution_day=2,intent_revision=7,
                   strategic_review=False,allowed_actor_refs=['object:0'],allowed_target_refs=['object:1'])
    request['observation']['strategy_assignments']=[]
    request['campaign']=final_reply(request)['plan']
    request['identity']['revision']=request['campaign']['revision']
    return request


def answer(request):
    reply=copy.deepcopy(final_reply(request))
    reply.update(mode='prepare_next_turn',execution_day=2,intent_revision=7)
    reply['plan']['revision']=request['identity']['revision']+1
    reply['plan']['policy']=copy.deepcopy(request['campaign']['policy'])
    reply['assignments']=[];reply['alternatives']=[]
    reply['plan']['goals'][0]['deadline_day']=7
    return reply


class BackgroundControllerTest(unittest.TestCase):
    def test_background_effort_reaches_cli_and_success_or_failure_diagnostics(self):
        request=prepared()
        with tempfile.TemporaryDirectory() as folder:
            reply_path=Path(folder)/'answer.json'
            args_path=Path(folder)/'args.json'
            env=codex_fixture(Path(folder), '''
import json,os,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
pathlib.Path(os.environ['NK3_ARGS']).write_text(json.dumps(sys.argv))
if os.environ['NK3_FAIL']=='1':sys.exit(4)
reply=json.loads(pathlib.Path(os.environ['NK3_ANSWER']).read_text())
schema=json.loads(pathlib.Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
if 'kind' in schema['properties']:reply={'kind':'decision','decision':reply,'guide_request':None}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':40}}))
''')
            for background in (True,False):
                current=copy.deepcopy(request)
                reply=answer(request)
                if not background:
                    for key in ('mode','execution_day','intent_revision','strategic_review','allowed_actor_refs','allowed_target_refs'):
                        current.pop(key)
                    for key in ('mode','execution_day','intent_revision'):reply.pop(key)
                    reply['plan']['goals'][0]['deadline_day']=6
                    reply['alternatives']=[dict(approach='economy',benefit='Build',cost='Funds',uncertainty='Enemy'),
                                           dict(approach='offense',benefit='Conquest',cost='Army',uncertainty='Route')]
                reply_path.write_text(json.dumps(reply))
                for fail in (False,True):
                    with self.subTest(background=background,fail=fail):
                        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'controller/main.py')],
                            input=json.dumps(current),text=True,capture_output=True,timeout=10,
                            env={**os.environ,**env,'VCMI_EXPERIENCE_MODE':'off','NK3_ARGS':str(args_path),
                                 'NK3_ANSWER':str(reply_path),'NK3_FAIL':str(int(fail))})
                        metadata=json.loads(result.stderr.splitlines()[-1])
                        expected='low' if background else 'none'
                        self.assertIn('model_reasoning_effort="'+expected+'"',json.loads(args_path.read_text()))
                        self.assertEqual(metadata['requested_reasoning_effort'],expected)
                        self.assertEqual(result.returncode==0,not fail,result.stderr)
                        if not fail:self.assertEqual(metadata['reasoning_effort'],expected)

    def test_routine_next_day_is_complete_without_global_comparison(self):
        request=prepared();validate_request(request)
        reply=answer(request)
        self.assertIs(validate_reply(request,reply),reply)
        self.assertEqual(reply['identity']['day'],1)
        self.assertEqual(reply_schema(request)['properties']['alternatives']['maxItems'],0)
        self.assertEqual(reply_schema(request)['properties']['decision']['enum'],['revise'])
        self.assertTrue(all(option.get('type')!='null' for option in reply_schema(request)['properties']['plan']['anyOf']))

    def test_routine_native_projection_has_no_global_overview(self):
        request=prepared();request['observation']['map_overview']=None
        validate_request(request);validate_reply(request,answer(request))

    def test_unknown_mode_day_or_revision_cannot_relabel_observation(self):
        request=prepared()
        for patch in ({'mode':'other'}, {'execution_day':1}, {'execution_day':3}, {'intent_revision':6}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                validate_request(dict(request,**patch))
        for patch in ({'execution_day':1},{'intent_revision':8},{'identity':dict(request['identity'],day=2)}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                validate_reply(request,dict(answer(request),**patch))

    def test_routine_cannot_change_roles_policy_or_global_course(self):
        request=prepared()
        for mutate in ('roles','policy','course','target'):
            reply=answer(request)
            if mutate=='roles':reply['assignments']=[dict(hero_ref='object:0',role='main')]
            elif mutate=='policy':reply['plan']['policy']['max_loss_ratio']=.4
            elif mutate=='course':reply['strategy_update']['decision']='revise'
            else:reply['plan']['goals'][0]['target_ref']='unknown'
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):validate_reply(request,reply)

    def test_ordinary_reply_keeps_existing_contract(self):
        request=prepared();request.pop('mode')
        with self.assertRaises(ValueError):validate_reply(request,answer(request))
