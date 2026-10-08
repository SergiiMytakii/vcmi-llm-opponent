"""One model-authored strategic decision; native code owns commands and feasibility."""
import json
import copy

try:
    from .strategy import _object, _validate_shape, campaign_evidence
except ImportError:
    from strategy import _object, _validate_shape, campaign_evidence

KINDS = ('hire_helper', 'develop_town', 'secure_resource', 'prepare_garrison', 'reinforce_hero', 'capture_target', 'intercept_hero',
         'defend_area', 'scout_frontier', 'scout_area', 'visit_site', 'preserve_force', 'explore_passage')
APPROACHES = ('economy', 'expansion', 'offense', 'defense', 'scouting')
ROLES = ('main', 'defender', 'scout', 'collector', 'reinforcement')
INTENT_PREDICATES = ('target_owned', 'building_present', 'army_at_least', 'site_visited', 'passage_explored')
INTENT_REASONS = ('target_lost', 'actor_lost', 'base_threat', 'route_blocked', 'no_progress', 'milestone_completed')


def integer(low, high):
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def array(item, low=0, high=12):
    return {'type': 'array', 'minItems': low, 'maxItems': high, 'items': item}


def references(request):
    world = request['observation']
    return {item['ref'] for key in ('heroes', 'towns', 'objects', 'scouting_options') for item in world.get(key, [])} | set(world.get('frontiers', []))


def strategic_objects(request):
    world = request['observation']
    overview = world.get('map_overview', {})
    result = {}
    for key in ('heroes','towns','objects','visible_objects'):
        for item in world.get(key, []):
            if isinstance(item,dict) and 'ref' in item:result.setdefault(item['ref'],item)
    for item in overview.get('objects', []):
        if isinstance(item,dict) and 'ref' in item:result.setdefault(item['ref'],item)
    return result


def evidence(request):
    refs = campaign_evidence({**request, 'actions': []})
    if 'goal_feedback' in request['observation']:
        refs.append('observation:goal_feedback')
    if 'offensive_preparation' in request['observation']:
        refs.append('observation:offensive_preparation')
    if 'scouting_options' in request['observation']:
        refs.append('observation:scouting_options')
    if 'main_army_idle' in request['observation']:
        refs.append('observation:main_army_idle')
    if 'map_overview' in request['observation']:
        refs.append('observation:map_overview')
        refs.extend('target:' + ref for ref in strategic_objects(request))
    if 'strategy_stalls' in request['observation']:
        refs.append('observation:strategy_stalls')
    refs.extend(request.get('evidence_refs', []))
    return sorted(set(refs))


def validate_request(request):
    if not isinstance(request, dict) or type(request.get('protocol')) is not int or request['protocol'] != 2:
        raise ValueError('unsupported native strategy protocol')
    if not isinstance(request.get('request_id'), str) or not 1 <= len(request['request_id']) <= 240:
        raise ValueError('invalid strategic request_id')
    world, identity, budget = request.get('observation'), request.get('identity'), request.get('budget')
    if not isinstance(world, dict) or not isinstance(identity, dict) or set(identity) != {'instance', 'generation', 'player', 'day', 'revision'}:
        raise ValueError('missing strategic identity or observation')
    for name in ('instance', 'generation'):
        if not isinstance(identity[name], str) or not 1 <= len(identity[name]) <= 120:
            raise ValueError('invalid strategic identity')
    for name in ('player', 'day', 'revision'):
        if type(identity[name]) is not int or identity[name] < (1 if name == 'day' else 0):
            raise ValueError('invalid strategic identity')
    if identity['player'] != world.get('player') or identity['day'] != world.get('day'):
        raise ValueError('strategic identity differs from observation')
    for name in ('heroes', 'towns', 'objects', 'frontiers', 'capabilities'):
        if not isinstance(world.get(name), list): raise ValueError('incomplete strategic observation: ' + name)
    if not isinstance(budget, dict) or set(budget) != {'wait_ms', 'tokens'} or any(type(v) is not int or v <= 0 for v in budget.values()):
        raise ValueError('invalid strategic budget')
    if not isinstance(request.get('memory'), dict) or not isinstance(request.get('signals'), list) or not request['signals']:
        raise ValueError('missing strategic evidence')
    if 'strategic_intent' not in request or request['strategic_intent'] is not None and not isinstance(request['strategic_intent'], dict):
        raise ValueError('missing strategic intent')
    if request['strategic_intent'] is not None:
        intent = request['strategic_intent']
        if type(intent.get('version')) is not int or intent['version'] != 1 or type(intent.get('revision')) is not int or not 1 <= intent['revision'] <= 2147483647:
            raise ValueError('invalid strategic intent revision')
        if type(intent.get('adopted_day')) is not int or not 1 <= intent['adopted_day'] <= world['day']:
            raise ValueError('invalid strategic intent adoption')
        selected = {key:intent[key] for key in ('objective','selection_reason','assumptions','milestones','reconsider_when') if key in intent}
        validate_selected(request, selected, current=True)
    if not references(request) or not evidence(request): raise ValueError('no supported strategic evidence')


