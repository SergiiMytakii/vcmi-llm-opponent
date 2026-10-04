"""Create the two-player land duel as a deterministic VCMI map, without game assets."""
import argparse
import json
from pathlib import Path
import zipfile


def template(animation, mask, entrances=None):
    return {"animation": animation, "editorAnimation": animation, "mask": mask,
            "visitableFrom": entrances or ["+++", "+-+", "+++"]}


def scenario():
    """Equal starting armies/economies; capture both towns wins for either side."""
    width, height = 36, 24
    players, objects = {}, {}
    south = ["---", "+-+", "+++"]
    town_template = template("AVCCASX0", ["VVVVVV", "VVVVVV", "VVVVVV",
                                               "VVBBBV", "VBBBBB", "VBBABB"], south)
    hero_template = template("AH00_", ["VV", "AV"])
    hero_template["editorAnimation"] = "AH00_E"
    army = [{"type": "core:pikeman", "amount": 40},
            {"type": "core:archer", "amount": 20}]

    def add(kind, subtype, x, y, appearance, options):
        name = f"{kind}_{len(objects)}"
        objects[name] = {"type": kind, "subtype": subtype, "x": x, "y": y, "l": 0,
                         "template": appearance, "options": options}
        return name

    for color, hero_type, entrance_x, direction in (
            ("red", "catherine", 5, 1), ("blue", "roland", 30, -1)):
        add("town", "castle", entrance_x + 2, 11,
            town_template, {"owner": color, "buildings": {
                "allOf": ["fort", "townHall", "dwellingLvl1"],
                "noneOf": ["tavern", "shipyard"]}})
        # Hero's sprite anchor is one tile east of its visitable position.
        hero_name = add("hero", "knight", entrance_x + 1, 11, hero_template,
            {"owner": color, "type": hero_type, "experience": 0,
             "army": [dict(stack) for stack in army],
             "secondarySkills": [{"skill": "leadership", "level": "basic"},
                                 {"skill": "offence", "level": "basic"}]})
        players[color] = {
            "canPlay": "PlayerOrAI", "mainHero": hero_name,
            "heroes": {hero_name: {"type": hero_type}},
            "mainTown": {"x": entrance_x + 2, "y": 11, "l": 0, "generateHero": False},
            "allowedFactions": {"anyOf": ["core:castle"]},
        }
        # Identical resources at matching distances from the two entrances.
        for subtype, dx, y, amount, animation in (
                ("wood", 2, 13, 10, "AVTWOOD0"),
                ("ore", 2, 9, 10, "AVTORE0"),
                ("gold", 4, 11, 1500, "AVTGOLD0"),
                ("crystal", 4, 15, 5, "AVTCRYS0")):
            add("resource", subtype, entrance_x + direction * dx,
                y, template(animation, ["VA"]), {"amount": amount})
        add("mine", "sawmill", entrance_x + direction * 4 + 1,
            18, template("AVMSAWD0", ["VVVVV", "VVVBB", "VBBAB"], south), {})
        add("mine", "orePit", entrance_x + direction * 6 + 1,
            5, template("AVMORDR0", ["BBB", "BAB"], south), {})
        add("monster", "pikeman", entrance_x + direction * 7,
            14, template("AVWPIKE", ["VV", "VA"]),
            {"amount": 15, "character": "hostile", "neverFlees": True, "noGrowing": True})

    header = {
        "versionMajor": 1, "versionMinor": 0, "name": "External AI - Land Duel",
        "description": "Two equal Castle starts. One hero per side; no hero recruitment, "
                       "boats or adventure movement spells. Capture the opposing town to win.",
        "author": "vcmi-llm-opponent", "mapVersion": "1.0",
        "difficulty": "NORMAL", "mods": [],
        "mapLevels": {"surface": {"width": width, "height": height, "index": 0}},
        "players": players, "allowedHeroes": {}, "allowedAbilities": {},
        "allowedArtifacts": {}, "allowedSpells": {"noneOf": [
            "core:dimensionDoor", "core:fly", "core:waterWalk", "core:townPortal",
            "core:summonBoat", "core:scuttleBoat"]},
        "victoryIconIndex": 11, "defeatIconIndex": 0,
        "triggeredEvents": {
            "captureTowns": {"condition": ["control", {"type": "town"}],
                             "effect": {"type": "victory", "messageToSend": "Opponent captured both towns."},
                             "message": "You captured both towns."},
            "noTown": {"condition": ["daysWithoutTown", {"value": 7}],
                       "effect": {"type": "defeat", "messageToSend": "Opponent lost all towns."},
                       "message": "You have no town."},
        },
    }
    # Dirt interior frames need no neighbouring-terrain transitions on this land-only map.
    terrain = [["dt40_" for _ in range(width)] for _ in range(height)]
    return {"header.json": header, "objects.json": objects, "surface_terrain.json": terrain}


def write_map(destination):
    # Exclusive creation protects previous playtest inputs. Stable ZIP metadata keeps hashes reproducible.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in scenario().items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, json.dumps(value, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New .vmap file in your isolated profile's Maps directory")
    destination = parser.parse_args().destination
    write_map(destination)
    print(destination)
