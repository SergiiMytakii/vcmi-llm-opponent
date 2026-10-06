"""Lossless, per-request sharing for the model input; engine protocol stays intact."""
from collections import Counter, defaultdict
import copy
import json

HISTORY_BYTES = 32768
SOFT_INPUT_BYTES = 131072

HISTORY_INSTRUCTIONS = '''
## History projection
Only memory is budgeted; current observation, actions and learning evidence stay
complete. In known_objects, facts_in_current_observation=true references the
visible_objects entry with the same id; keep the memory entry's ref, dates and
uncertainty flags. Older confirmed results may omit route forecasts. Omitted
history proves no absence, safety, ownership change or battle victory. Active
plans, unresolved results, referenced targets, enemy heroes/towns and wood/ore
mines remain protected even above the history budget.
'''


SHARED_CONTEXT_INSTRUCTIONS = '''
## Lossless JSON encoding
With reference_key/shared/request, read the game request inside request.
A one-key object keyed by reference_key means shared[its integer value].
With object_key/fields, a one-key object keyed by object_key holds
[field_set_index, value1, ...]: pair fields[field_set_index] with those values.
If field_defaults is present, merge field_defaults[str(field_set_index)] into
the reconstructed object; omitted defaults mean {}. Defaults are encoded values.
Resolve both forms recursively, including defaults and strings. Other objects are ordinary
data. Encoding preserves every field, null, occurrence, date and uncertainty;
null differs from absence. Output original game refs, action IDs and request_id,
never encoding indices.
'''


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def without_unknown_army_values(value):
    """Hide native risk sentinels; intervals remain the factual model contract."""
    if isinstance(value, dict):
        interval = value.get('army_interval', {})
        unknown = (isinstance(interval, dict) and interval.get('status') in ('unknown', 'unbounded')
                   and 'upper' not in interval)
        return {key:without_unknown_army_values(item) for key,item in value.items()
                if not (unknown and key in ('army_value', 'army', 'observed_army'))}
    if isinstance(value, list):
        return [without_unknown_army_values(item) for item in value]
    return value


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
        current = visible.get(item.get('id'))
        if item.get('stale') is False and isinstance(current, dict) and facts == {
                key:value for key,value in current.items() if key not in timing}:
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

    references(request.get('actions',[]))
    references(request.get('campaign',{}))
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


def share_field_defaults(envelope):
    """Factor exact recurring cells from existing field rows when bytes are saved."""
    marker=envelope['object_key']
    groups=defaultdict(list)

    def collect(value):
        if isinstance(value,dict):
            if set(value)=={marker}: groups[value[marker][0]].append(value[marker][1:])
            for item in value.values(): collect(item)
        elif isinstance(value,list):
            for item in value: collect(item)

    collect(envelope['request'])
    for value in envelope['shared']: collect(value)
    fields=list(envelope['fields'])
    defaults,variants,common_columns={},{},{}
    for index,rows in groups.items():
        common={}
        for column in range(len(fields[index])):
            literal,count=Counter(compact_json(row[column]) for row in rows).most_common(1)[0]
            if count>=max(3,len(rows)*.6): common[column]=literal
        buckets=defaultdict(list)
        for row in rows:
            mask=tuple(column for column,literal in common.items() if compact_json(row[column])==literal)
            buckets[mask].append(row)
        for mask,matching in buckets.items():
            if not mask or len(matching)<3: continue
            varying=[key for column,key in enumerate(fields[index]) if column not in mask]
            fixed={fields[index][column]:json.loads(common[column]) for column in mask}
            next_index=len(fields)
            before=sum(len(compact_json({marker:[index,*row]})) for row in matching)
            after=sum(len(compact_json({marker:[next_index,*[cell for column,cell in enumerate(row) if column not in mask]]}))
                      for row in matching)
            overhead=len(compact_json(varying))+len(compact_json(fixed))+20
            if before-after<=overhead: continue
            fields.append(varying)
            defaults[str(next_index)]=fixed
            variants[(index,mask)]=next_index
        common_columns[index]=common

    def transform(value):
        if isinstance(value,dict):
            if set(value)=={marker}:
                index,*row=value[marker]
                common=common_columns.get(index,{})
                mask=tuple(column for column,literal in common.items() if compact_json(row[column])==literal)
                variant=variants.get((index,mask))
                if variant is not None:
                    return {marker:[variant,*[transform(cell) for column,cell in enumerate(row) if column not in mask]]}
            return {key:transform(item) for key,item in value.items()}
        if isinstance(value,list): return [transform(item) for item in value]
        return value

    if not defaults: return envelope
    candidate={**envelope,'fields':fields,'field_defaults':defaults,
               'request':transform(envelope['request']),'shared':[transform(value) for value in envelope['shared']]}
    return candidate if len(compact_json(candidate).encode('utf-8'))<len(compact_json(envelope).encode('utf-8')) else envelope


def encode_request(request):
    """Return an equivalent JSON value, sharing only substantial exact repeats."""
    counts = Counter()
    keys = set()

    def signature(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)

    def count(value):
        if isinstance(value, (dict, list, str)):
            counts[signature(value)] += 1
            if isinstance(value, dict):
                keys.update(value)
                children = value.values()
            elif isinstance(value, list):
                children = value
            else:
                children = ()
            for child in children:
                count(child)

    count(request)
    # Avoid confusing any existing game-data key with an encoding reference.
    marker = '$'
    while marker in keys:
        marker += '_'
    repeated = {key for key, count in counts.items()
                if count > 1 and len(key.encode('utf-8')) >= 100}
    shared, indices = [], {}

    def encode(value, definition=False):
        if not isinstance(value, (dict, list, str)):
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
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    encoded = encode(request)
    envelope = {'reference_key':marker, 'shared':shared, 'request':encoded}
    object_marker = '@'
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
            envelope = share_field_defaults(tabular)
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
