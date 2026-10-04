# Land Duel

Create the initial two-player scenario in an **isolated** game's Maps directory:

```sh
python3 scripts/create_scenario.py /absolute/path/to/private-profile/Maps/LandDuel.vmap
```

The command creates a new file and refuses to overwrite an existing map. It uses
Python's standard library and includes no licensed game assets. The map requires
the usual Heroes III data and the pinned VCMI build. ZIP metadata is fixed so the
same generator produces the same SHA-256 on macOS and Windows.

The 36 by 24 land-only map has red and blue Castle players. Each starts with one
hero, 40 pikemen, 20 archers, basic Leadership and Offence, and a town containing
a Fort, Town Hall and first-level dwelling. Catherine and Roland have the same
swordsman specialty; the scenario explicitly overrides their differing default
secondary skills. Starting resources still follow the selected VCMI difficulty.

Both sides have matching resource piles, a sawmill, an ore pit and a neutral
guard at matching distances from their starting town entrance. Town and mine
graphics retain their normal orientation and footprints. This is a compact
initial calibration map; it is not evidence of strategy quality on other maps.

Taverns and shipyards are forbidden in both towns. A Town Hall is already built
because its normal prerequisite is a tavern. No taverns, prisons, boats, portals,
spell scrolls or hero-granting objects are placed on the adventure map. Fly,
Water Walk, Town Portal, Dimension Door, Summon Boat and Scuttle Boat are banned.
Ordinary battle spells remain allowed. Either side wins by controlling both towns,
even if the opponent's hero remains alive.

Both player slots permit human or AI control. For spectator playtesting set
`players` to `{"red":"ExternalAI","blue":"Nullkiller2"}`, `headless` to `false`,
and `map_resource` to the generated map's resource path. The test configuration
selects difficulty; the header's difficulty describes the scenario itself. See
[playtesting](testing/llm-opponent-playtest.md) for isolated launch and recording.

Current runtime evidence is described in
[scenario and spectator verification](verification-land-duel-2026-10-04.md).
