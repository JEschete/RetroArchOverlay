import re
from pathlib import Path


def supported_cores_for_console(console_name: str, retroarch_root: Path | None = None) -> tuple[str, ...]:
    console_aliases = _name_aliases(console_name)
    cores = set(console_aliases)
    if retroarch_root is None:
        return tuple(sorted(cores))
    info_root = retroarch_root / "info"
    if not info_root.is_dir():
        return tuple(sorted(cores))
    for path in info_root.glob("*.info"):
        fields = _read_info(path)
        system_aliases = set()
        for key in ("systemname", "database"):
            system_aliases.update(_name_aliases(fields.get(key, "")))
        if not console_aliases.intersection(system_aliases):
            continue
        cores.add(path.stem.removesuffix("_libretro").casefold())
        for key in ("corename", "display_name"):
            value = _normalize(fields.get(key, ""))
            if value:
                cores.add(value)
    return tuple(sorted(cores))


def set_network_commands_enabled(
    config_path: Path, enabled: bool, port: int = 55355
) -> bool:
    if not 1 <= port <= 65_535:
        raise ValueError("RetroArch network command port must be between 1 and 65535")
    path = config_path.expanduser().resolve()
    text = path.read_text(encoding="utf-8", errors="replace")
    updated = _set_config_value(
        text, "network_cmd_enable", "true" if enabled else "false"
    )
    updated = _set_config_value(updated, "network_cmd_port", str(port))
    if updated == text:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(path)
    return True


def network_commands_enabled(config_path: Path, port: int = 55355) -> bool:
    if not config_path.is_file():
        return False
    fields = _read_config(config_path)
    return (
        fields.get("network_cmd_enable", "").casefold() == "true"
        and fields.get("network_cmd_port") == str(port)
    )


def _read_info(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fields
    for line in lines:
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip().casefold()] = value.strip().strip('"')
    return fields


def _read_config(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fields
    for line in lines:
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip().casefold()] = value.strip().strip('"')
    return fields


def _set_config_value(text: str, key: str, value: str) -> str:
    line_pattern = re.compile(
        rf"^(?P<indent>\s*){re.escape(key)}\s*=.*$", re.MULTILINE
    )
    replacement = rf'\g<indent>{key} = "{value}"'
    if line_pattern.search(text):
        return line_pattern.sub(replacement, text, count=1)
    separator = "" if not text or text.endswith(("\n", "\r")) else "\n"
    return f'{text}{separator}{key} = "{value}"\n'


def _name_aliases(value: str) -> frozenset[str]:
    aliases: set[str] = set()
    for part in re.split(r"[/|,;-]+", value):
        words = re.findall(r"[a-z0-9]+", part.casefold())
        if not words:
            continue
        aliases.add("_".join(words))
        if len(words) > 1:
            aliases.add("".join(word[0] for word in words))
    normalized = _normalize(value)
    if normalized:
        aliases.add(normalized)
    return frozenset(aliases)


def _normalize(value: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", value.casefold()))