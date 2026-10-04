"""Lossless, per-request sharing for the model input; engine protocol stays intact."""
from collections import Counter
import json


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
'''


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


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
    if not shared:
        return request
    envelope = {'reference_key':marker, 'shared':shared, 'request':encoded}
    # Definitions and their reading instruction must earn their overhead.
    if len(compact_json(envelope).encode('utf-8')) + len(SHARED_CONTEXT_INSTRUCTIONS.encode('utf-8')) >= len(compact_json(request).encode('utf-8')):
        return request
    return envelope
