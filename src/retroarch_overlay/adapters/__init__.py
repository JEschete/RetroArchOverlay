from .base import AdapterRegistry, ContentHashResolver, GameAdapter

__all__ = [
	"AdapterRegistry",
	"ContentHashResolver",
	"DragonWarrior3Adapter",
	"EmeraldAdapter",
	"GameAdapter",
]


def __getattr__(name: str) -> object:
	if name == "DragonWarrior3Adapter":
		from .dragon_warrior_3 import DragonWarrior3Adapter

		return DragonWarrior3Adapter
	if name == "EmeraldAdapter":
		from .emerald import EmeraldAdapter

		return EmeraldAdapter
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
