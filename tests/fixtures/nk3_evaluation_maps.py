"""Frozen land-only comparison scenarios; no game assets or model instructions."""
import copy
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from create_scenario import scenario


def comparison_maps():
    duel = scenario()
    duel['header.json']['name'] = 'NK3 comparison - small duel v1'
    multiple = copy.deepcopy(duel)
    multiple['header.json']['name'] = 'NK3 comparison - multiple towns v1'
    multiple['header.json']['description'] = (
        'Two Castle towns and two heroes per player. Land only; capture all towns. '
        'No hero recruitment or adventure movement spells.')
    objects = multiple['objects.json']
    for color, hero_type in [('red', 'christian'), ('blue', 'adela')]:
        town = copy.deepcopy(next(o for o in objects.values()
                                  if o['type'] == 'town' and o['options']['owner'] == color))
        town['y'] = 22
        objects['town_secondary_' + color] = town
        hero = copy.deepcopy(next(o for o in objects.values()
                                  if o['type'] == 'hero' and o['options']['owner'] == color))
        hero['y'] = 20
        hero['options']['type'] = hero_type
        for stack in hero['options']['army']:
            stack['amount'] //= 2
        name = 'hero_secondary_' + color
        objects[name] = hero
        multiple['header.json']['players'][color]['heroes'][name] = {'type': hero_type}

    limited = copy.deepcopy(duel)
    limited['header.json']['name'] = 'NK3 comparison - scarce resources v1'
    limited['header.json']['description'] = (
        'Equal Castle starts with smaller armies, Village Halls, no loose resource '
        'pickups and stronger neutral guards. Land only; capture all towns. '
        'No hero recruitment or adventure movement spells.')
    objects = limited['objects.json']
    for name in list(objects):
        obj = objects[name]
        if obj['type'] == 'resource':
            del objects[name]
        elif obj['type'] == 'town':
            buildings = obj['options']['buildings']['allOf']
            buildings[buildings.index('townHall')] = 'villageHall'
        elif obj['type'] == 'hero':
            for stack in obj['options']['army']:
                stack['amount'] //= 2
        elif obj['type'] == 'monster':
            obj['options']['amount'] *= 2
    return {'small_duel': duel, 'multiple_towns': multiple, 'scarce_resources': limited}


def write_comparison_maps(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in comparison_maps().items():
        with zipfile.ZipFile(directory / (name + '.vmap'), 'x', zipfile.ZIP_DEFLATED) as archive:
            for filename, value in data.items():
                info = zipfile.ZipInfo(filename, (2026, 10, 5, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, json.dumps(value, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    write_comparison_maps(sys.argv[1])
