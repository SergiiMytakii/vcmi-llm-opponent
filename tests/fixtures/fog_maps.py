"""Create paired integration fixtures for player-visible observation checks.

Run from the repository root with a new output directory. These are diagnostic
variants, not calibration maps; never feed their hidden mutations to a game model.
"""
import copy
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from create_scenario import scenario


def variants():
    base = scenario()
    objects = base["objects.json"]
    # This neutral is within the red player's initial sight; the right-hand side
    # is well outside it. Preserve all instance IDs and object ordering.
    guard = next(k for k, v in objects.items() if v["type"] == "monster" and v["x"] < 18)
    objects[guard]["x"] = 9
    result = {"base": base}
    hidden = copy.deepcopy(base)
    for item in hidden["objects.json"].values():
        if item["x"] > 20:
            if item["type"] == "hero":
                item["options"]["army"][0]["amount"] = 40000
            if item["type"] in ("monster", "resource"):
                item["options"]["amount"] *= 100
    # A distant tile's terrain must not influence currently offered routes.
    hidden["surface_terrain.json"][20][32] = "gr40_"
    result["hidden"] = hidden
    distant_resource = next(k for k, v in objects.items() if v['type'] == 'resource' and v['x'] > 20)
    inserted = copy.deepcopy(base)
    inserted['objects.json']['resource_1000'] = copy.deepcopy(objects[distant_resource])
    inserted['objects.json']['resource_1000'].update(x=33, y=22)
    result['hidden_insert'] = inserted
    removed = copy.deepcopy(base)
    del removed['objects.json'][distant_resource]
    result['hidden_remove'] = removed
    for name, count in (("same_category", 19), ("different_category", 21)):
        changed = copy.deepcopy(base)
        changed["objects.json"][guard]["options"]["amount"] = count
        result[name] = changed
    return result


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in variants().items():
        with zipfile.ZipFile(destination / (name + ".vmap"), "x", zipfile.ZIP_DEFLATED) as archive:
            for filename, value in data.items():
                info = zipfile.ZipInfo(filename, (2026, 10, 4, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, json.dumps(value, separators=(",", ":")))
    print(destination)
