"""A deterministic campaign update and a held call for native save verification."""
import json
import sys
import time

request = json.load(sys.stdin)
observation = request['observation']
end = next(a for a in request['actions'] if a['kind'] == 'end_turn')
if request['request_id'] == '0:1:0':
    action = next(a for a in request['actions'] if a['kind'] == 'build')
    day = observation['day']
    hero = 'object:' + str(observation['heroes'][0]['id'])
    town = 'town:object:' + str(action['town'])
    strategy = {'goal':'Save/load integration probe', 'executor_ref':None,
                'target_ref':action['target_ref'], 'ready_when':{'kind':'always','value':None},
                'complete_when':{'kind':'confirmed_action','value':'build'},
                'rationale':'Use the observed construction.', 'reserves':'Keep gold for troops.',
                'progress':'First construction selected.', 'change_reason':'Owned town facts.',
                'steps':['Build once','Resume this campaign'], 'reconsider_if':['Town is lost']}
    campaign = {'decision':'revise', 'reason':'Owned town supports the observed construction.',
                'evidence_refs':[town, 'hero:'+hero],
                'plan':{'victory_method':'Defeat hostile teams through supported conquest.',
                        'approach':'economy', 'main_hero_ref':hero, 'horizon_day':day+4,
                        'advantages':[{'fact_ref':town,'benefit':'Income investment','constraint':'Troops need delivery'},
                                      {'fact_ref':'hero:'+hero,'benefit':'Main army available','constraint':'Unknown enemy strength'}],
                        'assignments':[{'hero_ref':hero,'role':'main','target_ref':None,'task':'Prepare useful expansion'}],
                        'milestones':[{'target_ref':action['target_ref'],'executor_ref':None,'due_day':day+3,'expected':'Complete useful town construction'}],
                        'reserves':[{'resource':'gold','amount':1000,'purpose':'Recruitment','release_if':'Urgent threat'}],
                        'alternatives':[{'approach':'economy','benefit':'Income','cost':'One build day','risk':'Delayed troops','abandon_if':'Visible enemy'},
                                        {'approach':'expansion','benefit':'Mine income','cost':'Army and travel','risk':'Unknown encounter','abandon_if':'Unsafe route'}]}}
else:
    time.sleep(12)
    action, strategy, campaign = end, None, None
print(json.dumps({'protocol':1, 'request_id':request['request_id'], 'action_id':action['id'],
                  'strategy':strategy, 'campaign':campaign}))
