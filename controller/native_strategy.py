"""One model-authored strategic decision; native code owns commands and feasibility."""
import json
import copy

try:
    from .strategy import _object, _validate_shape, campaign_evidence
    from .experience import learning_schema, validate_learning
except ImportError:
    from strategy import _object, _validate_shape, campaign_evidence
    from experience import learning_schema, validate_learning

KINDS = ('develop_town', 'secure_resource', 'reinforce_hero', 'capture_target',
         'defend_area', 'scout_frontier', 'preserve_force')
APPROACHES = ('economy', 'expansion', 'offense', 'defense', 'scouting')
ROLES = ('main', 'defender', 'scout', 'collector', 'reinforcement')


def integer(low, high):
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def array(item, low=0, high=12):
    return {'type': 'array', 'minItems': low, 'maxItems': high, 'items': item}


def references(request):
    world = request['observation']
    return {item['ref'] for key in ('heroes', 'towns', 'objects') for item in world.get(key, [])} | set(world.get('frontiers', []))


def evidence(request):
    return campaign_evidence({**request, 'actions': []})


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
    if not references(request) or not evidence(request): raise ValueError('no supported strategic evidence')


def reply_schema(request):
    world = request['observation']
    day = world['day']
    text = {'type': 'string', 'minLength': 1, 'maxLength': 40}
    heroes = sorted(h['ref'] for h in world['heroes'])
    hero = {'type': ['string', 'null'], 'enum': [None, *heroes]}
    owned_hero = {'type':'string','enum':heroes} if heroes else {'type':'string','pattern':'^$'}
    town_refs = [t['ref'] for t in world['towns']]
    owned_town = {'type':'string','enum':town_refs} if town_refs else {'type':'string','pattern':'^$'}
    target = {'type': 'string', 'enum': sorted(references(request))}
    label = {'type': 'string', 'minLength': 1, 'maxLength': 30}
    predicate = _object({'kind': {'type': 'string', 'enum': ['building_present', 'target_owned', 'reserve_at_least',
                       'army_at_least', 'frontier_observed', 'held_until', 'force_preserved_until']},
                         'value': integer(0, 1000000000)})
    goal = _object({'id': label, 'kind': {'type': 'string', 'enum': list(KINDS)}, 'actor_ref': hero,
                    'target_ref': target, 'deadline_day': integer(day, day+7), 'priority': integer(1,100),
                    'building_id': integer(-1,100000), 'min_army_value': integer(0,1000000000),
                    'depends_on': array(label), 'required_capabilities': array({'type':'string','enum':world['capabilities']},0,8),
                    'complete_when': predicate})
    # The schema constrains completion semantics before the model answers;
    # native feasibility still authoritatively validates the fresh world.
    variants = []
    def refs_schema(values):
        return {'type':'string','enum':sorted(set(values))}
    town_refs = [t['ref'] for t in world['towns']]
    own_refs = [*heroes,*town_refs]
    objects = world['objects']
    targets = {
        'develop_town':town_refs,
        'secure_resource':[o['ref'] for o in objects if o.get('kind') in ('mine','resource')],
        'reinforce_hero':own_refs,
        'capture_target':[o['ref'] for o in objects if o.get('kind') in ('town','mine')],
        'defend_area':town_refs,'scout_frontier':world['frontiers'],'preserve_force':town_refs}
    supported_buildings = sorted({b['id'] for t in world['towns'] for b in t.get('building_options',[]) if b.get('supported') is True})
    completions = {'develop_town':['building_present'],'secure_resource':['target_owned','reserve_at_least'],
                   'reinforce_hero':['army_at_least'],'capture_target':['target_owned'],
                   'defend_area':['held_until'],'scout_frontier':['frontier_observed'],'preserve_force':['force_preserved_until']}
    for kind in KINDS:
        if not targets[kind] or (kind!='develop_town' and not heroes) or (kind=='develop_town' and not supported_buildings):continue
        variant = copy.deepcopy(goal)
        props = variant['properties']
        props['kind'] = {'type':'string','enum':[kind]}
        props['target_ref'] = refs_schema(targets[kind])
        props['actor_ref'] = {'type':'null'} if kind=='develop_town' else refs_schema(heroes)
        props['building_id'] = {**integer(-1,100000),'enum':supported_buildings if kind=='develop_town' else [-1]}
        predicate_props = props['complete_when']['properties']
        predicate_props['kind'] = {'type':'string','enum':completions[kind]}
        if kind=='scout_frontier':predicate_props['value'] = {**integer(0,0),'enum':[0]}
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
                                      'critical_towns':array(owned_town)})})
    properties = {'protocol':{**integer(2,2),'enum':[2]},
                  'request_id':{'type':'string','enum':[request['request_id']]},
                  'identity':_object({key:{'type':'string' if isinstance(value,str) else 'integer', 'enum':[value],
                                           **({} if isinstance(value,str) else {'minimum':0,'maximum':2147483647})}
                                      for key,value in request['identity'].items()}),
                  'decision':{'type':'string','enum':['retain','revise']}, 'reason':text,
                  'evidence_refs':array({'type':'string','enum':evidence(request)},1,8),
                  'victory_method':text,
                  'assignments':array(_object({'hero_ref':owned_hero,
                                               'role':{'type':'string','enum':list(ROLES)}, 'goal_ids':array(label,1)}),0,16),
                  'alternatives':array(_object({'approach':approach,'benefit':text,'cost':text,'uncertainty':text}),2,3),
                  'reconsider_when':array(_object({'goal_id':label,'kind':{'type':'string','enum':
                                              ['executor_lost','deadline_missed','route_not_established']}}),1),
                  'plan':{'anyOf':[{'type':'null'},plan]}}
    if request.get('experience',{}).get('mode') == 'learn':
        properties['learning'] = learning_schema(request['experience'])
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
    def byte_limits(value):
        if isinstance(value,dict):
            if value.get('type')=='string' and 'maxLength' in value:value['maxLength']*=4
            for item in value.values():byte_limits(item)
        elif isinstance(value,list):
            for item in value:byte_limits(item)
    byte_limits(byte_schema)
    _validate_shape(reply, byte_schema)
    plan = reply['plan'] if reply['decision'] == 'revise' else request.get('campaign')
    if reply['decision'] == 'retain':
        if reply['plan'] is not None or not plan: raise ValueError('retain requires a current campaign')
    elif not plan: raise ValueError('revise requires a complete campaign')
    goals = {g['id']:g for g in plan['goals']}
    if len(goals) != len(plan['goals']): raise ValueError('duplicate strategic goal')
    def visit(name, stack):
        if name not in goals or name in stack: raise ValueError('missing or cyclic dependency')
        for dep in goals[name]['depends_on']: visit(dep, stack|{name})
    for name in goals: visit(name,set())
    by_ref = {o['ref']:o for o in request['observation']['objects']}
    for g in goals.values():
        kind, predicate = g['kind'], g['complete_when']
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
    assigned = {a['hero_ref']:a for a in reply['assignments']}
    if len(assigned) != len(reply['assignments']) or sum(a['role']=='main' for a in assigned.values())>1:
        raise ValueError('conflicting strategic roles')
    for assignment in assigned.values():
        if any(name not in goals for name in assignment['goal_ids']): raise ValueError('assignment references an unknown goal')
    for goal in goals.values():
        actor = goal['actor_ref']
        if actor is not None and (actor not in assigned or goal['id'] not in assigned[actor]['goal_ids']):
            raise ValueError('goal actor has no consistent role')
    if any(c['goal_id'] not in goals for c in reply['reconsider_when']): raise ValueError('unknown reconsideration goal')
    if len({a['approach'] for a in reply['alternatives']}) != len(reply['alternatives']):
        raise ValueError('strategic alternatives must differ')
    if len(json.dumps(reply,ensure_ascii=False,separators=(',',':')).encode('utf-8')) > 7600:
        raise ValueError('strategy exceeds native reply budget')
    if 'learning' in reply:
        validate_learning(request['experience'],reply['learning'])
    if wire: reply['usage'] = usage
    return reply
