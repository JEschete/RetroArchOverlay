import hashlib
import tempfile
import unittest
import zlib
from pathlib import Path

from retroarch_overlay.adapters import ContentHashResolver
from retroarch_overlay.models import RetroArchStatus
from retroarch_overlay.retroarch import (
    RetroArchClient,
    parse_memory_response,
    parse_status_response,
)


class StubRetroArchClient(RetroArchClient):
    def __init__(self) -> None:
        self.commands: list[str] = []

    def _request(self, command: str) -> str:
        self.commands.append(command)
        _, address, size = command.split()
        values = " ".join(f"{index & 0xFF:02x}" for index in range(int(size)))
        return f"READ_CORE_MEMORY {address} {values}"


class ResponseParsingTests(unittest.TestCase):
    def test_parses_playing_status(self) -> None:
        status = parse_status_response("GET_STATUS PLAYING mGBA,Pokemon Emerald.gba\n")
        self.assertEqual(status.state, "PLAYING")
        self.assertEqual(status.core, "mGBA")
        self.assertEqual(status.content, "Pokemon Emerald.gba")

    def test_parses_content_crc32(self) -> None:
        status = parse_status_response(
            "GET_STATUS PLAYING game_boy_advance,Pokemon Emerald,crc32=1f1c08fb\n"
        )
        self.assertEqual(status.content, "Pokemon Emerald")
        self.assertEqual(status.content_crc32, "1f1c08fb")

    def test_parses_memory_bytes(self) -> None:
        data = parse_memory_response("READ_CORE_MEMORY 3005d8c 00 01 02 03\n", 0x03005D8C)
        self.assertEqual(data, b"\x00\x01\x02\x03")

    def test_large_memory_reads_are_chunked(self) -> None:
        client = StubRetroArchClient()

        data = client.read_memory(0x6000, 600)

        self.assertEqual(len(data), 600)
        self.assertEqual(
            client.commands,
            [
                "READ_CORE_MEMORY 6000 256",
                "READ_CORE_MEMORY 6100 256",
                "READ_CORE_MEMORY 6200 88",
            ],
        )

    def test_resolves_active_content_md5_using_reported_crc(self) -> None:
        content = b"supported game content"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Example Game.gba"
            path.write_bytes(content)
            status = RetroArchStatus(
                "PLAYING",
                "example_core",
                "Example Game",
                f"{zlib.crc32(content):08x}",
            )
            resolved = ContentHashResolver((Path(directory),)).resolve(status)
        self.assertEqual(
            resolved,
            hashlib.md5(content, usedforsecurity=False).hexdigest(),
        )

    def test_resolves_hash_from_exact_local_rom_path(self) -> None:
        content = b"configured ROM"
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "locally configured game.nes"
            rom.write_bytes(content)
            status = RetroArchStatus("PLAYING", "example_core", "different display name", "")

            resolved = ContentHashResolver(files=(rom,)).resolve(status)

        self.assertEqual(resolved, hashlib.md5(content, usedforsecurity=False).hexdigest())

    def test_exposes_headerless_nes_hash_for_ra_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "subset.nes"
            rom.write_bytes(b"NES\x1a" + bytes(12) + b"game content")

            hashes = ContentHashResolver.hashes_for_file(rom)

        self.assertEqual(
            hashes,
            (hashlib.md5(b"game content", usedforsecurity=False).hexdigest(),),
        )

    def test_does_not_guess_between_multiple_local_roms_without_crc_or_name_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.nes"
            second = Path(directory) / "second.nes"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            status = RetroArchStatus("PLAYING", "example_core", "unknown game", "")

            resolved = ContentHashResolver(files=(first, second)).resolve(status)

        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
