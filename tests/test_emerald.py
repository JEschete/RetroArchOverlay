import unittest
from pathlib import Path

from retroarch_overlay.adapters.emerald.adapter import (
    BALL_POCKET_OFFSET,
    BALL_POCKET_SIZE,
    BERRY_POCKET_OFFSET,
    BERRY_POCKET_SIZE,
    BATTLE_MON_SIZE,
    BATTLE_MONS_ADDRESS,
    BATTLE_RESULTS_TURN_ADDRESS,
    BATTLE_TYPE_FLAGS_ADDRESS,
    BATTLERS_COUNT_ADDRESS,
    DEX_FLAG_BYTES,
    FLAGS_OFFSET,
    FLAGS_SIZE,
    DEWFORD_TREND_SEED_OFFSET,
    DECORATION_INVENTORY_OFFSET,
    DECORATION_INVENTORY_SIZE,
    POKEDEX_OWNED_OFFSET,
    REMATCHES_OFFSET,
    REMATCHES_SIZE,
    ROAMER_LOCATION_ADDRESS,
    ROAMER_OFFSET,
    ROAMER_SIZE,
    PLAYER_POSITION_ADDRESS,
    SAVE_BLOCK_1_POINTER,
    SAVE_BLOCK_2_POINTER,
    SECURITY_KEY_OFFSET,
    SECRET_BASE_DECORATIONS_OFFSET,
    SECRET_BASE_DECORATIONS_SIZE,
    ITEM_POCKET_OFFSET,
    ITEM_POCKET_SIZE,
    MAIN_IN_BATTLE_ADDRESS,
    MAIN_IN_BATTLE_MASK,
    EmeraldAdapter,
)
from retroarch_overlay.models import RetroArchStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POKEEMERALD_ROOT = PROJECT_ROOT / "pokeemerald"
requires_pokeemerald = unittest.skipUnless(
    (POKEEMERALD_ROOT / "src" / "data" / "wild_encounters.json").is_file(),
    "pokeemerald decomp checkout is not available",
)


