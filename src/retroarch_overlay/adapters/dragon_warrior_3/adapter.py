from collections import Counter, deque
from dataclasses import dataclass

from ...core.contracts import MemoryReader
from ...core.retroachievements import RAProgress
from ...models import MapPosition, OverlaySnapshot, PanelAction, PanelRow, PanelSection, RetroArchStatus
from .achievements import ACHIEVEMENTS, ACHIEVEMENTS_BY_ID
from .manifest import RA_GAME_ID, RA_HASHES


RAM_SIZE = 0x0800
SRAM_ADDRESS = 0x6000
SRAM_READ_SIZE = 0x0ACC

JOBS = ("Hero", "Wizard", "Pilgrim", "Sage", "Soldier", "Merchant", "Fighter", "Goof-off")
TOWNS = (
    "Aliahan", "Reeve", "Romaly", "Kanave", "Noaniels", "Assaram", "Isis", "Portoga",
    "Baharata", "Dhama", "Lancel", "Jipang", "Eginbear", "Samanao", "Soo", "Tantegel",
    "Hauksness", "Cantlin", "Kol", "Rimuldar",
)
ITEM_NAMES = {
    0x08: "Poison Needle",
    0x16: "Sword of Illusion",
    0x1B: "Staff of Thunder",
    0x1C: "Sword of Kings",
    0x3B: "Shield of Heroes",
    0x47: "Sacred Amulet",
    0x4C: "Book of Satori",
    0x4E: "Wizard's Ring",
    0x4F: "Black Pepper",
    0x52: "Vase of Drought",
    0x53: "Lamp of Darkness",
    0x54: "Staff of Change",
    0x58: "Thief's Key",
    0x59: "Magic Key",
    0x5A: "Final Key",
    0x69: "Leaf of the World Tree",
    0x6D: "Water Blaster",
    0x6F: "Echoing Flute",
    0x71: "Silver Harp",
    0x72: "Sphere of Light",
    0x76: "Rainbow Drop",
    0x77: "Silver Orb",
    0x78: "Red Orb",
    0x79: "Yellow Orb",
    0x7A: "Purple Orb",
    0x7B: "Blue Orb",
    0x7C: "Green Orb",
}
ITEM_ACHIEVEMENTS = {
    0x08: 50421,
    0x16: 50436,
    0x1B: 50427,
    0x1C: 50433,
    0x3B: 50430,
    0x47: 50457,
    0x4C: 50464,
    0x4E: 50463,
    0x4F: 50445,
    0x52: 50423,
    0x53: 50422,
    0x54: 50451,
    0x58: 50439,
    0x59: 50443,
    0x5A: 50446,
    0x69: 50431,
    0x6D: 50429,
    0x6F: 50425,
    0x71: 50426,
    0x77: 50454,
    0x78: 50450,
    0x79: 50452,
    0x7A: 50448,
    0x7B: 50449,
    0x7C: 50447,
}
EXACT_DETECTOR_COUNT = len(ITEM_ACHIEVEMENTS) + 7
ORB_ITEMS = (0x77, 0x78, 0x79, 0x7A, 0x7B, 0x7C)
KEY_ITEMS = (0x58, 0x59, 0x5A, 0x4F, 0x52, 0x53, 0x54, 0x6D, 0x6F, 0x71, 0x72, 0x76)
KEY_ITEM_UNLOCKS = {
    0x58: ("Thief's Key doors", "Early Aliahan and Reeve checks"),
    0x59: ("Magic Key doors", "Pyramid, Portoga, and midgame locked rooms"),
    0x5A: ("Final Key doors", "Jails, late-game shrines, and final key checks"),
    0x4F: ("Portoga ship trade", "Turn in Black Pepper to unlock world sailing"),
    0x52: ("Shoals access", "Use the Vase of Drought for the Final Key route"),
    0x53: ("Night control", "Force night checks without resting"),
    0x54: ("Samanao route", "Expose the false king and continue the orb chain"),
    0x6D: ("New Town chain", "Merchantville progression and Yellow Orb route"),
    0x6F: ("Orb search aid", "Echoing Flute helps identify orb locations"),
    0x71: ("Encounter control", "Silver Harp forces fights when grinding"),
    0x72: ("Zoma safety", "Sphere of Light weakens Zoma"),
    0x76: ("Final dungeon access", "Rainbow bridge to Zoma's Castle"),
}
ORB_HINTS = {
    0x77: "Necrogond shrine reward",
    0x78: "Pirates / hidden route",
    0x79: "Merchantville rebellion",
    0x7A: "Orochi / Jipang chain",
    0x7B: "Lancel / Gaia's Navel route",
    0x7C: "Tedanki / prisoner route",
}
ROUTE_PLAN = (
    ("Recruit a full party", "Build four active characters before leaving Aliahan."),
    ("Thief's Key", "Go to Reeve and unlock early locked-door checks."),
    ("Magic Key", "Push toward Isis and Pyramid."),
    ("Black Pepper", "Resolve Baharata and return to Portoga for the ship."),
    ("Final Key", "Use the ship and Vase of Drought route."),
    ("Orb hunt", "Collect all six orbs and place them in Liamland."),
    ("Ramia", "Finish Liamland after all orbs are placed."),
    ("Baramos", "Use Ramia to reach Baramos Castle."),
    ("Alefgard", "After Baramos, push the underworld route."),
    ("Rainbow Drop", "Build the bridge to Zoma's Castle."),
    ("Zoma", "Finish the final route."),
)
SHOPPING_GOALS = (
    (0, "Save for early key and gear checks."),
    (1000, "Comfortable early-game buffer."),
    (5000, "Good midgame equipment fund."),
    (15000, "Late-game purchases and recovery buffer."),
)
TIME_WINDOWS = (
    "Sunrise/Morning: travel visibility and normal town access",
    "Afternoon/Evening: continue overworld routing before night checks",
    "Dusk/Night: use for night-only NPC and town state checks",
    "Lamp of Darkness: force night when a route expects it",
)


