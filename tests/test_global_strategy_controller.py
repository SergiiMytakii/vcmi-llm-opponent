"""Selected global courses survive an independent operational revision."""
import copy
import unittest
from controller.native_strategy import validate_reply, validate_request
from test_nullkiller3_controller import strategic_request
from test_strategy_guide import final_reply
from fixtures.strategic_intent import with_intent


class GlobalStrategyControllerTest(unittest.TestCase):
    def test_initial_course_and_operation_are_accepted_together(self):
        request=strategic_request();request['strategic_intent']=None
        reply=with_intent(request,final_reply(request))
        self.assertIs(validate_reply(request,reply),reply)
        self.assertEqual(reply['operation_focus']['revision'],1)
        self.assertEqual(len(reply['strategy_update']['selected']['milestones']),3)

    def test_valid_large_course_reaches_native_transport_with_usage(self):
        import json, os, subprocess, sys
        from pathlib import Path
        driver=Path(os.environ.get('EXCHANGE_DRIVER', '.build/exchange-driver'))
        if not driver.is_file():self.skipTest('requires standalone exchange driver')
        request=strategic_request();reply=final_reply(request)
        selected=reply['strategy_update']['selected']
        text='Ж'*160
        selected['assumptions']=[dict(text=text,evidence_refs=['observation:day'],uncertainty=text) for _ in range(8)]
        selected['objective']=selected['selection_reason']=text
        validate_reply(request,reply)
        reply['usage']=dict(input_tokens=1000000000,output_tokens=1000000000,known=True)
        payload=json.dumps(reply,ensure_ascii=False,separators=(',',':'))+'\n'
        self.assertGreater(len(payload.encode()),8192)
        result=subprocess.run([str(driver),'2000',sys.executable,'-c',
            'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'],
            input=payload,text=True,capture_output=True,timeout=5,
            env={**os.environ,'EXCHANGE_REPLY_BYTES':'33792'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),reply)

    def test_model_schema_rejects_inconsistent_milestone_roles(self):
        from controller.native_strategy import reply_schema
        from controller.strategy import _validate_shape
        request=strategic_request();schema=reply_schema(request)["properties"]["strategy_update"]["properties"]["selected"]["anyOf"][1]["properties"]["milestones"]["items"]["properties"]["complete_when"]
        cases=[dict(kind='army_at_least',target_ref='object:0',actor_ref='object:0',value=5000),
               dict(kind='army_at_least',target_ref=None,actor_ref=None,value=5000),
               dict(kind='building_present',target_ref='object:1',actor_ref='object:0',value=0),
               dict(kind='site_visited',target_ref='object:1',actor_ref=None,value=0),
               dict(kind='passage_explored',target_ref='object:1',actor_ref='object:0',value=1)]
        for predicate in cases:
            answer=final_reply(request)
            answer['strategy_update']['selected']['milestones'][0]['complete_when']=predicate
            with self.subTest(predicate=predicate),self.assertRaises(ValueError):
                _validate_shape(predicate,schema)
        answer=final_reply(request)
        answer['strategy_update']['selected']['milestones'][0]['complete_when']=dict(
            kind='army_at_least',target_ref=None,actor_ref='object:0',value=5000)
        _validate_shape(answer["strategy_update"]["selected"]["milestones"][0]["complete_when"],schema)
        validate_reply(request,answer)

    def installed(self):
        request=strategic_request()
        selected=final_reply(request)['strategy_update']['selected']
        request['strategic_intent']=dict(selected,version=1,revision=7,adopted_day=1,progress=[],bindings=[])
        return request

    def test_operation_revision_keeps_course_without_implicit_replacement(self):
        request=self.installed();before=copy.deepcopy(request['strategic_intent'])
        reply=final_reply(request)
        self.assertEqual(reply['strategy_update']['decision'],'keep')
        self.assertEqual(reply['decision'],'revise')
        validate_reply(request,reply)
        self.assertEqual(request['strategic_intent'],before)
        for patch in ({'selected':before}, {'base_revision':6}, {'change_reason':'Silently replace the objective'}):
            bad=copy.deepcopy(reply);bad['strategy_update'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_reply(request,bad)

    def test_initial_keep_and_missing_course_are_rejected(self):
        request=strategic_request();validate_request(request)
        missing=copy.deepcopy(request);missing.pop('strategic_intent')
        with self.assertRaises(ValueError):validate_request(missing)
        reply=final_reply(request)
        reply['strategy_update']=dict(decision='keep',base_revision=0,selected=None,change_reason=None)
        with self.assertRaises(ValueError):validate_reply(request,reply)

    def test_explicit_course_revision_installs_next_revision_without_model_state(self):
        request=self.installed();reply=final_reply(request)
        selected=final_reply(strategic_request())['strategy_update']['selected']
        selected['objective']='Develop the observed base before expansion'
        reply['strategy_update']=dict(decision='revise',base_revision=7,selected=selected,
                                      change_reason='Observed material base threat changes the next operation')
        reply['operation_focus']['revision']=8
        validate_reply(request,reply)
        for mutation in ('adopted_day','revision','unknown_evidence','stale_focus'):
            bad=copy.deepcopy(reply)
            if mutation=='unknown_evidence':
                bad['strategy_update']['selected']['assumptions']=[dict(text='Claim',evidence_refs=['hidden:1'],uncertainty='Unknown')]
            elif mutation=='stale_focus':bad['operation_focus']['revision']=7
            else:bad['strategy_update']['selected'][mutation]=8
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_reply(request,bad)

    def test_milestone_cycles_unknown_refs_and_untrusted_completion_are_rejected(self):
        request=strategic_request();reply=final_reply(request)
        for mutation in ('cycle','duplicate','unknown_target','unknown_actor','unknown_dependency','reported_progress','bad_predicate','bad_owner','bad_review','no_reason'):
            bad=copy.deepcopy(reply);selected=bad['strategy_update']['selected'];stage=selected['milestones'][0]
            if mutation=='cycle':stage['depends_on']=['stage-3']
            elif mutation=='duplicate':selected['milestones'][1]['id']='stage-1'
            elif mutation=='unknown_target':stage['complete_when']['target_ref']='hidden:9'
            elif mutation=='unknown_actor':stage['complete_when']=dict(kind='army_at_least',target_ref=None,actor_ref='enemy:1',value=1)
            elif mutation=='unknown_dependency':stage['depends_on']=['not-a-stage']
            elif mutation=='reported_progress':selected['progress']=[dict(id='stage-1',completed=True)]
            elif mutation=='bad_predicate':stage['complete_when']['kind']='enemy_engaged'
            elif mutation=='bad_owner':stage['complete_when'].update(kind='target_owned',value=1)
            elif mutation=='bad_review':selected['reconsider_when'][0]['milestone_id']='not-a-stage'
            elif mutation=='no_reason':bad['strategy_update']['change_reason']=None
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_reply(request,bad)

    def test_focus_references_exact_course_and_concrete_operation(self):
        request=self.installed();reply=final_reply(request)
        for mutation in ('revision','goal','milestone','duplicate'):
            bad=copy.deepcopy(reply);focus=bad['operation_focus']
            if mutation=='revision':focus['revision']=8
            elif mutation=='goal':focus['bindings'][0]['goal_id']='other-operation'
            elif mutation=='milestone':focus['bindings'][0]['milestone_id']='other-course'
            else:focus['bindings'].append(dict(focus['bindings'][0]))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_reply(request,bad)

    def test_distant_overview_reference_is_allowed_without_authorizing_operation(self):
        request=strategic_request();request['observation']['map_overview']={'objects':[dict(ref='far:town',kind='town',owner=1,visible=True)]}
        reply=final_reply(request);stage=reply['strategy_update']['selected']['milestones'][2]
        stage['complete_when']=dict(kind='target_owned',target_ref='far:town',actor_ref=None,value=0)
        reply['strategy_update']['selected']['assumptions']=[dict(text='Known distant objective',evidence_refs=['target:far:town'],uncertainty='Native route remains unknown')]
        validate_reply(request,reply)
        bad=copy.deepcopy(reply);bad['plan']['goals'][0]['target_ref']='far:town'
        with self.assertRaises(ValueError):validate_reply(request,bad)
        request['observation']['map_overview']['objects']=[]
        with self.assertRaises(ValueError):validate_reply(request,reply)

    def test_saved_course_allows_lost_actor_and_preserves_context_under_history_budget(self):
        from controller.prompt_context import bounded_history,encode_request
        from test_prompt_context import restore_request
        request=self.installed();request['strategic_intent']['milestones'][0]['complete_when']=dict(kind='army_at_least',actor_ref='lost-own-hero',target_ref=None,value=1000)
        request['memory']['known_objects']=[dict(ref='stale:'+str(i),last_seen_day=-100,kind='resource',payload='x'*1000) for i in range(100)]
        validate_request(request)
        projected,info=bounded_history(request)
        self.assertTrue(info['applied'])
        self.assertEqual(projected['strategic_intent'],request['strategic_intent'])
        self.assertEqual(restore_request(encode_request(projected))['strategic_intent'],request['strategic_intent'])
        validate_reply(request,final_reply(request))

    def test_history_projection_retains_course_target_facts(self):
        from controller.prompt_context import bounded_history
        request=self.installed()
        request['strategic_intent']['milestones'][0]['complete_when']=dict(kind='target_owned',target_ref='distant-old-town',actor_ref=None,value=0)
        target=dict(ref='distant-old-town',last_seen_day=-100,kind='town',owner=-1,payload='known historical target')
        request['memory']['known_objects']=[target,*[dict(ref='stale:'+str(i),last_seen_day=-100,kind='resource',payload='x'*1000) for i in range(100)]]
        projected,info=bounded_history(request)
        self.assertTrue(info['applied'])
        self.assertIn(target,projected['memory']['known_objects'])

    def test_artifact_visit_is_admitted_only_as_visible_unvisited_site(self):
        from test_helper_hiring_controller import reply as answer
        request=strategic_request();site=dict(ref='artifact:1',kind='artifact',visible=True,visited=False)
        request['observation']['objects'].append(site)
        goal=dict(id='pickup',kind='visit_site',actor_ref='object:0',target_ref='artifact:1',deadline_day=3,priority=90,
                  building_id=-1,min_army_value=0,depends_on=[],required_capabilities=['land'],complete_when=dict(kind='site_visited',value=0))
        reply=answer(request,goal)
        reply['strategy_update']['selected']['milestones'][0]['complete_when']=dict(kind='site_visited',target_ref='artifact:1',actor_ref='object:0',value=0)
        validate_reply(request,reply)
        for patch in ({'visible':False},{'visited':True},{'kind':'hidden_reward'}):
            invalid=copy.deepcopy(request);invalid['observation']['objects'][-1].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_reply(invalid,reply)

    def test_text_and_list_limits_match_native_utf8_bounds(self):
        request=strategic_request();reply=final_reply(request)
        reply['strategy_update']['selected']['objective']='Ж'*320
        validate_reply(request,reply)
        reply['strategy_update']['selected']['objective']+='Ж'
        with self.assertRaises(ValueError):validate_reply(request,reply)
        reply=final_reply(request);reply['strategy_update']['selected']['milestones'].pop()
        with self.assertRaises(ValueError):validate_reply(request,reply)

if __name__=='__main__':unittest.main()
