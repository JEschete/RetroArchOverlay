import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from retroarch_overlay.adapters import ContentHashResolver
from retroarch_overlay.adapters.dragon_warrior_3.adapter import (
    RAM_SIZE,
    SRAM_ADDRESS,
    SRAM_READ_SIZE,
    DragonWarrior3Adapter,
)
from retroarch_overlay.core.retroachievements import RAProgress
from retroarch_overlay.infrastructure.retroachievements import load_ra_progress
from retroarch_overlay.models import RetroArchStatus


class FakeMemory:
    def __init__(self) -> None:
        self.ram = bytearray(RAM_SIZE)
        self.sram = bytearray(SRAM_READ_SIZE)
        self.ram[0x002F] = 0
        self.ram[0x002A:0x002C] = bytes((12, 34))
        self.ram[0x008A:0x008C] = (0x1234).to_bytes(2, "little")
        self.ram[0x0700:0x0704] = bytes((20, 18, 17, 0))
        self.ram[0x0718:0x071C] = bytes((0, 1, 2, 0))
        self.ram[0x07C1:0x07C5] = bytes((1, 2, 3, 0))
        self.ram[0x071C:0x071E] = (100).to_bytes(2, "little")
        self.ram[0x0724:0x0726] = (120).to_bytes(2, "little")
        self.ram[0x072C:0x072E] = (30).to_bytes(2, "little")
        self.ram[0x0734:0x0736] = (40).to_bytes(2, "little")
        self.ram[0x07BC:0x07BF] = (12345).to_bytes(3, "little")

    def read_memory(self, address: int, size: int) -> bytes:
        if (address, size) == (0, RAM_SIZE):
            return bytes(self.ram)
        if (address, size) == (SRAM_ADDRESS, SRAM_READ_SIZE):
            return bytes(self.sram)
        raise AssertionError(f"Unexpected read: 0x{address:04X}, {size}")