@dataclass(frozen=True, slots=True)
class GameState:
    levels: tuple[int, ...]
    jobs: tuple[int, ...]
    party_ids: tuple[int, ...]
    items: tuple[int, ...]
    pyramid_chests: int
    samanao_chests: int
    orbs_found: int
    orbs_placed: int
    pedestals: int
    arena_active: bool
    arena_winner: int
    arena_pick: int


class DragonWarrior3Adapter:
    name = "Dragon Warrior III"
    ra_game_id = RA_GAME_ID
    ra_hashes = RA_HASHES

    def __init__(self, account_progress: RAProgress | None = None) -> None:
        self._previous: GameState | None = None
        self._unlocked: set[int] = set()
        self._recent_items: deque[int] = deque(maxlen=8)
        self._account_progress = account_progress

    def supports(self, status: RetroArchStatus, content_hash: str | None = None) -> bool:
        core = status.core.casefold().replace(" ", "_")
        if not any(name in core for name in ("mesen", "nestopia", "fceumm", "fceux", "nes")):
            return False
        if content_hash is not None:
            return content_hash.casefold() in self.ra_hashes
        if status.content_crc32:
            return False
        content = status.content.casefold()
        return "dragon warrior iii" in content or "dragon quest iii" in content

    def snapshot(self, memory: MemoryReader) -> OverlaySnapshot:
        ram = memory.read_memory(0, RAM_SIZE)
        sram = memory.read_memory(SRAM_ADDRESS, SRAM_READ_SIZE)
        state = self._state(ram, sram)
        self._observe(state)

        map_id = int.from_bytes(ram[0x008A:0x008C], "little")
        map_bank = ram[0x002F]
        if map_bank in {0, 2}:
            coordinates = (ram[0x002A], ram[0x002B])
            area = "World" if map_bank == 0 else "Underworld"
        else:
            coordinates = (ram[0x0030], ram[0x0031])
            area = "Dungeon / town"
        location = f"{area} · Map {map_id:04X} · ({coordinates[0]},{coordinates[1]})"

        battle = ram[0x0032] == 0xFD
        if battle:
            sections = [
                self._battle_section(ram),
                self._party_section(ram, state),
                self._achievement_section(),
            ]
        else:
            sections = [
                self._objective_section(ram, state, area),
                self._party_section(ram, state),
                self._achievement_section(),
            ]
        sections.extend(
            (
                self._unlock_section(state),
                self._orb_section(state),
                self._resource_section(ram, state),
                self._progress_section(sram, state),
                self._world_section(ram),
            )
        )
        if self._recent_items:
            sections.append(
                PanelSection(
                    "New items observed",
                    tuple(
                        PanelRow(ITEM_NAMES.get(item_id, f"Item ID 0x{item_id:02X}"))
                        for item_id in self._recent_items
                    ),
                    actions=(
                        PanelAction(
                            "OPEN RECENT ITEMS",
                            "Recent Items Observed",
                            tuple(
                                PanelRow(self._item_detail(item_id), item_id in ITEM_ACHIEVEMENTS)
                                for item_id in self._recent_items
                            ),
                        ),
                    ),
                )
            )
        return OverlaySnapshot(
            self.name,
            f"Battle · {location}" if battle else location,
            tuple(sections),
            MapPosition(area, map_id, *coordinates, map_bank in {0, 2}),
        )

    def _objective_section(self, ram: bytes, state: GameState, area: str) -> PanelSection:
        objective, detail = self._current_objective(state, area)
        rows = [PanelRow(objective), PanelRow(detail)]
        warnings = self._party_warnings(ram, state)
        if warnings:
            rows.append(PanelRow("Risk: " + " · ".join(warnings), False))
        return PanelSection(
            "Current objective",
            tuple(rows),
            alert=bool(warnings),
            actions=(
                PanelAction("OPEN ROUTE PLAN", "Dragon Warrior III Route Plan", self._route_plan_rows(state, area)),
                PanelAction("OPEN KEY ITEM UNLOCKS", "Key Item Unlocks", self._key_item_rows(state)),
                PanelAction("OPEN RA PRIORITIES", "RetroAchievements Priorities", self._ra_priority_rows(state)),
            ),
        )

    def _current_objective(self, state: GameState, area: str) -> tuple[str, str]:
        if sum(level > 0 for level in state.levels) < 4:
            return "Next: recruit a full party", "Build four active party members before committing to the overworld."
        if not self._has_item(state, 0x58):
            return "Next: Reeve · Thief's Key", "Unlock the first door tier and early item checks."
        if not self._has_item(state, 0x59):
            return "Next: Isis / Pyramid · Magic Key", "Push the desert route and open the midgame door tier."
        if not self._has_item(state, 0x4F):
            return "Next: Baharata · Black Pepper", "Finish the trade chain that leads to the ship."
        if not self._has_item(state, 0x5A):
            return "Next: Final Key route", "Use ship access and the Vase of Drought chain to open jail doors."
        if state.orbs_found < 6:
            return f"Next: orb hunt · {state.orbs_found}/6 found", "Use key-item access to clean up the six orb routes."
        if state.orbs_placed < 6 or state.pedestals < 6:
            return "Next: Liamland · place the orbs", "Place every orb and light the pedestals to hatch Ramia."
        if area != "Underworld" and not self._has_item(state, 0x76):
            return "Next: Baramos / Alefgard route", "Use Ramia access to move into the endgame chain."
        if not self._has_item(state, 0x76):
            return "Next: Rainbow Drop", "Gather Alefgard requirements and build the bridge to Zoma's Castle."
        if not self._has_item(state, 0x72):
            return "Next: Sphere of Light", "Collect it unless you are routing the no-Sphere challenge."
        return "Next: Zoma", "Final route is open; prepare resources and finish the game."

    def _route_plan_rows(self, state: GameState, area: str) -> tuple[PanelRow, ...]:
        checks = {
            "Recruit a full party": sum(level > 0 for level in state.levels) >= 4,
            "Thief's Key": self._has_item(state, 0x58),
            "Magic Key": self._has_item(state, 0x59),
            "Black Pepper": self._has_item(state, 0x4F),
            "Final Key": self._has_item(state, 0x5A),
            "Orb hunt": state.orbs_found >= 6,
            "Ramia": state.orbs_placed >= 6 and state.pedestals >= 6,
            "Baramos": area == "Underworld" or self._has_item(state, 0x76),
            "Alefgard": area == "Underworld" or self._has_item(state, 0x76),
            "Rainbow Drop": self._has_item(state, 0x76),
            "Zoma": self._has_item(state, 0x72) and self._has_item(state, 0x76),
        }
        return tuple(
            PanelRow(f"{name}: {detail}", checks.get(name, False))
            for name, detail in ROUTE_PLAN
        )

    def _key_item_rows(self, state: GameState) -> tuple[PanelRow, ...]:
        rows = []
        for item_id in KEY_ITEMS:
            name = ITEM_NAMES[item_id]
            unlock, detail = KEY_ITEM_UNLOCKS[item_id]
            owned = self._has_item(state, item_id)
            rows.append(PanelRow(f"{name}: {unlock} · {detail}", owned))
        missing_orbs = [ITEM_NAMES[item_id] for item_id in ORB_ITEMS if not self._has_item(state, item_id)]
        rows.append(PanelRow("Missing orbs: " + (", ".join(missing_orbs) if missing_orbs else "none")))
        return tuple(rows)

    def _ra_priority_rows(self, state: GameState) -> tuple[PanelRow, ...]:
        unlocked = self._unlocked | (
            self._account_progress.unlocked_ids if self._account_progress is not None else frozenset()
        )
        rows = []
        for item_id, achievement_id in ITEM_ACHIEVEMENTS.items():
            achievement = ACHIEVEMENTS_BY_ID[achievement_id]
            if achievement_id in unlocked:
                rows.append(PanelRow(f"{achievement.title}: done", True))
            elif self._has_item(state, item_id):
                rows.append(PanelRow(f"{achievement.title}: item held, not observed this session", False))
            else:
                rows.append(PanelRow(f"{achievement.title}: {achievement.description}", False))
        for achievement in ACHIEVEMENTS:
            if achievement.id not in ITEM_ACHIEVEMENTS.values() and achievement.id not in unlocked:
                rows.append(PanelRow(f"{achievement.title}: {achievement.description}", False))
        return tuple(rows)

    @staticmethod
    def _has_item(state: GameState, item_id: int) -> bool:
        return item_id in state.items

    def _item_detail(self, item_id: int) -> str:
        name = ITEM_NAMES.get(item_id, f"Item ID 0x{item_id:02X}")
        achievement_id = ITEM_ACHIEVEMENTS.get(item_id)
        if achievement_id is not None:
            achievement = ACHIEVEMENTS_BY_ID[achievement_id]
            return f"{name}: {achievement.title} · {achievement.description}"
        unlock = KEY_ITEM_UNLOCKS.get(item_id)
        if unlock is not None:
            return f"{name}: {unlock[0]} · {unlock[1]}"
        return name

    def _party_warnings(self, ram: bytes, state: GameState) -> tuple[str, ...]:
        warnings = []
        active = 0
        low_hp = 0
        bad_status = 0
        no_mp = 0
        for index, level in enumerate(state.levels):
            if not level:
                continue
            active += 1
            hp = int.from_bytes(ram[0x071C + index * 2:0x071E + index * 2], "little")
            max_hp = int.from_bytes(ram[0x0724 + index * 2:0x0726 + index * 2], "little")
            mp = int.from_bytes(ram[0x072C + index * 2:0x072E + index * 2], "little")
            status = ram[0x073D + index * 2]
            if max_hp and hp * 4 <= max_hp:
                low_hp += 1
            if status & 0x60 or not hp:
                bad_status += 1
            if state.jobs[index] in {1, 2, 3} and not mp:
                no_mp += 1
        if active < 4:
            warnings.append(f"{4 - active} party slot(s) open")
        if low_hp:
            warnings.append(f"{low_hp} low HP")
        if bad_status:
            warnings.append(f"{bad_status} status/down")
        if no_mp:
            warnings.append(f"{no_mp} caster(s) dry")
        return tuple(warnings)

    def _unlock_section(self, state: GameState) -> PanelSection:
        owned = [ITEM_NAMES[item_id] for item_id in KEY_ITEMS if self._has_item(state, item_id)]
        next_missing = next((item_id for item_id in KEY_ITEMS if not self._has_item(state, item_id)), None)
        rows = [PanelRow(f"Key items {len(owned)}/{len(KEY_ITEMS)}")]
        if next_missing is not None:
            unlock, detail = KEY_ITEM_UNLOCKS[next_missing]
            rows.append(PanelRow(f"Next unlock: {ITEM_NAMES[next_missing]} · {unlock}"))
            rows.append(PanelRow(detail))
        else:
            rows.append(PanelRow("All tracked key-item unlocks are covered", True))
        return PanelSection(
            "Unlocks",
            tuple(rows),
            actions=(
                PanelAction("OPEN UNLOCK DETAILS", "Key Item Unlocks", self._key_item_rows(state)),
            ),
        )

    def _orb_section(self, state: GameState) -> PanelSection:
        rows = [PanelRow(f"Found {state.orbs_found}/6 · placed {state.orbs_placed}/6 · lit {state.pedestals}/6")]
        missing = [item_id for item_id in ORB_ITEMS if not self._has_item(state, item_id)]
        if missing:
            rows.append(PanelRow("Missing: " + ", ".join(ITEM_NAMES[item_id] for item_id in missing), False))
        else:
            rows.append(PanelRow("All tracked orb items are in inventory/vault", True))
        detail_rows = tuple(
            PanelRow(f"{ITEM_NAMES[item_id]}: {ORB_HINTS[item_id]}", self._has_item(state, item_id))
            for item_id in ORB_ITEMS
        )
        return PanelSection(
            "Orb route",
            tuple(rows),
            alert=state.orbs_found >= 6 and state.orbs_placed < 6,
            actions=(PanelAction("OPEN ORB CHECKLIST", "Orb Checklist", detail_rows),),
        )

    def _resource_section(self, ram: bytes, state: GameState) -> PanelSection:
        gold = int.from_bytes(ram[0x07BC:0x07BF], "little")
        alive = 0
        total_hp = 0
        total_max_hp = 0
        total_mp = 0
        total_max_mp = 0
        for index, level in enumerate(state.levels):
            if not level:
                continue
            hp = int.from_bytes(ram[0x071C + index * 2:0x071E + index * 2], "little")
            max_hp = int.from_bytes(ram[0x0724 + index * 2:0x0726 + index * 2], "little")
            mp = int.from_bytes(ram[0x072C + index * 2:0x072E + index * 2], "little")
            max_mp = int.from_bytes(ram[0x0734 + index * 2:0x0736 + index * 2], "little")
            alive += bool(hp)
            total_hp += hp
            total_max_hp += max_hp
            total_mp += mp
            total_max_mp += max_mp
        hp_text = f"HP pool {total_hp}/{total_max_hp}" if total_max_hp else "HP pool unknown"
        mp_text = f"MP pool {total_mp}/{total_max_mp}" if total_max_mp else "MP pool unknown"
        next_goal = next((goal for goal, _ in SHOPPING_GOALS if gold < goal), None)
        rows = [PanelRow(f"Alive {alive}/4 · {hp_text}"), PanelRow(mp_text)]
        if next_goal is not None:
            rows.append(PanelRow(f"Gold {gold:,} · need {next_goal - gold:,} for {next_goal:,} buffer"))
        else:
            rows.append(PanelRow(f"Gold {gold:,} · late-game buffer ready", True))
        detail_rows = tuple(PanelRow(f"{goal:,} gold: {detail}", gold >= goal) for goal, detail in SHOPPING_GOALS)
        return PanelSection(
            "Resources",
            tuple(rows),
            alert=bool(self._party_warnings(ram, state)),
            actions=(PanelAction("OPEN RESOURCE PLAN", "Resource Plan", detail_rows),),
        )

    def _achievement_detail_rows(self) -> tuple[PanelRow, ...]:
        unlocked = self._unlocked | (
            self._account_progress.unlocked_ids if self._account_progress is not None else frozenset()
        )
        return tuple(
            PanelRow(f"{achievement.title}: {achievement.description}", achievement.id in unlocked)
            for achievement in ACHIEVEMENTS
        )

    def _class_plan_rows(self, state: GameState) -> tuple[PanelRow, ...]:
        active_jobs = [state.jobs[index] for index, level in enumerate(state.levels) if level]
        rows = [PanelRow("Class mix: " + ", ".join(JOBS[job] for job in active_jobs) if active_jobs else "No active party")]
        if 3 not in active_jobs:
            rows.append(PanelRow("No Sage present · Book of Satori or Goof-off route can unlock one", False))
        if sum(job == 3 for job in active_jobs) >= 2:
            rows.append(PanelRow("Two Sage setup active for So Much Magic", True))
        eligible = [
            f"P{index + 1} {JOBS[state.jobs[index]]} Lv {level}"
            for index, level in enumerate(state.levels)
            if level >= 20 and state.jobs[index] not in {0, 3}
        ]
        rows.append(PanelRow("Dhama candidates: " + (", ".join(eligible) if eligible else "none yet")))
        return tuple(rows)

    def _recovery_rows(self, ram: bytes, state: GameState) -> tuple[PanelRow, ...]:
        warnings = self._party_warnings(ram, state)
        if not warnings:
            return (PanelRow("Recovery state: no immediate HP/status/MP warning", True),)
        return tuple(PanelRow(f"Recovery warning: {warning}", False) for warning in warnings)

    def _completion_rows(self, state: GameState, vault_count: int) -> tuple[PanelRow, ...]:
        return (
            PanelRow(f"Orbs found {state.orbs_found}/6", state.orbs_found >= 6),
            PanelRow(f"Orbs placed {state.orbs_placed}/6", state.orbs_placed >= 6),
            PanelRow(f"Liamland pedestals lit {state.pedestals}/6", state.pedestals >= 6),
            PanelRow(f"Pyramid chests {state.pyramid_chests}/24", state.pyramid_chests >= 24),
            PanelRow(f"Samanao cave chests {state.samanao_chests}/23", state.samanao_chests >= 23),
            PanelRow(f"Vault slots used {vault_count}/128"),
            PanelRow("Rainbow bridge ready" if self._has_item(state, 0x76) else "Rainbow bridge not ready", self._has_item(state, 0x76)),
            PanelRow("Sphere of Light owned" if self._has_item(state, 0x72) else "Sphere of Light missing", self._has_item(state, 0x72)),
        )

    def _chest_rows(self, state: GameState) -> tuple[PanelRow, ...]:
        pyramid_left = 24 - state.pyramid_chests
        samanao_left = 23 - state.samanao_chests
        return (
            PanelRow(f"Pyramid: {pyramid_left} chest(s) left", pyramid_left == 0),
            PanelRow(f"Samanao cave: {samanao_left} chest(s) left", samanao_left == 0),
            PanelRow("Pyramid completion detects Archaeologist when all 24 are opened"),
            PanelRow("Samanao cave completion detects Spelunker when all 23 are opened"),
        )

    def _vault_rows(self, sram: bytes) -> tuple[PanelRow, ...]:
        counts = Counter(value & 0x7F for value in sram[0x0D:0x8D] if value & 0x7F)
        if not counts:
            return (PanelRow("Vault is empty"),)
        return tuple(
            PanelRow(f"{ITEM_NAMES.get(item_id, f'Item ID 0x{item_id:02X}')} ×{count}", item_id in ITEM_ACHIEVEMENTS)
            for item_id, count in sorted(counts.items())
        )

    @staticmethod
    def _return_rows(town_names: list[str]) -> tuple[PanelRow, ...]:
        if not town_names:
            return (PanelRow("No Return destinations recorded"),)
        known = set(town_names)
        return tuple(PanelRow(town, town in known) for town in TOWNS)

    def _travel_aid_rows(self, ram: bytes) -> tuple[PanelRow, ...]:
        repel_steps = ram[0x00AD]
        time = self._time_of_day(ram[0x06DF])
        rows = [
            PanelRow(f"Repel: {repel_steps} steps remaining" if repel_steps else "Repel inactive"),
            PanelRow(f"Time: {time}"),
            PanelRow("Use Return for fast town routing once destinations are registered"),
            PanelRow("Use Echoing Flute during orb cleanup if available"),
            PanelRow("Use Lamp of Darkness for night checks if available"),
        ]
        return tuple(rows)

    def _state(self, ram: bytes, sram: bytes) -> GameState:
        levels = tuple(ram[0x0700:0x0704])
        jobs = tuple(value & 0x07 for value in ram[0x0718:0x071C])
        party_ids = tuple(ram[0x07C1:0x07C5])
        carried_items = tuple(value & 0x7F for value in ram[0x077C:0x079C] if value & 0x7F)
        vault_items = tuple(value & 0x7F for value in sram[0x0D:0x8D] if value & 0x7F)
        return GameState(
            levels,
            jobs,
            party_ids,
            carried_items + vault_items,
            self._bit_count(sram, ((0x92, 0x3F), (0x93, 0xC0), (0x9F, 0x07), (0xA0, 0xFF), (0xA1, 0xF8))),
            self._bit_count(sram, ((0x9B, 0x3F), (0x9C, 0xFF), (0x9D, 0xFF), (0x9E, 0x80))),
            (sram[0xCE] & 0x3F).bit_count(),
            (sram[0xCF] & 0x3F).bit_count(),
            (sram[0xD0] & 0x3F).bit_count(),
            bool(sram[0xA64]),
            sram[0xA65],
            sram[0xA67],
        )

    def _observe(self, state: GameState) -> None:
        previous = self._previous
        if previous is None:
            self._previous = state
            return
        if sum(level > 0 for level in previous.levels) < 4 == sum(level > 0 for level in state.levels):
            self._unlocked.add(50465)
        if any(
            old_job != new_job and old_id == new_id and level
            for old_job, new_job, old_id, new_id, level in zip(
                previous.jobs, state.jobs, previous.party_ids, state.party_ids, state.levels
            )
        ):
            self._unlocked.add(50467)
        if previous.jobs.count(3) < 2 <= state.jobs.count(3):
            self._unlocked.add(50434)
        if previous.pyramid_chests < 24 == state.pyramid_chests:
            self._unlocked.add(50526)
        if previous.samanao_chests < 23 == state.samanao_chests:
            self._unlocked.add(50527)
        if previous.pedestals < 6 == state.pedestals:
            self._unlocked.add(50455)
        if previous.arena_active and not state.arena_active and state.arena_winner == state.arena_pick:
            self._unlocked.add(50466)
        gained = Counter(state.items) - Counter(previous.items)
        for item_id, count in gained.items():
            self._recent_items.extend([item_id] * count)
            achievement_id = ITEM_ACHIEVEMENTS.get(item_id)
            if achievement_id is not None:
                self._unlocked.add(achievement_id)
        self._previous = state

    def _achievement_section(self) -> PanelSection:
        account_ids = (
            self._account_progress.unlocked_ids & ACHIEVEMENTS_BY_ID.keys()
            if self._account_progress is not None
            else frozenset()
        )
        combined_ids = account_ids | self._unlocked
        rows = []
        if self._account_progress is not None and not self._account_progress.message:
            rows.append(
                PanelRow(
                    f"{len(combined_ids)}/50 unlocked · {self._account_progress.username}"
                )
            )
            rows.append(PanelRow(f"{len(self._unlocked)} detected this session"))
        else:
            rows.append(PanelRow(f"{len(self._unlocked)}/50 detected this session"))
            if self._account_progress is not None and self._account_progress.message:
                rows.append(PanelRow(self._account_progress.message))
        rows.extend(
            PanelRow(
                f"{ACHIEVEMENTS_BY_ID[achievement_id].title} · "
                f"{'detected' if achievement_id in self._unlocked else 'account'}",
                True,
            )
            for achievement_id in sorted(combined_ids)
        )
        if not combined_ids:
            rows.append(PanelRow(f"{EXACT_DETECTOR_COUNT} exact detectors active · fresh baseline"))
        return PanelSection(
            "RetroAchievements",
            tuple(rows),
            preview_limit=7,
            actions=(PanelAction("OPEN ACHIEVEMENTS", "RetroAchievements", self._achievement_detail_rows()),),
        )

    def _party_section(self, ram: bytes, state: GameState) -> PanelSection:
        rows = []
        detail_rows = []
        for index, level in enumerate(state.levels):
            if not level:
                continue
            hp = int.from_bytes(ram[0x071C + index * 2:0x071E + index * 2], "little")
            max_hp = int.from_bytes(ram[0x0724 + index * 2:0x0726 + index * 2], "little")
            mp = int.from_bytes(ram[0x072C + index * 2:0x072E + index * 2], "little")
            max_mp = int.from_bytes(ram[0x0734 + index * 2:0x0736 + index * 2], "little")
            status = ram[0x073D + index * 2]
            condition = self._condition(status, hp)
            rows.append(
                PanelRow(
                    f"P{index + 1} · {JOBS[state.jobs[index]]} Lv {level} · "
                    f"HP {hp}/{max_hp} · MP {mp}/{max_mp}{condition}"
                )
            )
            detail_rows.append(
                PanelRow(
                    f"P{index + 1}: {JOBS[state.jobs[index]]} Lv {level} · "
                    f"HP {hp}/{max_hp} · MP {mp}/{max_mp}{condition}"
                )
            )
            if level >= 20 and state.jobs[index] not in {0, 3}:
                detail_rows.append(PanelRow(f"P{index + 1}: eligible for Dhama class change", False))
        if not detail_rows:
            detail_rows.append(PanelRow("Waiting for a loaded save"))
        detail_rows.extend(self._class_plan_rows(state))
        detail_rows.extend(self._recovery_rows(ram, state))
        return PanelSection(
            "Party",
            tuple(rows) or (PanelRow("Waiting for a loaded save"),),
            actions=(PanelAction("OPEN PARTY PLAN", "Party Plan", tuple(detail_rows)),),
        )

    def _battle_section(self, ram: bytes) -> PanelSection:
        rows = []
        groups = [
            f"0x{enemy_id:02X} ×{count}"
            for enemy_id, count in zip(ram[0x056D:0x0571], ram[0x0571:0x0575])
            if count
        ]
        if groups:
            rows.append(PanelRow("Groups · " + " · ".join(groups)))
        for index in range(8):
            hp = int.from_bytes(
                ram[0x0500 + index * 2:0x0502 + index * 2], "little"
            )
            if not hp:
                continue
            mp = ram[0x0510 + index]
            agility = ram[0x0518 + index]
            defense = int.from_bytes(
                ram[0x0520 + index * 2:0x0522 + index * 2], "little"
            )
            effects = self._battle_effects(
                ram[0x0530 + index * 2], ram[0x0531 + index * 2]
            )
            rows.append(
                PanelRow(
                    f"E{index + 1} · HP {hp} · MP {mp} · AGI {agility} · "
                    f"DEF {defense}{effects}"
                )
            )
        damage = ram[0x063F]
        if damage:
            attacker = ram[0x0051]
            attacker_name = f"P{attacker + 1}" if attacker < 4 else f"E{attacker - 3}"
            rows.append(PanelRow(f"Last hit · {attacker_name} · {damage} damage"))
        party_effects = []
        for index in range(4):
            effects = self._battle_effects(
                ram[0x073C + index * 2], ram[0x073D + index * 2]
            )
            if effects:
                party_effects.append(f"P{index + 1}{effects}")
        if party_effects:
            rows.append(PanelRow("Party effects · " + " · ".join(party_effects)))
        return PanelSection("Battle", tuple(rows) or (PanelRow("Battle starting"),))

    @staticmethod
    def _battle_effects(combat: int, condition: int) -> str:
        effects = []
        if combat & 0x03:
            effects.append("Sleep")
        for mask, label in (
            (0x04, "Barrier"),
            (0x08, "Bikill"),
            (0x10, "Surround"),
            (0x20, "Stopspell"),
            (0x40, "BeDragon"),
        ):
            if combat & mask:
                effects.append(label)
        if condition & 0x0F:
            effects.append("Bounce")
        for mask, label in ((0x10, "Confused"), (0x20, "Poison"), (0x40, "Numb")):
            if condition & mask:
                effects.append(label)
        return f" · {'/'.join(effects)}" if effects else ""

    def _progress_section(self, sram: bytes, state: GameState) -> PanelSection:
        vault_count = sum(bool(value & 0x7F) for value in sram[0x0D:0x8D])
        return PanelSection(
            "Adventure progress",
            (
                PanelRow(f"Orbs found {state.orbs_found}/6 · placed {state.orbs_placed}/6 · lit {state.pedestals}/6"),
                PanelRow(f"Pyramid chests {state.pyramid_chests}/24"),
                PanelRow(f"Samanao cave chests {state.samanao_chests}/23"),
                PanelRow(f"Vault items {vault_count}/128"),
            ),
            actions=(
                PanelAction("OPEN COMPLETION PLAN", "Completion Plan", self._completion_rows(state, vault_count)),
                PanelAction("OPEN CHEST CHECKLISTS", "Chest Checklists", self._chest_rows(state)),
                PanelAction("OPEN VAULT AUDIT", "Vault Audit", self._vault_rows(sram)),
            ),
        )

    def _world_section(self, ram: bytes) -> PanelSection:
        visited = ram[0x0750] | (ram[0x0751] << 8) | ((ram[0x0752] & 0x0F) << 16)
        town_names = [name for index, name in enumerate(TOWNS) if visited & (1 << index)]
        gold = int.from_bytes(ram[0x07BC:0x07BF], "little")
        return PanelSection(
            "Travel",
            (
                PanelRow(f"Gold {gold:,} · Repel {ram[0x00AD]} steps · {self._time_of_day(ram[0x06DF])}"),
                PanelRow(f"Return destinations {len(town_names)}/20"),
                PanelRow(", ".join(town_names) if town_names else "No Return destinations recorded"),
            ),
            preview_limit=3,
            actions=(
                PanelAction("OPEN RETURN LIST", "Return Destinations", self._return_rows(town_names)),
                PanelAction("OPEN TRAVEL AIDS", "Travel Aids", self._travel_aid_rows(ram)),
                PanelAction("OPEN TIME WINDOWS", "Time Windows", tuple(PanelRow(row) for row in TIME_WINDOWS)),
            ),
        )

    @staticmethod
    def _bit_count(data: bytes, fields: tuple[tuple[int, int], ...]) -> int:
        return sum((data[offset] & mask).bit_count() for offset, mask in fields)

    @staticmethod
    def _condition(status: int, hp: int) -> str:
        labels = []
        if not hp:
            labels.append("DEAD")
        if status & 0x20:
            labels.append("PSN")
        if status & 0x40:
            labels.append("NUMB")
        return f" · {'/'.join(labels)}" if labels else ""

    @staticmethod
    def _time_of_day(value: int) -> str:
        if value <= 0x1E:
            return "Sunrise"
        if value <= 0x3C:
            return "Morning"
        if value <= 0x5A:
            return "Afternoon"
        if value <= 0x78:
            return "Evening"
        if value <= 0x96:
            return "Dusk"
        if value <= 0xB4:
            return "Night"
        return "Dawn"


assert len(ACHIEVEMENTS) == 50