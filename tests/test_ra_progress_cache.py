import json
import tempfile
import threading
import unittest
from pathlib import Path

from retroarch_overlay.core.retroachievements import RAProgress
from retroarch_overlay.retroachievements import BackgroundRAProgressProvider


class BackgroundRAProgressProviderTests(unittest.TestCase):
    def test_returns_live_progress_without_blocking_on_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "retroarch.cfg"
            config.write_text('cheevos_username = "PlayerOne"\n', encoding="utf-8")
            release = threading.Event()

            def load(_config: Path, _game_id: int, _api_key: str) -> RAProgress:
                release.wait(1)
                return RAProgress("PlayerOne", frozenset({42}))

            provider = BackgroundRAProgressProvider(config, "key", root / "cache", loader=load)
            progress = provider(668)

            self.assertEqual(progress.message, "Loading RetroAchievements progress...")
            release.set()
            for _ in range(100):
                if progress.unlocked_ids == frozenset({42}):
                    break
                threading.Event().wait(0.01)
            self.assertEqual(progress.unlocked_ids, frozenset({42}))

    def test_uses_fresh_disk_cache_without_calling_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "retroarch.cfg"
            config.write_text('cheevos_username = "PlayerOne"\n', encoding="utf-8")
            provider = BackgroundRAProgressProvider(
                config,
                "key",
                root / "cache",
                loader=lambda *_args: self.fail("fresh cache should not load"),
            )
            path = provider._cache_path(668)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"username": "PlayerOne", "unlocked_ids": [7], "message": ""}),
                encoding="utf-8",
            )

            progress = provider(668)

            self.assertEqual(progress.unlocked_ids, frozenset({7}))


if __name__ == "__main__":
    unittest.main()