def same_goal(left, right):
    """Absent legacy risk and explicit null have identical goal semantics."""
    def normalized(goal):
        if not isinstance(goal,dict):return goal
        return {key:value for key,value in goal.items() if key!='risk' or value is not None}
    return normalized(left)==normalized(right)


def completed_interceptions(request):
    world=request['observation']
    return [goal for goal in (request.get('campaign') or {}).get('goals',[])
            if goal['kind']=='intercept_hero'
            and world.get('goal_statuses',{}).get(goal['id'],{}).get('state')=='completed'
            and any(same_goal(receipt.get('goal'),goal) and receipt.get('won') is True
                    and type(receipt.get('day')) is int and 1<=receipt['day']<=goal['deadline_day']
                    for receipt in world.get('confirmed_interceptions',[]))]


def needs_defense_exit(request):
    return any(g.get('kind') in ('defend_area','preserve_force')
               for g in (request.get('campaign') or {}).get('goals',[]))


def visit_site_available(site):
    if site.get('visible') is not True or site.get('visited') is not False:
        return False
    kind=site.get('kind')
    return (kind in ('scholar','treasure_chest','obelisk','artifact')
            or kind=='keymaster_tent' and site.get('key_owned') is False
            or kind in ('border_guard','border_gate') and site.get('key_owned') is True
               and bool(site.get('eligible_hero_refs')))


def selected_schema(request, current=False):
    text = {'type':'string','minLength':1,'maxLength':160}
    label = {'type':'string','minLength':1,'maxLength':30}
    refs = sorted(strategic_objects(request))
    target = {'type':'string','enum':refs}
    actors = sorted(h['ref'] for h in request['observation']['heroes'])
    actor = {'type':'string','enum':actors}
    # Saved courses may contain historical targets/actors no longer in this view.
    if current:
        target = actor = {'type':'string','minLength':1,'maxLength':40}
    predicates = []
    if refs or current:
        predicates.extend([
            _object({'kind':{'type':'string','enum':['target_owned']},'target_ref':target,
                'actor_ref':{'type':'null'},'value':{**integer(0,7),
                    **({} if current else {'enum':[request['observation']['player']]})}}),
            _object({'kind':{'type':'string','enum':['building_present']},'target_ref':target,
                'actor_ref':{'type':'null'},'value':integer(0,100000)})])
    if actors or current:
        predicates.append(_object({'kind':{'type':'string','enum':['army_at_least']},
            'target_ref':{'type':'null'},'actor_ref':actor,'value':integer(1,1000000000)}))
        if refs or current:
            predicates.append(_object({'kind':{'type':'string','enum':['site_visited','passage_explored']},
                'target_ref':target,'actor_ref':actor,'value':{**integer(0,0),'enum':[0]}}))
    if not predicates:raise ValueError('no supported strategic milestone predicate')
    return _object({'objective':text,'selection_reason':text,
        'assumptions':array(_object({'text':text,
            'evidence_refs':array({'type':'string','minLength':1,'maxLength':40,
                                 **({} if current else {'enum':evidence(request)})},1,8),
            'uncertainty':text}),0,8),
        'milestones':array(_object({'id':label,'description':text,'depends_on':array(label,0,5),
            'complete_when':{'anyOf':predicates}}),3,6),
        'reconsider_when':array(_object({'kind':{'type':'string','enum':list(INTENT_REASONS)},
            'milestone_id':label,'reason':text}),1,12)})


