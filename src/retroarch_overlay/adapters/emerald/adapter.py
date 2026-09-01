import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ...models import OverlaySnapshot, PanelRow, PanelSection, RetroArchStatus
from ...retroarch import MemoryReader, RetroArchError
from .achievements import GYM_MISSABLES, NEARBY_ACHIEVEMENTS, TRICK_HOUSE_MISSABLES
from .battle import BALLS, ball_multiplier, catch_probability
from .feebas import feebas_spot_ids, load_route119_fishing_spots, tile_in_front
from .manifest import RA_GAME_ID, RA_HASHES


SAVE_BLOCK_1_POINTER = 0x03005D8C
SAVE_BLOCK_2_POINTER = 0x03005D90
POKEDEX_OWNED_OFFSET = 0x28
DEX_FLAG_BYTES = 52
FLAGS_OFFSET = 0x1270
FLAGS_SIZE = 0x160
REMATCHES_OFFSET = 0x9CA
REMATCHES_SIZE = 100
DEWFORD_TREND_SEED_OFFSET = 0x2E66
PLAYER_POSITION_ADDRESS = 0x0203F360
BATTLE_TYPE_FLAGS_ADDRESS = 0x02022FEC
BATTLERS_COUNT_ADDRESS = 0x0202406C
BATTLE_MONS_ADDRESS = 0x02024084
BATTLE_RESULTS_TURN_ADDRESS = 0x03005D23
MAIN_IN_BATTLE_ADDRESS = 0x030026F9
MAIN_IN_BATTLE_MASK = 0x02
BATTLE_MON_SIZE = 0x58
BALL_POCKET_OFFSET = 0x650
BALL_POCKET_SIZE = 64
SECURITY_KEY_OFFSET = 0xAC
ROAMER_OFFSET = 0x31DC
ROAMER_SIZE = 0x1C
ROAMER_LOCATION_ADDRESS = 0x0203BC86
ITEM_POCKET_OFFSET = 0x560
ITEM_POCKET_SIZE = 80
BERRY_POCKET_OFFSET = 0x790
BERRY_POCKET_SIZE = 184
DECORATION_INVENTORY_OFFSET = 0x2734
DECORATION_INVENTORY_SIZE = 150
SECRET_BASE_DECORATIONS_OFFSET = 0x1AAE
SECRET_BASE_DECORATIONS_SIZE = 16
BADGE_FLAG_START = 0x867
EWRAM_START = 0x02000000
EWRAM_END = 0x02040000

POC_GATES = (
    (0, "Roxanne", 39),
    (2, "Wattson", 66),
    (3, "Flannery", 90),
    (1, "Brawly", 101),
    (4, "Norman", 101),
    (6, "Tate & Liza", 156),
    (7, "Juan", 167),
    (5, "Winona", 171),
)

HM_FLAGS = (0x89, 0x6E, 0x7A, 0x6A, 0x6D, 0x6B, 0x7B, 0x138)
FLUTE_ITEM_IDS = frozenset(range(39, 44))

TYPE_NAMES = (
    "Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug",
    "Ghost", "Steel", "Mystery", "Fire", "Water", "Grass", "Electric",
    "Psychic", "Ice", "Dragon", "Dark",
)


def _normalize_map_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.removeprefix("MAP_").upper())


def _display_constant(value: str, prefix: str) -> str:
    words = value.removeprefix(prefix).split("_")
    label = " ".join(word.capitalize() for word in words)
    return re.sub(r"(?<=\D)(?=\d)", " ", label)


def _display_map_name(value: str) -> str:
    parts = []
    for part in value.split("_"):
        label = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=\D)(?=\d)", " ", part)
        parts.append(label.replace("Pokemon", "Pokémon"))
    return " · ".join(parts)


def _parse_numeric_defines(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"#define\s+(\w+)\s+(.+?)(?:\s*//.*)?$", line)
        if not match:
            continue
        name, expression = match.groups()
        expression = expression.strip().strip("()")
        if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", expression):
            values[name] = int(expression, 0)
            continue
        addition = re.fullmatch(
            r"([A-Z0-9_]+)\s*\+\s*(0x[0-9A-Fa-f]+|\d+)", expression
        )
        if addition and addition.group(1) in values:
            values[name] = values[addition.group(1)] + int(addition.group(2), 0)
            continue
        if expression in values:
            values[name] = values[expression]
    return values


