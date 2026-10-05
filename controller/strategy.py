"""Bounded model-authored intentions; observations and execution history stay engine-owned."""
import json


TEXT_FIELDS = ('goal', 'rationale', 'reserves', 'progress', 'change_reason')
LIST_FIELDS = ('steps', 'reconsider_if')
FIELDS = {*TEXT_FIELDS, *LIST_FIELDS, 'target_ref', 'executor_ref', 'ready_when', 'complete_when'}
CONDITIONS = ('unknown', 'always', 'day_at_least', 'army_strength_at_least', 'executor_at_target', 'target_owned', 'confirmed_action')
ACTION_KINDS = ('build', 'recruit', 'transfer', 'upgrade', 'hire_hero')


def known_targets(request):
    refs = {item['ref'] for item in request.get('memory', {}).get('known_objects', [])}
    refs.update(a['target_ref'] for a in request['actions'] if 'target_ref' in a)
    plan = request.get('memory', {}).get('plan')
    if plan and plan.get('target_ref'):
        refs.add(plan['target_ref'])
    return sorted(refs)


def owned_executors(request):
    return sorted('object:' + str(h['id']) for h in request.get('observation', {}).get('heroes', []))


def validate_condition(condition, completion=False):
    if not isinstance(condition, dict) or set(condition) != {'kind', 'value'}:
        raise ValueError('condition must contain kind and value')
    kind, value = condition['kind'], condition['value']
    if kind not in CONDITIONS or (completion and kind == 'always'):
        raise ValueError('unsupported condition')
    if kind in ('day_at_least', 'army_strength_at_least'):
        if type(value) is not int or not 0 <= value <= 2**31-1:
            raise ValueError('invalid condition threshold')
    elif kind == 'confirmed_action':
        if value not in ACTION_KINDS:
            raise ValueError('invalid confirmed action kind')
    elif value is not None:
        raise ValueError('condition takes no value')


def validate_strategy(request, strategy):
    if strategy is None:  # Explicitly retain the previous plan, including on fallback.
        return
    if not isinstance(strategy, dict) or set(strategy) != FIELDS:
        raise ValueError('strategy must contain only plan fields')
    for key in TEXT_FIELDS:
        if not isinstance(strategy[key], str) or not 1 <= len(strategy[key].encode('utf-8')) <= 240:
            raise ValueError('invalid strategy text: ' + key)
    for key in LIST_FIELDS:
        if not isinstance(strategy[key], list) or not 1 <= len(strategy[key]) <= 4:
            raise ValueError('invalid strategy list: ' + key)
        if any(not isinstance(s, str) or not 1 <= len(s.encode('utf-8')) <= 160 for s in strategy[key]):
            raise ValueError('invalid strategy step or reconsideration condition')
    if strategy['executor_ref'] is not None and strategy['executor_ref'] not in owned_executors(request):
        raise ValueError('executor is not an owned hero')
    validate_condition(strategy['ready_when'])
    validate_condition(strategy['complete_when'], completion=True)
    for key in ('ready_when', 'complete_when'):
        kind = strategy[key]['kind']
        if kind in ('army_strength_at_least', 'executor_at_target') and strategy['executor_ref'] is None:
            raise ValueError('condition requires executor')
        if kind in ('target_owned', 'executor_at_target', 'confirmed_action') and strategy['target_ref'] is None:
            raise ValueError('condition requires target')
    if strategy['target_ref'] is not None and strategy['target_ref'] not in known_targets(request):
        raise ValueError('strategy target was never observed')
    if len(json.dumps(strategy, ensure_ascii=False).encode('utf-8')) > 4096:
        raise ValueError('strategy exceeds 4096 bytes')


def strategy_schema(request):
    fields = {key: {'type': 'string', 'minLength': 1, 'maxLength': 240} for key in TEXT_FIELDS}
    fields.update({key: {'type': 'array', 'minItems': 1, 'maxItems': 4,
                         'items': {'type': 'string', 'minLength': 1, 'maxLength': 160}}
                   for key in LIST_FIELDS})
    fields['executor_ref'] = {'type': ['string', 'null'], 'enum': [None, *owned_executors(request)]}
    for key in ('ready_when', 'complete_when'):
        kinds = [k for k in CONDITIONS if key != 'complete_when' or k != 'always']
        fields[key] = {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'value'],
                       'properties': {'kind': {'type': 'string', 'enum': kinds},
                                      'value': {'anyOf': [{'type': 'null'}, {'type': 'integer', 'minimum': 0, 'maximum': 2**31-1},
                                                          {'type': 'string', 'enum': list(ACTION_KINDS)}]}}}
    fields['target_ref'] = {'type': ['string', 'null'], 'enum': [None, *known_targets(request)]}
    return {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': False,
                                      'required': sorted(FIELDS), 'properties': fields}]}


