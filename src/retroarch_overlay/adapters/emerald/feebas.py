import re
from pathlib import Path


FISHING_SPOT_COUNT = 447
MAP_OFFSET = 7


def feebas_spot_ids(seed: int) -> tuple[int, ...]:
    value = seed
    spots = []
    while len(spots) < 6:
        value = (1103515245 * value + 12345) & 0xFFFFFFFF
        spot = (value >> 16) % FISHING_SPOT_COUNT
        if spot == 0:
            spot = FISHING_SPOT_COUNT
        if spot >= 4:
            spots.append(spot)
    return tuple(spots)


def load_route119_fishing_spots(root: Path) -> dict[tuple[int, int], int]:
    behaviors_path = root / "include" / "constants" / "metatile_behaviors.h"
    behavior_names = []
    in_enum = False
    for line in behaviors_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().split("//", 1)[0].strip().rstrip(",")
        if stripped == "enum {":
            in_enum = True
            continue
        if in_enum and stripped == "};":
            break
        if in_enum and stripped.startswith("MB_"):
            behavior_names.append(stripped)
    behavior_ids = {name: index for index, name in enumerate(behavior_names)}

    source = (root / "src" / "metatile_behavior.c").read_text(encoding="utf-8")
    surfable = {
        behavior_ids[name]
        for name in re.findall(r"\[(MB_[A-Z0-9_]+)\]\s*=\s*[^\n]*TILE_FLAG_SURFABLE", source)
        if name in behavior_ids
    }
    surfable.discard(behavior_ids["MB_WATERFALL"])

    primary = (root / "data" / "tilesets" / "primary" / "general" / "metatile_attributes.bin").read_bytes()
    secondary = (root / "data" / "tilesets" / "secondary" / "fortree" / "metatile_attributes.bin").read_bytes()
    blocks = (root / "data" / "layouts" / "Route119" / "map.bin").read_bytes()

    spots = {}
    spot_id = 0
    for y in range(140):
        for x in range(40):
            offset = (y * 40 + x) * 2
            metatile_id = int.from_bytes(blocks[offset : offset + 2], "little") & 0x3FF
            attributes = primary if metatile_id < 512 else secondary
            attribute_id = metatile_id if metatile_id < 512 else metatile_id - 512
            attribute_offset = attribute_id * 2
            behavior = int.from_bytes(attributes[attribute_offset : attribute_offset + 2], "little") & 0xFF
            if behavior in surfable:
                spot_id += 1
                spots[(x, y)] = spot_id
    return spots


def tile_in_front(x: int, y: int, direction: int) -> tuple[int, int]:
    deltas = {1: (0, 1), 2: (0, -1), 3: (-1, 0), 4: (1, 0)}
    delta_x, delta_y = deltas.get(direction & 0xF, (0, 0))
    return x + delta_x - MAP_OFFSET, y + delta_y - MAP_OFFSET