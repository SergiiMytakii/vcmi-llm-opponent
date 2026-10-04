"""Bounded model-authored intentions; observations and execution history stay engine-owned."""
import json


TEXT_FIELDS = ('goal', 'rationale', 'reserves', 'progress', 'change_reason')
LIST_FIELDS = ('steps', 'reconsider_if')
FIELDS = {*TEXT_FIELDS, *LIST_FIELDS, 'target_ref', 'executor_ref', 'ready_when', 'complete_when'}
CONDITIONS = ('unknown', 'always', 'day_at_least', 'army_strength_at_least', 'executor_at_target', 'target_owned', 'confirmed_action')
ACTION_KINDS = ('build', 'recruit', 'transfer', 'upgrade')


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
