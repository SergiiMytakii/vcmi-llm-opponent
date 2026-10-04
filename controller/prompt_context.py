"""Lossless, per-request sharing for the model input; engine protocol stays intact."""
from collections import Counter
import copy
import json

HISTORY_BYTES = 32768
SOFT_INPUT_BYTES = 131072

HISTORY_INSTRUCTIONS = '''
HISTORY PROJECTION
Only memory is budgeted; current observation, all offered actions and learning
evidence remain complete. A known_objects entry with facts_in_current_observation
true uses the visible_objects record with the same id for its current facts;
its own ref, dates and uncertainty flags still apply. Older confirmed results
may contain only action identity, costs and outcome, without old route forecasts.
Omitted historical sightings do not prove absence, removal, safety or ownership.
Unknown and stale data remain unknown and stale. Current plan, unresolved results,
referenced targets, enemy heroes/towns and wood/ore mines are protected, even when
they exceed the history budget. Never infer a battle victory from movement progress.
'''


SHARED_CONTEXT_INSTRUCTIONS = '''
SHARED JSON INPUT
When the input has shared, reference_key and request, the game request is inside
request. A one-key object whose key equals reference_key is a reference: its
integer value is a zero-based index into shared. Read it as that entire shared
value, recursively resolving any nested references. These are exact repeated
JSON values, not summaries or additional game facts. Apply the ordinary rules to
the fully expanded request, including actions, memory and experience. Preserve
each occurrence's surrounding fields and time: sharing does not merge sightings,
change uncertainty, or confirm execution. Output original offered action IDs and
request_id, never reference indices. Other one-key objects are ordinary data.
If object_key and fields are present, a one-key object keyed by object_key is
an encoded object: its array is [field_set_index, value1, value2, ...]. Pair the
names in fields[field_set_index] with these values, resolving references and
encoded objects recursively. Every original field is present, including null;
an absent field is different from null. Field sets only share JSON key names.
'''


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def bounded_history(request):
    """Project historical facts for this call; full authority and learning stay intact."""
    original = request.get('memory', {})
    size = lambda value:len(compact_json(value).encode('utf-8'))
    before = size(original)
    info = {'budget_bytes':HISTORY_BYTES, 'before_bytes':before,
            'after_bytes':before, 'applied':False, 'omitted_sightings':0,
            'summarized_results':0, 'current_fact_references':0,
            'over_budget':before > HISTORY_BYTES}
    if before <= HISTORY_BYTES:
        return request, info
    memory = copy.deepcopy(original)
    observation = request['observation']
    visible = {item.get('id'):item for item in observation.get('visible_objects', [])}
    timing = {'ref','last_seen_day','stale','not_seen_at_last_position'}
    for index,item in enumerate(memory.get('known_objects', [])):
        facts = {key:value for key,value in item.items() if key not in timing}
        if item.get('stale') is False and facts == visible.get(item.get('id')):
            memory['known_objects'][index] = {
                **{key:value for key,value in item.items() if key in timing or key == 'id'},
                'facts_in_current_observation':True}
            info['current_fact_references'] += 1
    if memory.get('own_heroes') == observation.get('heroes'):
        memory.pop('own_heroes', None)
    refs = set()

    def references(value):
        if isinstance(value, dict):
            for key,item in value.items():
                if key.endswith('_ref') and isinstance(item,str): refs.add(item)
                if key in ('object_id','id') and type(item) is int: refs.add('object:' + str(item))
                references(item)
        elif isinstance(value, list):
            for item in value: references(item)

    references(request['actions'])
    references(memory.get('plan', {}))
    references(memory.get('campaign', {}))
    references(memory.get('campaign_review', {}))
    references(observation.get('previous_unconfirmed_action', {}))
    for item in memory.get('recent_results', []):
        if item.get('outcome') == 'unconfirmed':
            references(item.get('action', {}))
    keep_action = {'id','kind','hero','town','destination','object_id','object_type',
                   'target_ref','target','chosen_in_request','owner','building',
                   'resource_type','resource_amount','resource_amount_visibility',
                   'amount','creature','cost'}
    results = memory.get('recent_results', [])
    for item in results[:-2]:
        action = item.get('action', {})
        if item.get('outcome') in ('completed','progress_observed') and action.get('target_ref') not in refs:
            shorter = {key:value for key,value in action.items() if key in keep_action}
            if shorter != action:
                item['action'] = shorter
                info['summarized_results'] += 1
    player = observation.get('player')
    day = observation.get('day', 0)
    known = memory.get('known_objects', [])

    def protected(item):
        owner = item.get('owner')
        return (item.get('ref') in refs
                or item.get('facts_in_current_observation') is True
                or (item.get('kind') in ('hero','town') and type(owner) is int and owner >= 0 and owner != player)
                or (item.get('kind') == 'mine' and item.get('resource_type') in ('wood','ore'))
                or (type(item.get('last_seen_day')) is int and type(day) is int and item['last_seen_day'] >= day - 2))

    removable = sorted((item for item in known if not protected(item)),
                       key=lambda item:(item.get('last_seen_day', -1), item.get('ref','')))
    for item in removable:
        if size(memory) <= HISTORY_BYTES:
            break
        known.remove(item)
        info['omitted_sightings'] += 1
    after = size(memory)
    info.update(after_bytes=after, applied=memory != original, over_budget=after > HISTORY_BYTES)
    return {**request, 'memory':memory}, info