def validate_selected(request, selected, current=False):
    schema = selected_schema(request,current)
    seen = set()
    def byte_limits(value):
        if isinstance(value,dict):
            if id(value) in seen:return
            seen.add(id(value))
            if 'maxLength' in value:value['maxLength']*=4
            for item in value.values():byte_limits(item)
        elif isinstance(value,list):
            for item in value:byte_limits(item)
    byte_limits(schema)
    _validate_shape(selected,schema)
    milestones = {m['id']:m for m in selected['milestones']}
    if len(milestones) != len(selected['milestones']):raise ValueError('duplicate strategic milestone')
    def visit(name, stack):
        if name not in milestones or name in stack:raise ValueError('missing or cyclic milestone dependency')
        dependencies=milestones[name]['depends_on']
        if len(set(dependencies)) != len(dependencies):raise ValueError('duplicate milestone dependency')
        for dep in dependencies:visit(dep,stack|{name})
    for name in milestones:visit(name,set())
    objects = strategic_objects(request)
    towns = {t['ref'] for t in request['observation']['towns']}
    heroes = {h['ref'] for h in request['observation']['heroes']}
    for milestone in milestones.values():
        p = milestone['complete_when'];kind=p['kind'];target=p['target_ref'];actor=p['actor_ref'];value=p['value']
        if not current and target is not None and objects.get(target,{}).get('visible') is False:
            raise ValueError('strategic target is not currently visible')
        if kind=='army_at_least':
            if target is not None or actor is None or value<1 or not current and actor not in heroes:
                raise ValueError('invalid strategic army predicate')
        elif kind in ('target_owned','building_present'):
            if actor is not None or target is None:raise ValueError('invalid strategic ownership predicate')
            if kind=='target_owned' and (value>7 or not current and value != request['observation']['player']):
                raise ValueError('invalid strategic target owner')
            if kind=='building_present' and value>100000:raise ValueError('invalid strategic building')
            if not current:
                kinds=('town','mine') if kind=='target_owned' else ('town',)
                if target not in towns and objects.get(target,{}).get('kind') not in kinds:
                    raise ValueError('unsupported strategic ownership target')
        else:
            if target is None or actor is None or value != 0:raise ValueError('invalid strategic action predicate')
            if not current:
                kind_expected=('subterranean_gate',) if kind=='passage_explored' else ('scholar','treasure_chest','obelisk','artifact','keymaster_tent','border_guard','border_gate')
                if actor not in heroes or objects.get(target,{}).get('kind') not in kind_expected:
                    raise ValueError('unsupported strategic action target')
    if any(c['milestone_id'] not in milestones for c in selected['reconsider_when']):
        raise ValueError('unknown strategic reconsideration milestone')
    return milestones


