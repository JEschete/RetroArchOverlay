from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
GUIDE = ROOT / "plugins/RAO_dragonwarrior3/resources/UnifiedWalkThrough.md"
SETTINGS = Path.home() / "AppData/Local/RetroArchOverlay/local_settings.json"
PLUGIN_ID = "org.jeschete.retroarch-overlay.dragonwarrior3"
CLASS_NAMES = (
    "Hero",
    "Wizard",
    "Pilgrim",
    "Sage",
    "Soldier",
    "Merchant",
    "Fighter",
    "Goof-Off",
)
ITEM_NAMES = (
    "Cypress Stick", "Club", "Copper Sword", "Magic Knife", "Iron Spear",
    "Battle Axe", "Broad Sword", "Wizard's Wand", "Poison Needle", "Iron Claw",
    "Thorn Whip", "Giant Shears", "Chain Sickle", "Thor's Sword",
    "Snowblast Sword", "Demon Axe", "Staff of Rain", "Sword of Gaia",
    "Staff of Reflection", "Sword of Destruction", "Multi-Edge Sword",
    "Staff of Force", "Sword of Illusion", "Zombie Slasher", "Falcon Sword",
    "Sledge Hammer", "Thunder Sword", "Staff of Thunder", "Sword of Kings",
    "Orochi Sword", "Dragon Killer", "Staff of Judgment", "Clothes",
    "Training Suit", "Leather Armor", "Flashy Clothes", "Half Plate Armor",
    "Full Plate Armor", "Magic Armor", "Cloak of Evasion", "Armor of Radiance",
    "Iron Apron", "Animal Suit", "Fighting Suit", "Sacred Robe", "Armor of Hades",
    "Water Flying Cloth", "Chain Mail", "Wayfarer's Clothes", "Revealing Swimsuit",
    "Magic Bikini", "Shell Armor", "Armor of Terrafirma", "Dragon Mail",
    "Swordedge Armor", "Angel's Robe", "Leather Shield", "Iron Shield",
    "Shield of Strength", "Shield of Heroes", "Shield of Sorrow", "Bronze Shield",
    "Silver Shield", "Golden Crown", "Iron Helmet", "Mysterious Hat",
    "Unlucky Helmet", "Turban", "Noh Mask", "Leather Helmet", "Iron Mask",
    "Sacred Amulet", "Ring of Life", "Shoes of Happiness", "Golden Claw",
    "Meteorite Armband",
)


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def row(values: list[str]) -> str:
    return "| " + " | ".join(values) + " |"


def is_separator(values: list[str]) -> bool:
    return bool(values) and all(set(value) <= {"-", ":"} for value in values)


def main() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    rom_path = Path(settings["plugins"][PLUGIN_ID]["rom_path"])
    rom = rom_path.read_bytes()
    masks = rom[0x1147:0x1147 + len(ITEM_NAMES)]
    if len(masks) != len(ITEM_NAMES) or masks[0] != 0xFF or masks[8] != 0x02:
        raise RuntimeError("Configured ROM equipment table failed sanity checks")

    eligibility: dict[str, str] = {}
    for item_id, name in enumerate(ITEM_NAMES):
        classes = [
            class_name
            for bit, class_name in enumerate(CLASS_NAMES)
            if masks[item_id] & (1 << bit)
        ]
        value = "All classes" if len(classes) == len(CLASS_NAMES) else ", ".join(classes)
        if name in {"Revealing Swimsuit", "Magic Bikini"}:
            value += " (female only)"
        elif name == "Sword of Illusion":
            value += " (female only)"
        eligibility[name] = value

    lines = GUIDE.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    annotated_rows = 0
    dedicated_tables = 0
    mixed_rows = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        header = cells(line) if line.startswith("|") else []
        is_shop = len(header) == 4 and header[0] == "Tier" and (
            "Shop" in header[1] or header[1] == "Haggling Merchant 1"
        )
        if not is_shop:
            output.append(line)
            index += 1
            continue

        table = []
        while index < len(lines) and lines[index].startswith("|"):
            table.append(cells(lines[index]))
            index += 1
        data_rows = [values for values in table[2:] if values and not is_separator(values)]
        equipment_rows = [values for values in data_rows if values[1] in eligibility]
        dedicated = bool(data_rows) and len(equipment_rows) == len(data_rows)

        if dedicated:
            dedicated_tables += 1
            output.append(row([header[0], header[1], header[2], "Equippable Classes", "Route Advice"]))
            output.append(row(["---", "---", "---:", "---", "---"]))
            for values in table[2:]:
                if is_separator(values):
                    continue
                output.append(row(values[:3] + [eligibility[values[1]], values[3]]))
                annotated_rows += 1
        else:
            output.append(row(header))
            output.append(row(table[1]))
            for values in table[2:]:
                if values[1] in eligibility:
                    values[3] = f"**Equippable:** {eligibility[values[1]]}. {values[3]}"
                    annotated_rows += 1
                    mixed_rows += 1
                output.append(row(values))

    guide_note = "- Shop equipment rows list every class permitted by the ROM's equip mask; sex-specific restrictions are called out separately from class eligibility."
    anchor = "- Shop recommendations use four tiers: **Required**, **High**, **Situational**, and **Skip**."
    if guide_note not in output:
        anchor_index = output.index(anchor)
        output.insert(anchor_index + 1, guide_note)

    if dedicated_tables != 18 or annotated_rows != 129 or mixed_rows != 10:
        raise RuntimeError(
            f"Unexpected shop coverage: {dedicated_tables=} {annotated_rows=} {mixed_rows=}"
        )
    GUIDE.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(
        f"Annotated {annotated_rows} equipment rows across {dedicated_tables} "
        f"equipment-only tables and {mixed_rows} mixed-shop rows"
    )


if __name__ == "__main__":
    main()