def _objective_label(name: str, location_key: str) -> str:
    text = name.removeprefix("FLAG_")
    for prefix in ("HIDDEN_ITEM_", "ITEM_", "DEFEATED_", "RECEIVED_", "DELIVERED_", "RETURNED_", "RECOVERED_", "MET_"):
        text = text.removeprefix(prefix)
    text = text.replace(location_key, "").strip("_")
    return _display_constant(text, "")


class EmeraldAdapter:
    name = "Pokémon Emerald"
    ra_game_id = RA_GAME_ID
    ra_hashes = RA_HASHES

    def __init__(self, pokeemerald_root: Path):
        encounters_path = pokeemerald_root / "src" / "data" / "wild_encounters.json"
        groups_path = pokeemerald_root / "data" / "maps" / "map_groups.json"
        pokedex_path = pokeemerald_root / "include" / "constants" / "pokedex.h"
        species_path = pokeemerald_root / "include" / "constants" / "species.h"
        flags_path = pokeemerald_root / "include" / "constants" / "flags.h"
        opponents_path = pokeemerald_root / "include" / "constants" / "opponents.h"
        with encounters_path.open(encoding="utf-8") as file:
            encounter_document = json.load(file)
        with groups_path.open(encoding="utf-8") as file:
            group_document = json.load(file)

        group = encounter_document["wild_encounter_groups"][0]
        self._field_definitions = {field["type"]: field for field in group["fields"]}
        self._encounters = {entry["map"]: entry for entry in group["encounters"]}
        self._national_dex_numbers = self._load_national_dex_numbers(pokedex_path)
        self._species_ids = _parse_numeric_defines(species_path)
        self._species_by_id = {value: name for name, value in self._species_ids.items()}
        self._catch_rates = self._load_catch_rates(
            pokeemerald_root / "src" / "data" / "pokemon" / "species_info.h"
        )
        self._flag_ids = _parse_numeric_defines(flags_path)
        self._trainer_ids = _parse_numeric_defines(opponents_path)
        self._map_names_by_id = self._build_map_names(group_document)
        self._map_constants_by_id = self._build_map_constants(group_document)
        self.map_ids = self._build_map_ids(group_document, self._encounters)
        self._encounters_by_id = {
            self.map_ids[map_name]: encounter
            for map_name, encounter in self._encounters.items()
        }
        self._route_trackers = self._build_route_trackers(pokeemerald_root)
        self._item_locations = self._load_item_locations(pokeemerald_root)
        self._nearby_achievements = {
            map_name: tuple(
                achievement
                for achievement in NEARBY_ACHIEVEMENTS
                if achievement.map_name == map_name
            )
            for map_name in {achievement.map_name for achievement in NEARBY_ACHIEVEMENTS}
        }
        self._rematches_by_map = self._load_rematches(
            pokeemerald_root / "src" / "battle_setup.c"
        )
        self._route119_fishing_spots = load_route119_fishing_spots(pokeemerald_root)

    def _load_item_locations(
        self, pokeemerald_root: Path
    ) -> dict[str, tuple[tuple[str, int, int, int, bool], ...]]:
        locations = {}
        maps_root = pokeemerald_root / "data" / "maps"
        for map_id in self._map_constants_by_id.values():
            path = maps_root / map_id / "map.json"
            if not path.exists():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            map_items = []
            for event in document.get("object_events", ()):
                flag_name = event.get("flag", "")
                if event.get("graphics_id") != "OBJ_EVENT_GFX_ITEM_BALL":
                    continue
                flag_id = self._flag_ids.get(flag_name)
                if flag_id is not None:
                    map_items.append(
                        (
                            _objective_label(flag_name, self._location_key(map_id)),
                            event["x"],
                            event["y"],
                            flag_id,
                            False,
                        )
                    )
            for event in document.get("bg_events", ()):
                if event.get("type") != "hidden_item":
                    continue
                flag_id = self._flag_ids.get(event.get("flag", ""))
                if flag_id is not None:
                    map_items.append(
                        (
                            _display_constant(event["item"], "ITEM_"),
                            event["x"],
                            event["y"],
                            flag_id,
                            True,
                        )
                    )
            if map_items:
                locations[map_id] = tuple(map_items)
        return locations

    @staticmethod
    def _location_key(map_name: str) -> str:
        return re.sub(
            r"(?<=[A-Za-z])(?=\d)",
            "_",
            re.sub(r"(?<=[a-z])(?=[A-Z])", "_", map_name),
        ).upper()

    @staticmethod
    def _load_national_dex_numbers(path: Path) -> dict[str, int]:
        numbers: dict[str, int] = {}
        in_national_order = False
        value = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().rstrip(",")
            if stripped == "enum {" and not in_national_order:
                in_national_order = True
                continue
            if not in_national_order:
                continue
            if stripped == "};":
                break
            if stripped.startswith("NATIONAL_DEX_"):
                species = stripped.replace("NATIONAL_DEX_", "SPECIES_", 1)
                numbers[species] = value
                value += 1
        return numbers

    @staticmethod
    def _load_catch_rates(path: Path) -> dict[str, int]:
        text = path.read_text(encoding="utf-8")
        entries = re.split(
            r"(?=^\s*\[SPECIES_[A-Z0-9_]+\]\s*=)", text, flags=re.MULTILINE
        )
        rates = {}
        for entry in entries:
            species = re.match(r"\s*\[(SPECIES_[A-Z0-9_]+)\]", entry)
            catch_rate = re.search(r"\.catchRate\s*=\s*(\d+)", entry)
            if species and catch_rate:
                rates[species.group(1)] = int(catch_rate.group(1))
        return rates

    @staticmethod
    def _build_map_names(document: dict[str, Any]) -> dict[tuple[int, int], str]:
        return {
            (group_number, map_number): _display_map_name(map_name)
            for group_number, group_name in enumerate(document["group_order"])
            for map_number, map_name in enumerate(document[group_name])
        }

    @staticmethod
    def _build_map_constants(document: dict[str, Any]) -> dict[tuple[int, int], str]:
        return {
            (group_number, map_number): map_name
            for group_number, group_name in enumerate(document["group_order"])
            for map_number, map_name in enumerate(document[group_name])
        }

    def _build_route_trackers(
        self, pokeemerald_root: Path
    ) -> dict[str, tuple[dict[str, tuple[int, ...]], dict[str, int], dict[str, int]]]:
        trackers = {}
        maps_root = pokeemerald_root / "data" / "maps"
        for map_name in self._map_constants_by_id.values():
            script_path = maps_root / map_name / "scripts.inc"
            if not script_path.exists():
                continue
            script = script_path.read_text(encoding="utf-8")
            trainer_groups: dict[str, list[int]] = {}
            for trainer_name in set(re.findall(r"\bTRAINER_[A-Z0-9_]+", script)):
                trainer_id = self._trainer_ids.get(trainer_name)
                if trainer_id is None:
                    continue
                group = re.sub(r"^TRAINER_(?:MAY|BRENDAN)_", "TRAINER_RIVAL_", trainer_name)
                group = re.sub(r"_(?:[1-6]|TREECKO|TORCHIC|MUDKIP)$", "", group)
                trainer_groups.setdefault(group, []).append(trainer_id)

            location_key = self._location_key(map_name)
            referenced_flags = set(re.findall(r"\bFLAG_[A-Z0-9_]+", script))
            item_flags = {
                _objective_label(name, location_key): flag_id
                for name, flag_id in self._flag_ids.items()
                if name.startswith(("FLAG_ITEM_", "FLAG_HIDDEN_ITEM_"))
                and location_key in name
            }
            objective_flags = {
                _objective_label(name, location_key): self._flag_ids[name]
                for name in referenced_flags
                if name in self._flag_ids
                and name.startswith(("FLAG_DEFEATED_", "FLAG_RECEIVED_", "FLAG_DELIVERED_", "FLAG_RETURNED_", "FLAG_RECOVERED_", "FLAG_MET_"))
            }
            trackers[map_name] = (
                {name: tuple(ids) for name, ids in trainer_groups.items()},
                item_flags,
                objective_flags,
            )
        return trackers

    @staticmethod
    def _load_rematches(path: Path) -> dict[str, tuple[tuple[int, str], ...]]:
        rematches: dict[str, list[tuple[int, str]]] = {}
        pattern = re.compile(
            r"^\s*\[REMATCH_([A-Z0-9_]+)\]\s*=\s*REMATCH\([^\n]+,\s*MAP_([A-Z0-9_]+)\),",
            re.MULTILINE,
        )
        for index, match in enumerate(pattern.finditer(path.read_text(encoding="utf-8"))):
            trainer, map_name = match.groups()
            rematches.setdefault(_normalize_map_name(map_name), []).append(
                (index, _display_constant(trainer, ""))
            )
        return {name: tuple(entries) for name, entries in rematches.items()}

    @staticmethod
    def _build_map_ids(
        document: dict[str, Any], encounter_names: dict[str, Any]
    ) -> dict[str, tuple[int, int]]:
        normalized: dict[str, tuple[int, int]] = {}
        for group_number, group_name in enumerate(document["group_order"]):
            for map_number, map_name in enumerate(document[group_name]):
                normalized[_normalize_map_name(map_name)] = (group_number, map_number)
        return {
            map_name: normalized[_normalize_map_name(map_name)]
            for map_name in encounter_names
            if _normalize_map_name(map_name) in normalized
        }

    def supports(
        self, status: RetroArchStatus, content_hash: str | None = None
    ) -> bool:
        core = status.core.casefold()
        if core not in {"mgba", "game_boy_advance"}:
            return False
        if content_hash is not None:
            return content_hash.casefold() in self.ra_hashes
        if status.content_crc32:
            return False
        return "emerald" in status.content.casefold()

    def snapshot(self, memory: MemoryReader) -> OverlaySnapshot:
        pointer = int.from_bytes(memory.read_memory(SAVE_BLOCK_1_POINTER, 4), "little")
        if pointer == 0:
            return OverlaySnapshot(
                self.name,
                "Waiting for game/save",
                (PanelSection("Status", (PanelRow("Load or continue a save"),)),),
            )
        if not EWRAM_START <= pointer < EWRAM_END:
            raise RetroArchError(f"Invalid Emerald save block pointer: 0x{pointer:08X}")

        map_group, map_number = memory.read_memory(pointer + 4, 2)
        caught_flags = self._read_caught_flags(memory)
        map_name = self._map_constants_by_id.get((map_group, map_number), "")
        location = self._map_names_by_id.get(
            (map_group, map_number), f"Map {map_group}:{map_number}"
        )
        battle = self._battle_snapshot(memory, pointer, caught_flags, map_name, location)
        if battle is not None:
            return battle

        event_flags = memory.read_memory(pointer + FLAGS_OFFSET, FLAGS_SIZE)
        rematches = memory.read_memory(pointer + REMATCHES_OFFSET, REMATCHES_SIZE)
        encounter = self._encounters_by_id.get((map_group, map_number))
        if encounter is None:
            sections = []
            missable = self._missable_section(map_name, event_flags)
            if missable is not None:
                sections.append(missable)
            sections.append(self._poc_section(caught_flags, event_flags))
            ra_nearby = self._ra_nearby_section(map_name, event_flags)
            if ra_nearby is not None:
                sections.append(ra_nearby)
            sections.extend(
                self._completion_sections(memory, pointer, map_name, event_flags, rematches)
            )
            sections.append(self._collection_section(memory, pointer, event_flags))
            return OverlaySnapshot(self.name, location, tuple(sections))

        sections = []
        missable = self._missable_section(map_name, event_flags)
        if missable is not None:
            sections.append(missable)
        sections.append(self._poc_section(caught_flags, event_flags))
        roamer_alert = self._roamer_section(memory, pointer, map_group, map_number)
        if roamer_alert is not None:
            sections.append(roamer_alert)
        feebas_alert = self._feebas_section(memory, pointer, map_name)
        if feebas_alert is not None:
            sections.append(feebas_alert)
        ra_nearby = self._ra_nearby_section(map_name, event_flags)
        if ra_nearby is not None:
            sections.append(ra_nearby)
        sections.extend(
            self._completion_sections(memory, pointer, map_name, event_flags, rematches)
        )
        for field_name, title in (
            ("land_mons", "Land"),
            ("water_mons", "Water"),
            ("rock_smash_mons", "Rock Smash"),
        ):
            if field_name in encounter:
                sections.append(self._section(title, field_name, encounter[field_name], caught_flags))

        fishing = encounter.get("fishing_mons")
        if fishing:
            definition = self._field_definitions["fishing_mons"]
            for rod_name, indexes in definition["groups"].items():
                sections.append(
                    self._section(
                        _display_constant(rod_name.upper(), ""),
                        "fishing_mons",
                        fishing,
                        caught_flags,
                        indexes,
                    )
                )

        location = _display_constant(encounter["map"], "MAP_")
        return OverlaySnapshot(self.name, location, tuple(sections))

    def _missable_section(
        self, map_name: str, event_flags: bytes
    ) -> PanelSection | None:
        gym = GYM_MISSABLES.get(map_name)
        if gym is not None:
            _, title, badge_index, leader = gym
            if not self._flag_is_set(event_flags, BADGE_FLAG_START + badge_index):
                tracker = self._route_trackers.get(map_name)
                trainer_groups = tracker[0] if tracker is not None else {}
                missing = [
                    name
                    for name, trainer_ids in trainer_groups.items()
                    if leader.upper().replace(" & ", "_AND_") not in name
                    and not any(
                        self._flag_is_set(event_flags, 0x500 + trainer_id)
                        for trainer_id in trainer_ids
                    )
                ]
                detail = (
                    f"Defeat {len(missing)} remaining trainer(s) before {leader}"
                    if missing
                    else f"Confirm every trainer is defeated before {leader}"
                )
                return PanelSection(
                    f"MISSABLE · {title}",
                    (PanelRow(detail),),
                    alert=True,
                )

        trick_house = TRICK_HOUSE_MISSABLES.get(map_name)
        if trick_house is not None:
            _, title = trick_house
            tracker = self._route_trackers.get(map_name)
            if tracker is not None:
                trainer_groups, item_flags, _ = tracker
                trainers_left = sum(
                    not any(
                        self._flag_is_set(event_flags, 0x500 + trainer_id)
                        for trainer_id in trainer_ids
                    )
                    for trainer_ids in trainer_groups.values()
                )
                items_left = sum(
                    not self._flag_is_set(event_flags, flag_id)
                    for flag_id in item_flags.values()
                )
                if trainers_left or items_left:
                    return PanelSection(
                        f"MISSABLE · {title}",
                        (
                            PanelRow(
                                f"Before finishing: {trainers_left} trainer(s), "
                                f"{items_left} item(s) remain"
                            ),
                        ),
                        alert=True,
                    )
        return None

    def _ra_nearby_section(
        self, map_name: str, event_flags: bytes
    ) -> PanelSection | None:
        pending = []
        tracker = self._route_trackers.get(map_name)
        trainer_groups = tracker[0] if tracker is not None else {}
        for achievement in self._nearby_achievements.get(map_name, ()):
            if achievement.event_flag is not None:
                flag_id = self._flag_ids.get(achievement.event_flag)
                complete = flag_id is not None and self._flag_is_set(event_flags, flag_id)
            else:
                trainer_ids = trainer_groups.get(achievement.trainer_prefix or "", ())
                complete = any(
                    self._flag_is_set(event_flags, 0x500 + trainer_id)
                    for trainer_id in trainer_ids
                )
            if not complete:
                pending.append(PanelRow(achievement.title))
        if not pending:
            return None
        return PanelSection("RA nearby", tuple(pending[:3]))

    def _roamer_section(
        self,
        memory: MemoryReader,
        save_block_1: int,
        map_group: int,
        map_number: int,
    ) -> PanelSection | None:
        roamer = memory.read_memory(save_block_1 + ROAMER_OFFSET, ROAMER_SIZE)
        if not roamer[0x13]:
            return None
        if memory.read_memory(ROAMER_LOCATION_ADDRESS, 2) != bytes((map_group, map_number)):
            return None
        species_id = int.from_bytes(roamer[0x08:0x0A], "little")
        species = self._species_by_id.get(species_id, f"Species {species_id}")
        return PanelSection(
            "RA · Flying Through the Eons",
            (
                PanelRow(
                    f"{_display_constant(species, 'SPECIES_')} IS ON THIS ROUTE · "
                    f"Lv {roamer[0x0C]} · HP {int.from_bytes(roamer[0x0A:0x0C], 'little')}"
                ),
            ),
        )

    def _collection_section(
        self, memory: MemoryReader, save_block_1: int, event_flags: bytes
    ) -> PanelSection:
        items = memory.read_memory(save_block_1 + ITEM_POCKET_OFFSET, ITEM_POCKET_SIZE)
        item_ids = {
            int.from_bytes(items[offset : offset + 2], "little")
            for offset in range(0, len(items), 4)
        }
        berries = memory.read_memory(save_block_1 + BERRY_POCKET_OFFSET, BERRY_POCKET_SIZE)
        berry_count = sum(
            bool(int.from_bytes(berries[offset : offset + 2], "little"))
            for offset in range(0, len(berries), 4)
        )
        decorations = memory.read_memory(
            save_block_1 + DECORATION_INVENTORY_OFFSET, DECORATION_INVENTORY_SIZE
        )
        furniture_count = sum(bool(value) for value in decorations[:30])
        doll_count = sum(bool(value) for value in decorations[100:140])
        placed = memory.read_memory(
            save_block_1 + SECRET_BASE_DECORATIONS_OFFSET,
            SECRET_BASE_DECORATIONS_SIZE,
        )
        hm_count = sum(self._flag_is_set(event_flags, flag) for flag in HM_FLAGS)
        flute_count = len(item_ids & FLUTE_ITEM_IDS)
        return PanelSection(
            "Collections",
            (
                PanelRow(f"HMs {hm_count}/8 · Flutes {flute_count}/5 · Berries {berry_count}/46"),
                PanelRow(
                    f"Furniture {furniture_count}/30 · Dolls {doll_count}/40 · "
                    f"Base placed {sum(bool(value) for value in placed)}/16"
                ),
            ),
        )

    def _battle_snapshot(
        self,
        memory: MemoryReader,
        save_block_1: int,
        caught_flags: bytes,
        map_name: str,
        location: str,
    ) -> OverlaySnapshot | None:
        if not memory.read_memory(MAIN_IN_BATTLE_ADDRESS, 1)[0] & MAIN_IN_BATTLE_MASK:
            return None
        battlers_count = int.from_bytes(
            memory.read_memory(BATTLERS_COUNT_ADDRESS, 2), "little"
        )
        if battlers_count not in {2, 4}:
            return None
        battle_mons = memory.read_memory(
            BATTLE_MONS_ADDRESS, BATTLE_MON_SIZE * battlers_count
        )
        opponents = []
        for battler in ((1, 3) if battlers_count == 4 else (1,)):
            offset = BATTLE_MON_SIZE * battler
            opponent = battle_mons[offset : offset + BATTLE_MON_SIZE]
            species_id = int.from_bytes(opponent[0:2], "little")
            level = opponent[0x2A]
            hp = int.from_bytes(opponent[0x28:0x2A], "little")
            max_hp = int.from_bytes(opponent[0x2C:0x2E], "little")
            species = self._species_by_id.get(species_id)
            if species is None or not 1 <= level <= 100 or not 0 <= hp <= max_hp or not max_hp:
                continue
            status = int.from_bytes(opponent[0x4C:0x50], "little")
            types = (opponent[0x21], opponent[0x22])
            opponents.append((species, level, hp, max_hp, status, types))
        if not opponents:
            return None

        sections = [
            PanelSection(
                "Battle",
                tuple(
                    PanelRow(
                        f"{_display_constant(species, 'SPECIES_')}  Lv {level}  "
                        f"HP {hp}/{max_hp}  "
                        f"{'/'.join(dict.fromkeys(TYPE_NAMES[value] for value in types if value < len(TYPE_NAMES)))}"
                        f"{self._status_text(status) if hp else ' · FNT'}"
                    )
                    for species, level, hp, max_hp, status, types in opponents
                ),
            )
        ]

        battle_flags = int.from_bytes(
            memory.read_memory(BATTLE_TYPE_FLAGS_ADDRESS, 4), "little"
        )
        if not battle_flags & (1 << 3):
            turns = memory.read_memory(BATTLE_RESULTS_TURN_ADDRESS, 1)[0]
            quantities = self._ball_quantities(memory, save_block_1)
            for species, level, hp, max_hp, status, types in opponents:
                catch_rate = self._catch_rates.get(species)
                chances = []
                if catch_rate is not None and hp:
                    for ball in BALLS:
                        quantity = quantities.get(ball.item_id, 0)
                        if not quantity:
                            continue
                        multiplier = ball_multiplier(
                            ball.item_id,
                            level=level,
                            types=types,
                            caught=self._is_caught(species, caught_flags),
                            underwater=map_name.startswith("Underwater_"),
                            turns=turns,
                        )
                        probability = catch_probability(
                            catch_rate,
                            hp,
                            max_hp,
                            status,
                            multiplier,
                            master_ball=ball.item_id == 1,
                        )
                        chances.append(
                            (probability, PanelRow(f"{ball.name} x{quantity}  {probability:.1%}"))
                        )
                if chances:
                    title = "Catch chances"
                    if len(opponents) > 1:
                        title += f" · {_display_constant(species, 'SPECIES_')}"
                    sections.append(
                        PanelSection(
                            title,
                            tuple(
                                row
                                for _, row in sorted(
                                    chances, reverse=True, key=lambda entry: entry[0]
                                )
                            ),
                        )
                    )
        return OverlaySnapshot(self.name, f"Battle · {location}", tuple(sections))

    def _ball_quantities(self, memory: MemoryReader, save_block_1: int) -> dict[int, int]:
        save_block_2 = int.from_bytes(memory.read_memory(SAVE_BLOCK_2_POINTER, 4), "little")
        key = int.from_bytes(
            memory.read_memory(save_block_2 + SECURITY_KEY_OFFSET, 2), "little"
        )
        pocket = memory.read_memory(save_block_1 + BALL_POCKET_OFFSET, BALL_POCKET_SIZE)
        quantities = {}
        for offset in range(0, len(pocket), 4):
            item_id = int.from_bytes(pocket[offset : offset + 2], "little")
            encrypted = int.from_bytes(pocket[offset + 2 : offset + 4], "little")
            if item_id:
                quantities[item_id] = encrypted ^ key
        return quantities

    @staticmethod
    def _status_text(status: int) -> str:
        for mask, label in (
            (0x7, "SLP"),
            (0x8, "PSN"),
            (0x10, "BRN"),
            (0x20, "FRZ"),
            (0x40, "PAR"),
            (0x80, "TOX"),
        ):
            if status & mask:
                return f" · {label}"
        return ""

    def _feebas_section(
        self, memory: MemoryReader, save_block_1: int, map_name: str
    ) -> PanelSection | None:
        if map_name != "Route119":
            return None
        seed = int.from_bytes(
            memory.read_memory(save_block_1 + DEWFORD_TREND_SEED_OFFSET, 2), "little"
        )
        position = memory.read_memory(PLAYER_POSITION_ADDRESS, 9)
        x = int.from_bytes(position[0:2], "little", signed=True)
        y = int.from_bytes(position[2:4], "little", signed=True)
        target = tile_in_front(x, y, position[8])
        spot_id = self._route119_fishing_spots.get(target)
        if spot_id not in feebas_spot_ids(seed):
            return None
        return PanelSection(
            "RA · One Tile Away from Beauty",
            (PanelRow(f"VALID TILE · spot {spot_id} · 50% Feebas"),),
        )

    @staticmethod
    def _poc_section(caught_flags: bytes, event_flags: bytes) -> PanelSection:
        caught_count = sum(byte.bit_count() for byte in caught_flags)
        next_gate = next(
            (
                (leader, target)
                for badge, leader, target in POC_GATES
                if not EmeraldAdapter._flag_is_set(event_flags, BADGE_FLAG_START + badge)
            ),
            None,
        )
        if next_gate is None:
            text = f"Final goal  {caught_count}/212"
        else:
            leader, target = next_gate
            ready = "READY" if caught_count >= target else f"need {target - caught_count}"
            text = f"Next: {leader}  {caught_count}/{target}  {ready}"
        return PanelSection("Professor Oak Challenge", (PanelRow(text),))

    @staticmethod
    def _flag_is_set(flags: bytes, flag_id: int) -> bool:
        return bool(flags[flag_id // 8] & (1 << (flag_id % 8)))

    def _completion_sections(
        self,
        memory: MemoryReader,
        save_block_1: int,
        map_name: str,
        flags: bytes,
        rematches: bytes,
    ) -> tuple[PanelSection, ...]:
        tracker = self._route_trackers.get(map_name)
        if tracker is None:
            return ()
        trainer_groups, item_flags, objective_flags = tracker
        sections = []
        if trainer_groups:
            missing = [
                _display_constant(name, "TRAINER_")
                for name, ids in trainer_groups.items()
                if not any(self._flag_is_set(flags, 0x500 + trainer_id) for trainer_id in ids)
            ]
            sections.append(self._checklist_section("Route trainers", len(trainer_groups), missing))
        map_item_locations = self._item_locations.get(map_name, ())
        if map_item_locations:
            player_x, player_y = self._player_position(memory, save_block_1)
            missing = []
            for item_name, item_x, item_y, flag_id, hidden in map_item_locations:
                if self._flag_is_set(flags, flag_id):
                    continue
                kind = "hidden" if hidden else "item"
                missing.append(
                    f"{item_name} · ({item_x},{item_y}) · {kind}"
                )
            sections.append(
                self._checklist_section(
                    f"Route items · You ({player_x},{player_y})",
                    len(map_item_locations),
                    missing,
                )
            )
        elif item_flags:
            missing = [
                name
                for name, flag_id in item_flags.items()
                if not self._flag_is_set(flags, flag_id)
            ]
            sections.append(self._checklist_section("Route items", len(item_flags), missing))
        missing_objectives = [
            name for name, flag_id in objective_flags.items() if not self._flag_is_set(flags, flag_id)
        ]
        if missing_objectives:
            sections.append(
                PanelSection(
                    "Nearby objectives",
                    tuple(PanelRow(name) for name in missing_objectives),
                    3,
                )
            )
        ready_rematches = [
            name
            for index, name in self._rematches_by_map.get(_normalize_map_name(map_name), ())
            if index < len(rematches) and rematches[index]
        ]
        if ready_rematches:
            sections.append(
                PanelSection(
                    "Rematches ready",
                    tuple(PanelRow(name) for name in ready_rematches),
                    3,
                )
            )
        return tuple(sections)

    @staticmethod
    def _player_position(memory: MemoryReader, save_block_1: int) -> tuple[int, int]:
        position = memory.read_memory(save_block_1, 4)
        return (
            int.from_bytes(position[:2], "little", signed=True),
            int.from_bytes(position[2:4], "little", signed=True),
        )

    @staticmethod
    def _checklist_section(title: str, total: int, missing: list[str]) -> PanelSection:
        rows = [PanelRow(f"{total - len(missing)}/{total} complete")]
        rows.extend(PanelRow(name, False) for name in missing)
        return PanelSection(title, tuple(rows), 4)

    def _read_caught_flags(self, memory: MemoryReader) -> bytes:
        pointer = int.from_bytes(memory.read_memory(SAVE_BLOCK_2_POINTER, 4), "little")
        if not EWRAM_START <= pointer < EWRAM_END:
            raise RetroArchError(f"Invalid Emerald save block 2 pointer: 0x{pointer:08X}")
        return memory.read_memory(pointer + POKEDEX_OWNED_OFFSET, DEX_FLAG_BYTES)

    def _section(
        self,
        title: str,
        field_name: str,
        encounter: dict[str, Any],
        caught_flags: bytes,
        indexes: list[int] | None = None,
    ) -> PanelSection:
        definition = self._field_definitions[field_name]
        rates = definition["encounter_rates"]
        selected_indexes = indexes if indexes is not None else list(range(len(encounter["mons"])))
        species: OrderedDict[str, dict[str, int]] = OrderedDict()
        for index in selected_indexes:
            mon = encounter["mons"][index]
            entry = species.setdefault(
                mon["species"],
                {"min": mon["min_level"], "max": mon["max_level"], "chance": 0},
            )
            entry["min"] = min(entry["min"], mon["min_level"])
            entry["max"] = max(entry["max"], mon["max_level"])
            entry["chance"] += rates[index]

        rows = tuple(
            PanelRow(
                f"{_display_constant(name, 'SPECIES_')}  Lv {values['min']}-{values['max']}  {values['chance']}%",
                self._is_caught(name, caught_flags),
            )
            for name, values in species.items()
        )
        encounter_rate = encounter.get("encounter_rate")
        heading = f"{title} · rate {encounter_rate}" if encounter_rate is not None else title
        return PanelSection(heading, rows)

    def _is_caught(self, species: str, caught_flags: bytes) -> bool:
        national_number = self._national_dex_numbers[species]
        bit_index = national_number - 1
        return bool(caught_flags[bit_index // 8] & (1 << (bit_index % 8)))