def reply_schema(request):
    world = request['observation']
    intent = request.get('strategic_intent')
    intent_revision = intent['revision'] if intent else 0
    day = world['day']
    text = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    heroes = sorted(h['ref'] for h in world['heroes'])
    hero = {'type': ['string', 'null'], 'enum': [None, *heroes]}
    owned_hero = {'type':'string','enum':heroes} if heroes else {'type':'string','pattern':'^$'}
    town_refs = [t['ref'] for t in world['towns']]
    owned_town = {'type':'string','enum':town_refs} if town_refs else {'type':'string','pattern':'^$'}
    target = {'type': 'string', 'enum': sorted(references(request))}
    label = {'type': 'string', 'minLength': 1, 'maxLength': 30}
    predicate = _object({'kind': {'type': 'string', 'enum': ['helper_hired', 'building_present', 'target_owned', 'reserve_at_least',
                       'army_at_least', 'enemy_engaged', 'garrison_at_least', 'frontier_observed', 'area_observed', 'site_visited', 'held_until', 'force_preserved_until', 'passage_explored']},
                         'value': integer(0, 1000000000)})
    goal = _object({'id': label, 'kind': {'type': 'string', 'enum': list(KINDS)}, 'actor_ref': hero,
                    'target_ref': target, 'deadline_day': integer(day, day+7), 'priority': integer(1,100),
                    'building_id': integer(-1,100000), 'min_army_value': integer(0,1000000000),
                    'depends_on': array(label), 'required_capabilities': array({'type':'string','enum':world['capabilities']},0,8),
                    'complete_when': predicate,
                    'risk': {'anyOf':[{'type':'null'},_object({
                        'max_loss_ratio':{'type':'number','minimum':0,'maximum':1},
                        'reason':text})]}})
    # The schema constrains completion semantics before the model answers;
    # native feasibility still authoritatively validates the fresh world.
    variants = []
    def refs_schema(values):
        return {'type':'string','enum':sorted(set(values))}
    town_refs = [t['ref'] for t in world['towns']]
    own_refs = [*heroes,*town_refs]
    objects = world['objects']
    targets = {
        'hire_helper':[t['ref'] for t in world['towns'] if any(c.get('can_recruit') is True for c in t.get('hiring_options',[]))],
        'develop_town':town_refs,
        'secure_resource':[o['ref'] for o in objects if o.get('kind') in ('mine','resource') and (o.get('kind')!='mine' or o.get('owner')!=world['player'] or o.get('visible') is not True)],
        'reinforce_hero':own_refs,
        'prepare_garrison':town_refs,
        'intercept_hero':[o['ref'] for o in objects if o.get('kind')=='hero' and o.get('visible') is True and o.get('owner') in world.get('enemy_players',[])]
            +[g['target_ref'] for g in completed_interceptions(request)],
        'capture_target':[o['ref'] for o in objects if o.get('kind') in ('town','mine') and (o.get('owner')!=world['player'] or o.get('visible') is not True)],
        'defend_area':town_refs,'scout_frontier':world['frontiers'],
        'scout_area':[a['ref'] for a in world.get('scouting_options',[])],'preserve_force':town_refs,
        'visit_site':[o['ref'] for o in objects if visit_site_available(o)]
            +[g['target_ref'] for g in (request.get('campaign') or {}).get('goals',[]) if g['kind']=='visit_site' and world.get('goal_statuses',{}).get(g['id'],{}).get('state')=='completed'],
        'explore_passage':[o['ref'] for o in objects if o.get('kind')=='subterranean_gate' and o.get('visible') is True]}
    supported_buildings = sorted({b['id'] for t in world['towns'] for b in t.get('building_options',[]) if b.get('supported') is True})
    completions = {'hire_helper':['helper_hired'],'develop_town':['building_present'],'secure_resource':['target_owned','reserve_at_least'],
                   'reinforce_hero':['army_at_least'],
                           'prepare_garrison':['garrison_at_least'],'intercept_hero':['enemy_engaged'],'capture_target':['target_owned'],
                   'defend_area':['held_until'],'scout_frontier':['frontier_observed'],'scout_area':['area_observed'],'visit_site':['site_visited'],'preserve_force':['force_preserved_until'],'explore_passage':['passage_explored']}
    for kind in KINDS:
        if not targets[kind] or (kind not in ('develop_town','hire_helper') and not heroes) or (kind=='develop_town' and not supported_buildings):continue
        variant = copy.deepcopy(goal)
        props = variant['properties']
        props['kind'] = {'type':'string','enum':[kind]}
        if kind not in ('capture_target','intercept_hero'): props['risk']={'type':'null'}
        props['target_ref'] = refs_schema(targets[kind])
        props['actor_ref'] = {'type':'null'} if kind in ('develop_town','hire_helper') else refs_schema(heroes)
        props['building_id'] = {**integer(-1,100000),'enum':supported_buildings if kind=='develop_town' else [-1]}
        predicate_props = props['complete_when']['properties']
        predicate_props['kind'] = {'type':'string','enum':completions[kind]}
        if kind=='hire_helper':
            props['candidate_ref']=refs_schema([c['ref'] for t in world['towns'] for c in t.get('hiring_options',[]) if c.get('can_recruit') is True])
            props['helper_role']={'type':'string','enum':['scout','collector','reinforcement','defender']}
            props['job_ref']=refs_schema(references(request))
            props['min_army_value']=integer(0,0)
            variant['required'].extend(['candidate_ref','helper_role','job_ref'])
            predicate_props['value']=integer(0,0)
        elif kind in ('scout_frontier','explore_passage','visit_site','intercept_hero'):predicate_props['value'] = {**integer(0,0),'enum':[0]}
        elif kind=='prepare_garrison':
            predicate_props['value']=integer(1,1000000000)
            props['garrison_mode']={'type':'string','enum':['recruit','detach','recruit_then_detach']}
            variant['required'].append('garrison_mode')
        elif kind=='scout_area':predicate_props['value']={**integer(1,64),'enum':sorted({p['sight_radius'] for a in world.get('scouting_options',[]) for p in a['own_arrivals']})}
        elif kind=='capture_target':predicate_props['value'] = {**integer(0,7),'enum':[world['player']]}
        elif kind=='develop_town':predicate_props['value'] = {**integer(0,100000),'enum':supported_buildings}
        elif kind in ('defend_area','preserve_force'):predicate_props['value'] = integer(day,day+7)
        variants.append(variant)
    if not variants:raise ValueError('no supported native goal vocabulary for this world')
    goal = {'anyOf':variants}
    approach = {'type': 'string', 'enum': list(APPROACHES)}
    plan = _object({'version': {**integer(3,3), 'enum':[3]}, 'revision': integer(request['identity']['revision']+1,2147483647),
                    'approach': approach, 'horizon_days': integer(3,7), 'goals':array(goal,1),
                    'reserves':array(_object({'goal_id':label, 'resources':array(integer(0,100000000),7,7),
                                             'force_value':integer(0,1000000000)})),
                    'policy':_object({'max_loss_ratio':{'type':'number','minimum':0,'maximum':.5},
                                      'allow_route_repair':{'type':'boolean'}, 'allow_helper_replacement':{'type':'boolean'},
                                      'critical_towns':array(owned_town, high=12 if town_refs else 0)})})
    properties = {'protocol':{**integer(2,2),'enum':[2]},
                  'request_id':{'type':'string','enum':[request['request_id']]},
                  'identity':_object({key:{'type':'string' if isinstance(value,str) else 'integer', 'enum':[value],
                                           **({} if isinstance(value,str) else {'minimum':0,'maximum':2147483647})}
                                      for key,value in request['identity'].items()}),
                  'decision':{'type':'string','enum':['retain','revise']}, 'reason':text,
                  'evidence_refs':array({'type':'string','enum':evidence(request)},1,8),
                  'victory_method':text,
                  'assignments':array(_object({'hero_ref':owned_hero,
                                               'role':{'type':'string','enum':list(ROLES)}}),0,16),
                  'alternatives':array(_object({'approach':approach,'benefit':text,'cost':text,'uncertainty':text}),2,3),
                  'reconsider_when':array(_object({'goal_id':label,'kind':{'type':'string','enum':
                                              ['executor_lost','deadline_missed','route_not_established']}}),1),
                  'plan':{'anyOf':[{'type':'null'},plan]},
                  'strategy_update':_object({'decision':{'type':'string','enum':['keep','revise'] if intent else ['revise']},
                      'base_revision':{**integer(0,2147483647),'enum':[intent_revision]},
                      'selected':{'anyOf':[{'type':'null'},selected_schema(request)]},
                      'change_reason':{'anyOf':[{'type':'null'},text]}}),
                  'operation_focus':_object({'revision':{**integer(1,2147483647),
                      'enum':[intent_revision,intent_revision+1] if intent else [1]},
                      'bindings':array(_object({'goal_id':label,'milestone_id':label}),0,16)})}
    if needs_defense_exit(request):
        properties['defense_exit']={'anyOf':[{'type':'null'},_object({
            'waiting_for':text,'expected_gain':text,'next_step':text})]}
    return _object(properties)