def encode_request(request):
    """Return an equivalent JSON value, sharing only substantial exact repeats."""
    counts = Counter()
    keys = set()

    def signature(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)

    def count(value):
        if isinstance(value, (dict, list)):
            counts[signature(value)] += 1
            if isinstance(value, dict):
                keys.update(value)
                children = value.values()
            else:
                children = value
            for child in children:
                count(child)

    count(request)
    # Avoid confusing any existing game-data key with an encoding reference.
    marker = '$ref'
    while marker in keys:
        marker += '_'
    repeated = {key for key, count in counts.items()
                if count > 1 and len(key.encode('utf-8')) >= 160}
    shared, indices = [], {}

    def encode(value, definition=False):
        if not isinstance(value, (dict, list)):
            return value
        key = signature(value)
        if key in repeated and not definition:
            if key not in indices:
                item = encode(value, definition=True)
                indices[key] = len(shared)
                shared.append(item)  # Nested definitions precede their parents.
            return {marker:indices[key]}
        if isinstance(value, dict):
            return {name:encode(item) for name,item in value.items()}
        return [encode(item) for item in value]

    encoded = encode(request)
    envelope = {'reference_key':marker, 'shared':shared, 'request':encoded}
    object_marker = '$obj'
    while object_marker in keys:
        object_marker += '_'
    shapes = Counter()

    def count_shapes(value):
        if isinstance(value, dict):
            shapes[tuple(sorted(value))] += 1
            children = value.values()
        elif isinstance(value, list):
            children = value
        else:
            return
        for child in children:
            count_shapes(child)

    count_shapes(encoded)
    for value in shared:
        count_shapes(value)
    fields = [list(shape) for shape, count in shapes.items()
              if len(shape) >= 3 and count >= 3
              and count * (sum(len(compact_json(key)) for key in shape) + len(shape)
                           - len(compact_json(object_marker)) - 6) > len(compact_json(shape))]
    field_indices = {tuple(shape):index for index,shape in enumerate(fields)}

    def table(value):
        if isinstance(value, dict):
            shape = tuple(sorted(value))
            if shape in field_indices:
                return {object_marker:[field_indices[shape], *[table(value[key]) for key in shape]]}
            return {key:table(item) for key,item in value.items()}
        if isinstance(value, list):
            return [table(item) for item in value]
        return value

    if fields:
        tabular = {**envelope, 'object_key':object_marker, 'fields':fields,
                   'shared':[table(value) for value in shared], 'request':table(encoded)}
        if len(compact_json(tabular).encode('utf-8')) < len(compact_json(envelope).encode('utf-8')):
            envelope = tabular
    # Definitions and their reading instruction must earn their overhead.
    if len(compact_json(envelope).encode('utf-8')) + len(SHARED_CONTEXT_INSTRUCTIONS.encode('utf-8')) >= len(compact_json(request).encode('utf-8')):
        return request
    return envelope


def context_parts(request):
    """Measure actual serialized inputs, without estimating tokens from bytes."""
    size = lambda value:len(compact_json(value).encode('utf-8'))
    return {'actions':size(request.get('actions', [])),
            'observation':size(request.get('observation', {})),
            'memory':size(request.get('memory', {})),
            'experience':size(request.get('experience', {}))}
