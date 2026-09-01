from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RAProgress:
    username: str
    unlocked_ids: frozenset[int]
    message: str = ""


@dataclass(frozen=True, slots=True)
class RAConsole:
    console_id: int
    name: str
    active: bool = True
    is_game_system: bool = True


@dataclass(frozen=True, slots=True)
class RAGameReference:
    game_id: int
    title: str
    console_id: int
    console_name: str


@dataclass(frozen=True, slots=True)
class RAAchievement:
    achievement_id: int
    title: str
    description: str
    points: int
    achievement_type: str
    author: str
    display_order: int
    logic_hash: str = ""


@dataclass(frozen=True, slots=True)
class RAGame:
    game_id: int
    title: str
    console_id: int
    console_name: str
    parent_game_id: int | None
    achievements: tuple[RAAchievement, ...]


@dataclass(frozen=True, slots=True)
class RAMemoryNote:
    game_id: int
    address: str
    note: str
    author: str = ""
    scope: str = "set"


@dataclass(frozen=True, slots=True)
class RACodeNotesPage:
    game_id: int
    notes: tuple[RAMemoryNote, ...]
    related_game_ids: tuple[int, ...] = ()