def validate_reply(request, reply, wire=False):
    usage = None
    if wire:
        if not isinstance(reply,dict) or 'usage' not in reply: raise ValueError('missing actual strategic usage')
        reply = dict(reply)
        usage = reply.pop('usage')
        if not isinstance(usage,dict) or set(usage) != {'input_tokens','output_tokens','known'}:
            raise ValueError('invalid strategic usage')
        if type(usage['known']) is not bool or any(type(usage[k]) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
            raise ValueError('invalid strategic usage')
    schema = reply_schema(request)
    # JSON Schema lengths count Unicode characters. The native value contract
    # caps UTF-8 bytes; four bytes per character is its conservative bound.
    byte_schema = copy.deepcopy(schema)
    seen = set()
    def byte_limits(value):
        if isinstance(value,dict):
            if id(value) in seen:return
            seen.add(id(value))
            if value.get('type')=='string' and 'maxLength' in value:value['maxLength']*=4
            for item in value.values():byte_limits(item)
        elif isinstance(value,list):
            for item in value:byte_limits(item)
    byte_limits(byte_schema)
    shape_reply = copy.deepcopy(reply)
    # Old saved/fixture plans omitted risk. New model responses explicitly choose
    # null or a grant; checking a legacy plan must not mutate its identity.
    if isinstance(shape_reply.get('plan'),dict) and isinstance(shape_reply['plan'].get('goals'),list):
        for goal in shape_reply['plan']['goals']:
            if isinstance(goal,dict):goal.setdefault('risk',None)
    _validate_shape(shape_reply, byte_schema)
    exposed = any(front.get('town_ref') in {t['ref'] for t in request['observation']['towns']}
                  and front.get('threats') and front.get('status') in
                  ('insufficient_current_force','unbounded_opposition')
                  for front in request['observation'].get('forecasts',{}).get('defenses',[]))
    if exposed and not any(option['approach']=='defense' for option in reply['alternatives']):
        raise ValueError('exposed town requires a defense comparison, not a mandatory defense decision')
    plan = reply['plan'] if reply['decision'] == 'revise' else request.get('campaign')
    if reply['decision'] == 'retain':
        if reply['plan'] is not None or not plan: raise ValueError('retain requires a current campaign')
    elif not plan: raise ValueError('revise requires a complete campaign')
    update=reply['strategy_update'];current=request.get('strategic_intent')
    base=current['revision'] if current else 0
    if update['base_revision'] != base:raise ValueError('stale strategic intent revision')
    if update['decision']=='keep':
        if current is None or update['selected'] is not None or update['change_reason'] is not None:
            raise ValueError('keep requires an unchanged accepted strategic intent')
        milestones={m['id']:m for m in current['milestones']}
        intent_revision=base
    else:
        if update['selected'] is None or update['change_reason'] is None:
            raise ValueError('revise requires a selected course and change reason')
        milestones=validate_selected(request,update['selected'])
        intent_revision=base+1
    focus=reply['operation_focus']
    if focus['revision'] != intent_revision:raise ValueError('stale operation focus revision')
    goal_ids={g['id'] for g in plan['goals']}
    bound=set()
    for binding in focus['bindings']:
        if binding['goal_id'] not in goal_ids or binding['milestone_id'] not in milestones or binding['goal_id'] in bound:
            raise ValueError('invalid strategic operation binding')
        bound.add(binding['goal_id'])
    if needs_defense_exit(request) and any(g['kind'] in ('defend_area','preserve_force') for g in plan['goals']):
        if reply.get('defense_exit') is None:
            raise ValueError('repeated_hold_requires_wait_gain_and_next_step')
    goals = {g['id']:g for g in plan['goals']}
    if len(goals) != len(plan['goals']): raise ValueError('duplicate strategic goal')
    def visit(name, stack):
        if name not in goals or name in stack: raise ValueError('missing or cyclic dependency')
        for dep in goals[name]['depends_on']: visit(dep, stack|{name})
    for name in goals: visit(name,set())
    by_ref = {o['ref']:o for o in request['observation']['objects']}
    hiring_costs=[0]*7
    hired_candidates=set()
    for g in goals.values():
        kind, predicate = g['kind'], g['complete_when']
        if kind=='hire_helper':
            if reply['decision']=='retain' and any(
                    same_goal(receipt.get('goal'),g) and g['candidate_ref']=='tavern:'+str(receipt.get('hero_type_id'))
                    and type(receipt.get('day')) is int
                    and 1<=receipt['day']<=g['deadline_day']
                    and (request['observation'].get('goal_statuses',{}).get(g['id'],{}).get('state')=='completed'
                         or any(h['ref']==receipt.get('hero_ref') and h.get('hero_type_id')==receipt.get('hero_type_id')
                                for h in request['observation']['heroes']))
                    for receipt in request['observation'].get('confirmed_helper_hires',[])):
                continue
            town=next((t for t in request['observation']['towns'] if t['ref']==g['target_ref']),{})
            candidate=next((c for c in town.get('hiring_options',[]) if c['ref']==g['candidate_ref'] and c.get('can_recruit') is True),None)
            if not candidate or g['candidate_ref'] in hired_candidates:
                raise ValueError('helper_candidate_not_available')
            hired_candidates.add(g['candidate_ref'])
            hiring_costs=[a+b for a,b in zip(hiring_costs,candidate['cost'])]
            own_towns={t['ref'] for t in request['observation']['towns']}
            own_heroes={h['ref'] for h in request['observation']['heroes']}
            target=by_ref.get(g['job_ref'],{})
            known_scout=set(request['observation'].get('frontiers',[])) | {o['ref'] for o in request['observation'].get('scouting_options',[])}
            role=g['helper_role']
            valid=(role=='defender' and g['job_ref'] in own_towns
                   or role=='reinforcement' and g['job_ref'] in own_heroes
                   or role=='scout' and (g['job_ref'] in known_scout or target.get('kind') in ('subterranean_gate','scholar','obelisk','treasure_chest'))
                   or role=='collector' and target.get('kind') in ('mine','resource','treasure_chest'))
            if not valid:raise ValueError('helper_role_job_mismatch')
    if any(cost>available for cost,available in zip(hiring_costs,request['observation']['resources'])):
        raise ValueError('helper_hiring_exceeds_available_funds')
    for g in goals.values():
        kind, predicate = g['kind'], g['complete_when']
        if reply['decision']=='revise' and predicate['kind']=='target_owned' and by_ref.get(g['target_ref'],{}).get('visible') is True and by_ref.get(g['target_ref'],{}).get('owner')==request['observation']['player']:
            raise ValueError('new_capture_target_already_owned')
        if kind=='intercept_hero':
            target=by_ref.get(g['target_ref'],{})
            if not (target.get('kind')=='hero' and target.get('visible') is True
                    and target.get('owner') in request['observation'].get('enemy_players',[])):
                if not any(same_goal(g,old) for old in completed_interceptions(request)):raise ValueError('unconfirmed hidden interception')
        if kind=='visit_site':
            target=by_ref.get(g['target_ref'],{})
            if target.get('kind') in ('border_guard','border_gate') and not any(
                    same_goal(g,receipt.get('goal')) for receipt in request['observation'].get('confirmed_site_visits',[])):
                if g['actor_ref'] not in target.get('eligible_hero_refs',[]):
                    raise ValueError('border_actor_not_eligible')
        if kind=='develop_town' and predicate['value'] != g['building_id']:raise ValueError('building predicate does not prove goal')
        if kind=='reinforce_hero' and (g['actor_ref']==g['target_ref'] or predicate['value']<g['min_army_value']):
            raise ValueError('invalid reinforcement predicate or participants')
        if kind=='secure_resource':
            expected='target_owned' if by_ref[g['target_ref']]['kind']=='mine' else 'reserve_at_least'
            if predicate['kind']!=expected or (expected=='target_owned' and predicate['value']!=request['observation']['player']):
                raise ValueError('resource predicate does not prove goal')
        if kind in ('defend_area','preserve_force') and predicate['value']>g['deadline_day']:
            raise ValueError('holding predicate exceeds deadline')
    if any(g['deadline_day'] > request['observation']['day']+plan['horizon_days'] for g in goals.values()):
        raise ValueError('goal exceeds horizon')
    if reply['decision'] == 'revise':
        # Match CampaignState's current-force/funds contract before emitting a reply.
        # A delivery's future army minimum is a goal, never an existing reservation.
        heroes = {h['ref']:h for h in request['observation']['heroes']}
        reserved_goals = set()
        resource_totals = [0] * 7
        for reserve in plan['reserves']:
            name = reserve['goal_id']
            if name not in goals or name in reserved_goals:
                raise ValueError('invalid_commitment_reserve')
            reserved_goals.add(name)
            actor = heroes.get(goals[name]['actor_ref'], {})
            if reserve['force_value'] > actor.get('army_value', 0):
                raise ValueError('force_reserve_not_available')
            resource_totals = [a+b for a,b in zip(resource_totals, reserve['resources'])]
        if any(total > available for total, available in zip(resource_totals, request['observation']['resources'])):
            raise ValueError('resource_commitments_exceed_available_funds')
    assigned = {a['hero_ref']:a for a in reply['assignments']}
    if len(assigned) != len(reply['assignments']) or sum(a['role']=='main' for a in assigned.values())>1:
        raise ValueError('conflicting strategic roles')
    for goal in goals.values():
        actor = goal['actor_ref']
        if actor is not None and actor not in assigned:
            raise ValueError('goal actor has no consistent role')
    if any(c['goal_id'] not in goals for c in reply['reconsider_when']): raise ValueError('unknown reconsideration goal')
    if len({json.dumps(a,sort_keys=True,ensure_ascii=False) for a in reply['alternatives']}) != len(reply['alternatives']):
        raise ValueError('strategic alternatives must differ in content')
    if len(json.dumps(reply,ensure_ascii=False,separators=(',',':')).encode('utf-8')) > 32768:
        raise ValueError('strategy exceeds native reply budget')
    if wire: reply['usage'] = usage
    return reply
