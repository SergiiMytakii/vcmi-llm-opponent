"""Native action and real controller UTF-8 channel proof, with scripted choices."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'controller'))
import main as controller_main

def fixture_choice(request):
    actions = request['actions']
    index = request['request_id'].split(':')
    if index[1:] == ['1', '0']:
        action = next(a for a in actions if a['kind'] == 'build' and a['building'].endswith('dwellingUpLvl2'))
    elif index[1:] == ['1', '1']:
        action = next((a for a in actions if a['kind'] == 'upgrade' and a['from_creature'] == 'core:archer'), actions[0])
    elif index[1:] == ['1', '2']:
        moves = [a for a in actions if a['kind'] in ('visit', 'explore') and a.get('turn_stop', {}).get('condition') == 'unchanged_route']
        action = min(moves, key=lambda a: a['travel_turns']) if moves else actions[0]
    elif index[1:] == ['2', '0']:
        moves = [a for a in actions if a['kind'] == 'visit'
                 and a.get('route_encounters') and a['route_encounters'][0].get('stops_before_tile')]
        action = min(moves, key=lambda a: a['travel_turns']) if moves else actions[0]
    else:
        action = next(a for a in actions if a['kind'] == 'end_turn')
    reply = {'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id'],
             'strategy': {'goal': 'Проверить действие', 'target_ref': action.get('target_ref'),
                          'rationale': 'Сила 5720–6880; проверка команды', 'steps': ['Выполнить команду'],
                          'reserves': 'Проверить цену', 'reconsider_if': ['Действие недоступно'],
                          'executor_ref': None, 'ready_when': {'kind': 'always', 'value': None},
                          'complete_when': {'kind': 'unknown', 'value': None},
                          'progress': 'Нативная проверка', 'change_reason': 'Следующий шаг проверки'}}
    return reply, {'provider': 'scripted_native_probe'}

controller_main.choose = fixture_choice
controller_main.main()
