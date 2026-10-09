"""Explicit global-course fields for deterministic NK3 test controllers."""


def with_intent(request, reply):
    current = request.get('strategic_intent')
    revision = current['revision'] if current else 0
    selected = None
    if not current:
        world = request['observation']
        town = world.get('towns', [None])[0] if world.get('towns') else None
        hero = world.get('heroes', [None])[0] if world.get('heroes') else None
        if town:
            predicate = dict(kind='building_present', target_ref=town['ref'], actor_ref=None, value=0)
        elif hero:
            predicate = dict(kind='army_at_least', target_ref=None, actor_ref=hero['ref'], value=1)
        else:
            target = next(o for o in world['objects'] if o['kind'] in ('town', 'mine'))
            predicate = dict(kind='target_owned', target_ref=target['ref'], actor_ref=None, value=world['player'])
        selected = dict(objective='Prepare own forces for conquest', selection_reason='Controlled contract fixture',
                        assumptions=[], milestones=[dict(id='stage-'+str(i), description='Confirmed stage '+str(i),
                            depends_on=[] if i==1 else ['stage-'+str(i-1)], complete_when=dict(predicate))
                            for i in range(1,4)],
                        reconsider_when=[dict(kind='milestone_completed',milestone_id='stage-1',reason='Select the next operation')])
    reply['strategy_update'] = dict(decision='keep' if current else 'revise', base_revision=revision,
                                    selected=selected, change_reason=None if current else 'Initial course selection')
    campaign = reply['plan'] if reply['decision']=='revise' else request.get('campaign')
    milestone = current['milestones'][0]['id'] if current else 'stage-1'
    reply['operation_focus'] = dict(revision=revision if current else 1,
                                    bindings=[dict(goal_id=g['id'],milestone_id=milestone)
                                              for g in (campaign or {}).get('goals',[])])
    goals=(campaign or {}).get('goals',[])
    waits=[]
    for g in goals:
        if g['kind'] in ('preserve_force','defend_area'):
            waits.append(dict(goal_id=g['id'],purpose='safety' if g['kind']=='preserve_force' else 'defend',
                              basis_goal_ids=[g['id']],next_goal_id=None))
    towns=[]
    for front in request['observation'].get('forecasts',{}).get('defenses',[]):
        if not front.get('threats') or not goals:continue
        defense=[g['id'] for g in goals if g['target_ref']==front['town_ref'] and g['kind'] in ('defend_area','prepare_garrison')]
        towns.append(dict(town_ref=front['town_ref'],choice='defend' if defense else 'accept_risk',
                          goal_ids=defense or [goals[0]['id']]))
    reply['decision_basis']=dict(waits=waits,town_choices=towns)
    return reply