class DragonWarrior3AdapterTests(unittest.TestCase):
    def test_loads_account_achievement_progress(self) -> None:
        response = BytesIO(
            b'{"Achievements":{"50439":{"DateEarned":"2024-01-01"},'
            b'"50440":{"DateEarned":null}}}'
        )
        response.__enter__ = lambda: response
        response.__exit__ = lambda *_: None
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "retroarch.cfg"
            config.write_text('cheevos_username = "PlayerOne"\n', encoding="utf-8")
            progress = load_ra_progress(
                config, 1667, "web-api-key", lambda *_args, **_kwargs: response
            )
        self.assertEqual(progress.username, "PlayerOne")
        self.assertEqual(progress.unlocked_ids, {50439})

    def test_account_unlocks_are_shown_with_session_detections(self) -> None:
        progress = RAProgress("PlayerOne", frozenset({50439}))
        snapshot = DragonWarrior3Adapter(progress).snapshot(FakeMemory())
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "1/50 unlocked · PlayerOne")
        self.assertIn("Now You Can Open Doors · account", achievements.rows[2].text)

    def test_supports_official_normalized_hash(self) -> None:
        adapter = DragonWarrior3Adapter()
        status = RetroArchStatus("PLAYING", "Mesen", "Dragon Warrior III", "a86a5318")
        self.assertTrue(adapter.supports(status, "16a03048ce659d3d733026b6b72f2470"))
        self.assertFalse(adapter.supports(status, "0" * 32))

    def test_nes_hash_resolver_ignores_ines_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "Dragon Warrior III.nes"
            rom.write_bytes(b"NES\x1a" + bytes(12) + b"cartridge")
            status = RetroArchStatus("PLAYING", "Mesen", rom.name)
            resolved = ContentHashResolver((Path(directory),)).resolve(status)
        import hashlib

        self.assertEqual(resolved, hashlib.md5(b"cartridge", usedforsecurity=False).hexdigest())

    def test_nes_hash_resolver_normalizes_hash_when_status_uses_raw_crc(self) -> None:
        import hashlib
        import zlib

        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "Dragon Warrior III.nes"
            data = b"NES\x1a" + bytes(12) + b"cartridge"
            rom.write_bytes(data)
            status = RetroArchStatus("PLAYING", "Mesen", rom.name, f"{zlib.crc32(data):08x}")
            resolved = ContentHashResolver((Path(directory),)).resolve(status)
        self.assertEqual(resolved, hashlib.md5(b"cartridge", usedforsecurity=False).hexdigest())

    def test_first_snapshot_starts_at_zero_and_shows_useful_state(self) -> None:
        memory = FakeMemory()
        snapshot = DragonWarrior3Adapter().snapshot(memory)
        self.assertEqual(snapshot.location, "World · Map 1234 · (12,34)")
        self.assertEqual(snapshot.map_position.x, 12)
        self.assertEqual(snapshot.map_position.y, 34)
        self.assertTrue(snapshot.map_position.is_world)
        objective = next(section for section in snapshot.sections if section.title == "Current objective")
        self.assertEqual(objective.rows[0].text, "Next: recruit a full party")
        self.assertEqual(
            tuple(action.label for action in objective.actions),
            ("OPEN ROUTE PLAN", "OPEN KEY ITEM UNLOCKS", "OPEN RA PRIORITIES"),
        )
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "0/50 detected this session")
        self.assertEqual(achievements.rows[1].text, "32 exact detectors active · fresh baseline")
        party = next(section for section in snapshot.sections if section.title == "Party")
        self.assertIn("Hero Lv 20", party.rows[0].text)
        resources = next(section for section in snapshot.sections if section.title == "Resources")
        self.assertIn("Gold 12,345", resources.rows[2].text)

    def test_observed_full_party_and_two_sages_increment_counter(self) -> None:
        adapter = DragonWarrior3Adapter()
        memory = FakeMemory()
        adapter.snapshot(memory)
        memory.ram[0x0703] = 10
        memory.ram[0x07C4] = 4
        memory.ram[0x0719:0x071C] = bytes((3, 3, 4))
        snapshot = adapter.snapshot(memory)
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "3/50 detected this session")
        detected = " ".join(row.text for row in achievements.rows)
        self.assertIn("With a Little Help from My Friends", detected)
        self.assertIn("A New Line of Work", detected)
        self.assertIn("So Much Magic", detected)

    def test_new_unique_item_is_named_and_detects_achievement(self) -> None:
        adapter = DragonWarrior3Adapter()
        memory = FakeMemory()
        adapter.snapshot(memory)
        memory.ram[0x077C] = 0x58
        snapshot = adapter.snapshot(memory)
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "1/50 detected this session")
        self.assertIn("Now You Can Open Doors", achievements.rows[1].text)
        self.assertEqual(snapshot.sections[-1].rows[0].text, "Thief's Key")

    def test_moving_item_to_vault_does_not_detect_it_twice(self) -> None:
        adapter = DragonWarrior3Adapter()
        memory = FakeMemory()
        memory.ram[0x077C] = 0x58
        adapter.snapshot(memory)
        memory.ram[0x077C] = 0
        memory.sram[0x0D] = 0x58
        snapshot = adapter.snapshot(memory)
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "0/50 detected this session")

    def test_swapping_party_members_is_not_a_profession_change(self) -> None:
        adapter = DragonWarrior3Adapter()
        memory = FakeMemory()
        adapter.snapshot(memory)
        memory.ram[0x0719:0x071B] = bytes((2, 1))
        memory.ram[0x07C2:0x07C4] = bytes((3, 2))
        snapshot = adapter.snapshot(memory)
        achievements = next(section for section in snapshot.sections if section.title == "RetroAchievements")
        self.assertEqual(achievements.rows[0].text, "0/50 detected this session")

    def test_key_items_drive_objective_unlock_and_orb_guidance(self) -> None:
        memory = FakeMemory()
        memory.ram[0x0703] = 10
        memory.ram[0x07C4] = 4
        for slot, item_id in enumerate((0x58, 0x59, 0x4F, 0x5A, 0x77, 0x78)):
            memory.ram[0x077C + slot] = item_id
        memory.sram[0xCE] = 0x03
        snapshot = DragonWarrior3Adapter().snapshot(memory)

        objective = next(section for section in snapshot.sections if section.title == "Current objective")
        self.assertEqual(objective.rows[0].text, "Next: orb hunt · 2/6 found")
        unlocks = next(section for section in snapshot.sections if section.title == "Unlocks")
        self.assertEqual(unlocks.rows[0].text, "Key items 4/12")
        orbs = next(section for section in snapshot.sections if section.title == "Orb route")
        self.assertIn("Purple Orb", orbs.rows[1].text)
        self.assertEqual(orbs.actions[0].label, "OPEN ORB CHECKLIST")

    def test_battle_lists_enemy_groups_and_hp(self) -> None:
        memory = FakeMemory()
        memory.ram[0x0032] = 0xFD
        memory.ram[0x056D] = 0x44
        memory.ram[0x0571] = 3
        memory.ram[0x0500:0x0502] = (77).to_bytes(2, "little")
        memory.ram[0x0510] = 12
        memory.ram[0x0518] = 28
        memory.ram[0x0520:0x0522] = (64).to_bytes(2, "little")
        memory.ram[0x0530] = 0x21
        memory.ram[0x0051] = 5
        memory.ram[0x063F] = 19
        snapshot = DragonWarrior3Adapter().snapshot(memory)
        self.assertTrue(snapshot.location.startswith("Battle"))
        self.assertEqual(snapshot.sections[0].title, "Battle")
        battle = next(section for section in snapshot.sections if section.title == "Battle")
        self.assertEqual(battle.rows[0].text, "Groups · 0x44 ×3")
        self.assertEqual(
            battle.rows[1].text,
            "E1 · HP 77 · MP 12 · AGI 28 · DEF 64 · Sleep/Stopspell",
        )
        self.assertEqual(battle.rows[2].text, "Last hit · E2 · 19 damage")


if __name__ == "__main__":
    unittest.main()