from collections import Counter, deque
from dataclasses import dataclass

from ...models import MapPosition, OverlaySnapshot, PanelRow, PanelSection, RetroArchStatus
from ...retroachievements import RAProgress
from ...retroarch import MemoryReader
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
            sections = [self._achievement_section(), self._party_section(ram, state)]
        sections.extend((self._progress_section(sram, state), self._world_section(ram)))
        if self._recent_items:
            sections.append(
                PanelSection(
                    "New items observed",
                    tuple(
                        PanelRow(ITEM_NAMES.get(item_id, f"Item ID 0x{item_id:02X}"))
                        for item_id in self._recent_items
                    ),
                )
            )
        return OverlaySnapshot(
            self.name,
            f"Battle · {location}" if battle else location,
            tuple(sections),
            MapPosition(area, map_id, *coordinates, map_bank in {0, 2}),
        )

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
        return PanelSection("RetroAchievements", tuple(rows), preview_limit=7)

    def _party_section(self, ram: bytes, state: GameState) -> PanelSection:
        rows = []
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
        return PanelSection("Party", tuple(rows) or (PanelRow("Waiting for a loaded save"),))

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
        return PanelSection(
            "Adventure progress",
            (
                PanelRow(f"Orbs found {state.orbs_found}/6 · placed {state.orbs_placed}/6 · lit {state.pedestals}/6"),
                PanelRow(f"Pyramid chests {state.pyramid_chests}/24"),
                PanelRow(f"Samanao cave chests {state.samanao_chests}/23"),
                PanelRow(f"Vault items {sum(bool(value & 0x7F) for value in sram[0x0D:0x8D])}/128"),
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