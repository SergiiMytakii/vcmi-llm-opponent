"""Validate the ordered choices shared by the controller and decision recorder."""


def validate_batch(request, reply):
    if 'follow_up_action_ids' not in reply:
        return
    limit = request['observation'].get('batch_action_limit', 1)
    followups = reply['follow_up_action_ids']
    if type(limit) is not int or not 1 <= limit <= 32 or not isinstance(followups, list):
        raise ValueError('invalid action batch')
    choices = [reply['action_id'], *followups]
    offered = {a['id']: a['kind'] for a in request['actions']}
    if len(choices) > limit or any(not isinstance(i, str) or i not in offered for i in choices):
        raise ValueError('batch action was not offered or exceeds limit')
    if len(set(choices)) != len(choices):
        raise ValueError('duplicate batch action')
    if any(offered[i] == 'end_turn' for i in choices[:-1]):
        raise ValueError('end_turn must be the final batch action')