class FakeMemory:
    def __init__(
        self,
        map_group: int,
        map_number: int,
        caught: tuple[int, ...] = (),
        badges: tuple[int, ...] = (),
        rematches: tuple[int, ...] = (),
        feebas_position: bytes | None = None,
        feebas_seed: int = 0,
        battle_mons: bytes | None = None,
        balls: dict[int, int] | None = None,
        roamer: tuple[int, int, int, int] | None = None,
        player_position: tuple[int, int] = (0, 0),
        in_battle: bool | None = None,
        battle_flags: int = 0,
    ):
        self.save_block_1 = 0x02010000
        self.save_block_2 = 0x02020000
        self.map_group = map_group
        self.map_number = map_number
        self.player_position = player_position
        self.caught_flags = bytearray(DEX_FLAG_BYTES)
        for national_number in caught:
            bit_index = national_number - 1
            self.caught_flags[bit_index // 8] |= 1 << (bit_index % 8)
        self.event_flags = bytearray(FLAGS_SIZE)
        for badge in badges:
            flag_id = 0x867 + badge
            self.event_flags[flag_id // 8] |= 1 << (flag_id % 8)
        self.rematches = bytearray(REMATCHES_SIZE)
        for rematch in rematches:
            self.rematches[rematch] = 1
        self.feebas_position = feebas_position
        self.feebas_seed = feebas_seed
        self.battle_mons = battle_mons
        self.in_battle = battle_mons is not None if in_battle is None else in_battle
        self.battle_flags = battle_flags
        self.security_key = 0x1234
        self.ball_pocket = bytearray(BALL_POCKET_SIZE)
        for slot, (item_id, quantity) in enumerate((balls or {}).items()):
            offset = slot * 4
            self.ball_pocket[offset : offset + 2] = item_id.to_bytes(2, "little")
            self.ball_pocket[offset + 2 : offset + 4] = (
                quantity ^ self.security_key
            ).to_bytes(2, "little")
        self.roamer = bytearray(ROAMER_SIZE)
        self.roamer_location = bytes(2)
        self.items = bytes(ITEM_POCKET_SIZE)
        self.berries = bytes(BERRY_POCKET_SIZE)
        self.decorations = bytes(DECORATION_INVENTORY_SIZE)
        self.placed_decorations = bytes(SECRET_BASE_DECORATIONS_SIZE)
        if roamer is not None:
            species_id, hp, roamer_group, roamer_number = roamer
            self.roamer[0x08:0x0A] = species_id.to_bytes(2, "little")
            self.roamer[0x0A:0x0C] = hp.to_bytes(2, "little")
            self.roamer[0x0C] = 40
            self.roamer[0x13] = 1
            self.roamer_location = bytes((roamer_group, roamer_number))

    def read_memory(self, address: int, size: int) -> bytes:
        if (address, size) == (SAVE_BLOCK_1_POINTER, 4):
            return self.save_block_1.to_bytes(4, "little")
        if (address, size) == (self.save_block_1 + 4, 2):
            return bytes((self.map_group, self.map_number))
        if (address, size) == (self.save_block_1, 4):
            return (
                self.player_position[0].to_bytes(2, "little", signed=True)
                + self.player_position[1].to_bytes(2, "little", signed=True)
            )
        if (address, size) == (SAVE_BLOCK_2_POINTER, 4):
            return self.save_block_2.to_bytes(4, "little")
        if (address, size) == (BATTLERS_COUNT_ADDRESS, 2):
            count = len(self.battle_mons) // BATTLE_MON_SIZE if self.battle_mons else 0
            return count.to_bytes(2, "little")
        if (address, size) == (MAIN_IN_BATTLE_ADDRESS, 1):
            return bytes((MAIN_IN_BATTLE_MASK if self.in_battle else 0,))
        if address == BATTLE_MONS_ADDRESS and self.battle_mons is not None:
            assert self.battle_mons is not None
            assert size == len(self.battle_mons)
            return self.battle_mons
        if (address, size) == (BATTLE_TYPE_FLAGS_ADDRESS, 4):
            return self.battle_flags.to_bytes(4, "little")
        if (address, size) == (BATTLE_RESULTS_TURN_ADDRESS, 1):
            return b"\x00"
        if (address, size) == (self.save_block_2 + SECURITY_KEY_OFFSET, 2):
            return self.security_key.to_bytes(2, "little")
        if (address, size) == (self.save_block_1 + BALL_POCKET_OFFSET, BALL_POCKET_SIZE):
            return bytes(self.ball_pocket)
        if (address, size) == (self.save_block_2 + POKEDEX_OWNED_OFFSET, DEX_FLAG_BYTES):
            return bytes(self.caught_flags)
        if (address, size) == (self.save_block_1 + FLAGS_OFFSET, FLAGS_SIZE):
            return bytes(self.event_flags)
        if (address, size) == (self.save_block_1 + REMATCHES_OFFSET, REMATCHES_SIZE):
            return bytes(self.rematches)
        if (address, size) == (self.save_block_1 + ROAMER_OFFSET, ROAMER_SIZE):
            return bytes(self.roamer)
        if (address, size) == (ROAMER_LOCATION_ADDRESS, 2):
            return self.roamer_location
        if (address, size) == (self.save_block_1 + ITEM_POCKET_OFFSET, ITEM_POCKET_SIZE):
            return self.items
        if (address, size) == (self.save_block_1 + BERRY_POCKET_OFFSET, BERRY_POCKET_SIZE):
            return self.berries
        if (address, size) == (self.save_block_1 + DECORATION_INVENTORY_OFFSET, DECORATION_INVENTORY_SIZE):
            return self.decorations
        if (address, size) == (self.save_block_1 + SECRET_BASE_DECORATIONS_OFFSET, SECRET_BASE_DECORATIONS_SIZE):
            return self.placed_decorations
        if (address, size) == (self.save_block_1 + DEWFORD_TREND_SEED_OFFSET, 2):
            return self.feebas_seed.to_bytes(2, "little")
        if (address, size) == (PLAYER_POSITION_ADDRESS, 9) and self.feebas_position is not None:
            return self.feebas_position
        raise AssertionError(f"Unexpected read: 0x{address:08X}, {size}")


@requires_pokeemerald
class EmeraldAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = EmeraldAdapter(POKEEMERALD_ROOT)

    def _wild_battle_mons(self) -> bytes:
        battle_mons = bytearray(BATTLE_MON_SIZE * 2)
        offset = BATTLE_MON_SIZE
        species_id = self.adapter._species_ids["SPECIES_ZIGZAGOON"]
        battle_mons[offset : offset + 2] = species_id.to_bytes(2, "little")
        battle_mons[offset + 0x21 : offset + 0x23] = bytes((0, 0))
        battle_mons[offset + 0x28 : offset + 0x2A] = (5).to_bytes(2, "little")
        battle_mons[offset + 0x2A] = 4
        battle_mons[offset + 0x2C : offset + 0x2E] = (12).to_bytes(2, "little")
        return bytes(battle_mons)

    def _double_battle_mons(self) -> bytes:
        battle_mons = bytearray(BATTLE_MON_SIZE * 4)
        for battler, species_name, hp in (
            (1, "SPECIES_ZIGZAGOON", 5),
            (3, "SPECIES_POOCHYENA", 0),
        ):
            offset = BATTLE_MON_SIZE * battler
            species_id = self.adapter._species_ids[species_name]
            battle_mons[offset : offset + 2] = species_id.to_bytes(2, "little")
            battle_mons[offset + 0x21 : offset + 0x23] = bytes((0, 0))
            battle_mons[offset + 0x28 : offset + 0x2A] = hp.to_bytes(2, "little")
            battle_mons[offset + 0x2A] = 4
            battle_mons[offset + 0x2C : offset + 0x2E] = (12).to_bytes(2, "little")
        return bytes(battle_mons)

    def test_every_encounter_map_has_an_id(self) -> None:
        self.assertEqual(set(self.adapter._encounters), set(self.adapter.map_ids))

    def test_numeric_defines_keep_full_species_trainer_and_flag_values(self) -> None:
        self.assertEqual(self.adapter._species_ids["SPECIES_POOCHYENA"], 286)
        self.assertEqual(self.adapter._trainer_ids["TRAINER_BRENDAN_ROUTE_110_MUDKIP"], 521)
        self.assertEqual(self.adapter._flag_ids["FLAG_RECEIVED_POWDER_JAR"], 0x151)

    def test_supports_installed_mgba_status_identifier(self) -> None:
        status = RetroArchStatus(
            "PLAYING",
            "game_boy_advance",
            "Pokemon - Emerald Version (USA, Europe),crc32=1f1c08fb",
        )
        self.assertTrue(self.adapter.supports(status))

    def test_requires_official_ra_hash_when_retroarch_reports_crc(self) -> None:
        status = RetroArchStatus(
            "PLAYING",
            "game_boy_advance",
            "Pokemon Emerald",
            "3c3c927f",
        )
        self.assertTrue(
            self.adapter.supports(status, "31446456df04356cb9f2145bada42ed2")
        )
        self.assertFalse(self.adapter.supports(status, "0" * 32))
        self.assertFalse(self.adapter.supports(status))

    def test_zero_save_pointer_waits_for_game(self) -> None:
        memory = FakeMemory(0, 0)
        memory.save_block_1 = 0
        snapshot = self.adapter.snapshot(memory)
        self.assertEqual(snapshot.location, "Waiting for game/save")
        self.assertEqual(snapshot.sections[0].rows[0].text, "Load or continue a save")

    def test_interior_without_encounters_has_a_location_name(self) -> None:
        snapshot = self.adapter.snapshot(FakeMemory(1, 2))
        self.assertEqual(snapshot.location, "Littleroot Town · Mays House · 1F")
        self.assertEqual(snapshot.sections[0].title, "Professor Oak Challenge")
        self.assertEqual(snapshot.sections[-1].title, "Collections")

    def test_poc_progress_uses_set_badge_order(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE101"]
        caught = tuple(range(1, 40))
        snapshot = self.adapter.snapshot(FakeMemory(map_group, map_number, caught, (0,)))
        self.assertEqual(
            snapshot.sections[0].rows[0].text,
            "Next: Wattson  39/66  need 27",
        )

    def test_route_completion_is_derived_from_decomp_flags(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE104"]
        snapshot = self.adapter.snapshot(
            FakeMemory(map_group, map_number, player_position=(10, 10))
        )
        sections = {section.title: section for section in snapshot.sections}
        self.assertIn("Route trainers", sections)
        item_section = next(
            section for section in snapshot.sections if section.title.startswith("Route items")
        )
        self.assertEqual(item_section.title, "Route items · You (10,10)")
        self.assertEqual(item_section.rows[0].text, "0/9 complete")
        self.assertTrue(item_section.rows[0].text.endswith("complete"))
        self.assertTrue(any("(" in row.text for row in item_section.rows[1:]))
        self.assertFalse(any("Δ(" in row.text for row in item_section.rows[1:]))
        trainer_text = " ".join(row.text for row in sections["Route trainers"].rows)
        self.assertEqual(trainer_text.count("Rival Rustboro"), 1)

    def test_only_current_route_ready_rematches_are_shown(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE104"]
        route104_rematches = self.adapter._rematches_by_map["ROUTE104"]
        ready_index, ready_name = route104_rematches[0]
        snapshot = self.adapter.snapshot(
            FakeMemory(map_group, map_number, rematches=(ready_index,))
        )
        section = next(section for section in snapshot.sections if section.title == "Rematches ready")
        self.assertEqual(section.rows[0].text, ready_name)

    def test_feebas_alert_only_appears_when_facing_valid_tile(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE119"]
        seed = 12345
        spot_id = __import__(
            "retroarch_overlay.adapters.emerald.feebas", fromlist=["feebas_spot_ids"]
        ).feebas_spot_ids(seed)[0]
        target_x, target_y = next(
            position
            for position, candidate in self.adapter._route119_fishing_spots.items()
            if candidate == spot_id
        )
        position = bytearray(9)
        position[0:2] = (target_x + 7).to_bytes(2, "little")
        position[2:4] = (target_y + 8).to_bytes(2, "little")
        position[8] = 2
        snapshot = self.adapter.snapshot(
            FakeMemory(
                map_group,
                map_number,
                feebas_position=bytes(position),
                feebas_seed=seed,
            )
        )
        self.assertIn(
            "RA · One Tile Away from Beauty",
            {section.title for section in snapshot.sections},
        )

    def test_wild_battle_replaces_overworld_with_catch_chances(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE101"]
        snapshot = self.adapter.snapshot(
            FakeMemory(
                map_group,
                map_number,
                battle_mons=self._wild_battle_mons(),
                balls={4: 5},
            )
        )
        self.assertEqual(snapshot.location, "Battle · Route 101")
        self.assertEqual(
            tuple(section.title for section in snapshot.sections),
            ("Battle", "Catch chances"),
        )
        self.assertIn("Poké Ball x5", snapshot.sections[1].rows[0].text)

    def test_double_battle_shows_both_opponents(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE101"]
        snapshot = self.adapter.snapshot(
            FakeMemory(
                map_group,
                map_number,
                battle_mons=self._double_battle_mons(),
                battle_flags=(1 << 0) | (1 << 3),
            )
        )

        self.assertEqual(len(snapshot.sections[0].rows), 2)
        self.assertIn("Zigzagoon", snapshot.sections[0].rows[0].text)
        self.assertIn("Poochyena", snapshot.sections[0].rows[1].text)
        self.assertIn("FNT", snapshot.sections[0].rows[1].text)
        self.assertEqual(tuple(section.title for section in snapshot.sections), ("Battle",))

    def test_stale_battle_globals_do_not_replace_overworld(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE101"]
        snapshot = self.adapter.snapshot(
            FakeMemory(
                map_group,
                map_number,
                battle_mons=self._wild_battle_mons(),
                in_battle=False,
            )
        )
        self.assertFalse(snapshot.location.startswith("Battle"))

    def test_roamer_alert_only_appears_on_same_route(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE110"]
        latios = self.adapter._species_ids["SPECIES_LATIOS"]
        snapshot = self.adapter.snapshot(
            FakeMemory(
                map_group,
                map_number,
                roamer=(latios, 91, map_group, map_number),
            )
        )
        section = next(
            section
            for section in snapshot.sections
            if section.title == "RA · Flying Through the Eons"
        )
        self.assertIn("Latios IS ON THIS ROUTE", section.rows[0].text)

    def test_relevant_route_achievement_is_explicitly_tracked(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE103"]
        snapshot = self.adapter.snapshot(FakeMemory(map_group, map_number))
        section = next(section for section in snapshot.sections if section.title == "RA nearby")
        self.assertEqual(section.rows[0].text, "Let's Have a Quick Battle!")

    def test_gym_missable_alert_is_first_and_strong(self) -> None:
        map_group, map_number = next(
            map_id
            for map_id, map_name in self.adapter._map_constants_by_id.items()
            if map_name == "RustboroCity_Gym"
        )
        snapshot = self.adapter.snapshot(FakeMemory(map_group, map_number))

        self.assertTrue(snapshot.sections[0].alert)
        self.assertEqual(
            snapshot.sections[0].title,
            "MISSABLE · Battle Addict - Rustboro",
        )

    def test_route_101_snapshot_contains_land_encounters(self) -> None:
        map_group, map_number = self.adapter.map_ids["MAP_ROUTE101"]
        poochyena = self.adapter._national_dex_numbers["SPECIES_POOCHYENA"]
        snapshot = self.adapter.snapshot(FakeMemory(map_group, map_number, (poochyena,)))
        self.assertEqual(snapshot.location, "Route 101")
        self.assertEqual(snapshot.sections[1].title, "Land · rate 20")
        rows = "\n".join(row.text for row in snapshot.sections[1].rows)
        self.assertIn("Poochyena", rows)
        self.assertIn("Wurmple", rows)
        caught = {row.text.split()[0]: row.caught for row in snapshot.sections[1].rows}
        self.assertTrue(caught["Poochyena"])
        self.assertFalse(caught["Wurmple"])


if __name__ == "__main__":
    unittest.main()