# Intent budgets leave room for the operational plan, batch and learning under
# the native 8 KiB reply cap. These are storage limits, never hero-count limits.
CAMPAIGN_BYTES = 4096
APPROACHES = ('economy', 'expansion', 'breakthrough', 'defense', 'conquest')
ROLES = ('main', 'defender', 'scout', 'collector', 'reinforcement')
RESOURCES = ('wood', 'mercury', 'ore', 'sulfur', 'crystal', 'gems', 'gold')


def campaign_evidence(request):
    observation = request['observation']
    refs = ['observation:' + key for key in ('day', 'resources', 'victory', 'rules') if key in observation]
    refs += ['hero:object:' + str(h['id']) for h in observation.get('heroes', [])]
    refs += ['town:object:' + str(t['id']) for t in observation.get('towns', [])]
    refs += ['target:' + ref for ref in known_targets(request)]
    refs += ['result:' + str(r['sequence']) for r in request.get('memory', {}).get('recent_results', [])
             if r.get('outcome') in ('completed', 'progress_observed') and type(r.get('sequence')) is int]
    return sorted(set(refs))


def _object(properties):
    return {'type': 'object', 'additionalProperties': False, 'required': sorted(properties), 'properties': properties}


def campaign_schema(request):
    text = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    target = {'type': ['string', 'null'], 'enum': [None, *known_targets(request)]}
    hero = {'type': 'string', 'enum': owned_executors(request)}
    # Empty enum is invalid JSON Schema. No hero is assignable when none is owned.
    if not hero['enum']: hero = {'type': 'string', 'pattern': '^$'}
    nullable_hero = {'type': ['string', 'null'], 'enum': [None, *owned_executors(request)]}
    evidence = {'type': 'string', 'enum': campaign_evidence(request)}
    day = request['observation'].get('day', 0)
    approach = {'type': 'string', 'enum': list(APPROACHES)}
    array = lambda item, minimum, maximum: {'type': 'array', 'minItems': minimum, 'maxItems': maximum, 'items': item}
    plan = _object({
        'victory_method': text, 'approach': approach, 'main_hero_ref': nullable_hero,
        'horizon_day': {'type': 'integer', 'minimum': day + 3, 'maximum': day + 7},
        'advantages': array(_object({'fact_ref': evidence, 'benefit': text, 'constraint': text}), 2, 3),
        'milestones': array(_object({'target_ref': target, 'executor_ref': nullable_hero,
                                    'due_day': {'type': 'integer', 'minimum': day, 'maximum': day + 7}, 'expected': text}), 1, 6),
        'assignments': array(_object({'hero_ref': hero, 'role': {'type': 'string', 'enum': list(ROLES)},
                                     'target_ref': target, 'task': text}), 0, 16),
        'reserves': array(_object({'resource': {'type': 'string', 'enum': list(RESOURCES)},
                                  'amount': {'type': 'integer', 'minimum': 0, 'maximum': 2**31-1},
                                  'purpose': text, 'release_if': text}), 0, 7),
        'alternatives': array(_object({'approach': approach, 'benefit': text, 'cost': text,
                                      'risk': text, 'abandon_if': text}), 2, 3)})
    return {'anyOf': [{'type': 'null'}, _object({
        'decision': {'type': 'string', 'enum': ['retain', 'revise']}, 'reason': text,
        'evidence_refs': array(evidence, 1, 4), 'plan': {'anyOf': [{'type': 'null'}, plan]}})]}


