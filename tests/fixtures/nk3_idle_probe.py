"""Return an unexecutable scout, then correct it through the real request boundary."""
from strategic_intent import with_intent
import json
import sys

request = json.load(sys.stdin)
own = request['observation']
hero = max(own['heroes'], key=lambda h: h['army_value'])
day = own['day']
frontier = max(own['frontier_options'],
               key=lambda f: sum(abs(f['position'][i]-hero['position'][i]) for i in (0, 1)))
goal = dict(id='blocked_scout', kind='scout_frontier', actor_ref=hero['ref'],
            target_ref=frontier['ref'], deadline_day=day+3, priority=100,
            building_id=-1, min_army_value=1000000, depends_on=[],
            required_capabilities=['land'], complete_when=dict(kind='frontier_observed', value=0))
# Retain the same bad operation during the ordinary deeper native scan. The
# next correction must come from the turn-end idle review, not that scan.
if request.get('campaign') and request['identity']['revision']>=2:
    resources = {o['ref']: o for o in own['visible_objects'] if o['kind']=='resource'}
    choices = [(a['movement_cost'], entry['target_ref'])
               for entry in own['forecasts']['routes'] if entry['target_ref'] in resources
               for a in entry['own_arrivals']
               if a['hero_ref']==hero['ref'] and a['day']<=day+3 and a['army_loss_estimate']==0]
    if choices:
        goal.update(id='pickup', kind='secure_resource', target_ref=min(choices)[1],
                    min_army_value=0, complete_when=dict(kind='reserve_at_least', value=1))
    else:
        goal = request['campaign']['goals'][0]
plan = dict(version=3, revision=request['identity']['revision']+1, approach='expansion',
            horizon_days=3, goals=[goal], reserves=[],
            policy=dict(max_loss_ratio=.28, allow_route_repair=True,
                        allow_helper_replacement=True, critical_towns=[]))
reply = dict(protocol=2, request_id=request['request_id'], identity=request['identity'],
             decision='revise', reason='Correct the blocked scout with a supported pickup.',
             evidence_refs=['hero:'+hero['ref']], victory_method='Build a supported expansion route.',
             assignments=[dict(hero_ref=hero['ref'], role='main')],
             alternatives=[dict(approach='scouting', benefit='Information', cost='Travel', uncertainty='Fog'),
                           dict(approach='expansion', benefit='Resources', cost='Movement', uncertainty='Future threats')],
             reconsider_when=[dict(goal_id=goal['id'], kind='route_not_established')], plan=plan,
             usage=dict(input_tokens=100, output_tokens=100, known=True))
print(json.dumps(with_intent(request,reply)))