def _validate_shape(value, schema):
    """Small closed-schema validator shared by all bounded campaign records."""
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:
                _validate_shape(value, option)
                return
            except ValueError:
                pass
        raise ValueError('invalid campaign record')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('unknown campaign reference or value')
    kind = schema.get('type')
    if isinstance(kind, list):
        if value is None and 'null' in kind: return
        kind = next(k for k in kind if k != 'null')
    if kind == 'null':
        if value is not None: raise ValueError('campaign value must be null')
    elif kind == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['required']):
            raise ValueError('campaign contains missing or factual fields')
        for key, item in value.items(): _validate_shape(item, schema['properties'][key])
    elif kind == 'array':
        if not isinstance(value, list) or not schema['minItems'] <= len(value) <= schema['maxItems']:
            raise ValueError('campaign array exceeds budget')
        for item in value: _validate_shape(item, schema['items'])
    elif kind == 'string':
        if not isinstance(value, str) or not value or len(value.encode('utf-8')) > schema.get('maxLength', 160):
            raise ValueError('campaign text exceeds UTF-8 budget')
    elif kind == 'integer':
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            raise ValueError('campaign integer exceeds bounds')
    elif kind == 'boolean':
        if type(value) is not bool: raise ValueError('campaign value must be boolean')
    elif kind == 'number':
        import math
        if type(value) not in (int, float) or not math.isfinite(value) or not schema['minimum'] <= value <= schema['maximum']:
            raise ValueError('campaign number exceeds bounds')


def validate_campaign(request, update, strategy=None):
    if update is None: return  # Fallback or no assessment never acknowledges review.
    _validate_shape(update, campaign_schema(request))
    if len(json.dumps(update, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > CAMPAIGN_BYTES:
        raise ValueError('campaign exceeds byte budget')
    memory = request.get('memory', {})
    if update['decision'] == 'retain':
        if update['plan'] is not None or not memory.get('campaign'):
            raise ValueError('retain requires an existing campaign and null plan')
        plan = memory['campaign']
    else:
        plan = update['plan']
        if plan is None: raise ValueError('revise requires a complete campaign')
        if len({a['approach'] for a in plan['alternatives']}) != len(plan['alternatives']):
            raise ValueError('campaign alternatives must differ')
        if plan['approach'] not in {a['approach'] for a in plan['alternatives']}:
            raise ValueError('chosen approach must be compared')
        if any(m['due_day'] > plan['horizon_day'] for m in plan['milestones']):
            raise ValueError('milestone exceeds campaign horizon')
    heroes = owned_executors(request)
    if plan['main_hero_ref'] is not None and plan['main_hero_ref'] not in heroes:
        raise ValueError('campaign main hero is no longer owned')
    assignments = {a['hero_ref']: a for a in plan['assignments']}
    if len(assignments) != len(plan['assignments']) or any(h not in heroes for h in assignments):
        raise ValueError('hero has duplicate assignments or is no longer owned')
    main = [a['hero_ref'] for a in assignments.values() if a['role'] == 'main']
    if main != ([plan['main_hero_ref']] if plan['main_hero_ref'] else []):
        raise ValueError('main hero must have exactly its main assignment')
    targets = [a['target_ref'] for a in assignments.values() if a['target_ref'] is not None]
    if len(set(targets)) != len(targets): raise ValueError('heroes compete for one target')
    absent = {o['ref'] for o in memory.get('known_objects', []) if o.get('not_seen_at_last_position') is True}
    if any(target in absent for target in targets):
        raise ValueError('assignment target is absent at its last observed position')
    resources = [r['resource'] for r in plan['reserves']]
    if len(resources) != len(set(resources)): raise ValueError('reserve is counted twice')
    promised_targets = {}
    for milestone in plan['milestones']:
        executor, target = milestone['executor_ref'], milestone['target_ref']
        if executor is None: continue
        if executor not in assignments:
            raise ValueError('milestone executor has no assignment')
        if target is not None and any(a['hero_ref'] != executor and a['target_ref'] == target for a in assignments.values()):
            raise ValueError('milestone competes with another hero assignment')
        if target is not None:
            key = (target, milestone['due_day'])
            if key in promised_targets and promised_targets[key] != executor:
                raise ValueError('heroes promise the same milestone target')
            promised_targets[key] = executor
    operational = strategy if strategy is not None else memory.get('plan')
    if operational and operational['executor_ref'] is not None:
        assignment = assignments.get(operational['executor_ref'])
        if assignment is None or assignment['target_ref'] != operational['target_ref']:
            raise ValueError('operational objective conflicts with campaign assignment')
