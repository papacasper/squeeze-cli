"""Named size targets, mirroring the Squeeze Android app's presets."""

TARGETS = {
    "discord-free": 20 * 1024 * 1024,
    "discord-basic": 50 * 1024 * 1024,
    "discord-nitro": 500 * 1024 * 1024,
    "email": 20 * 1024 * 1024,
    "text": 100 * 1024 * 1024,
    "whatsapp": 2 * 1024 * 1024 * 1024,
    "telegram": 2 * 1024 * 1024 * 1024,
}


def resolve_target_bytes(target: str) -> int:
    """Accepts a preset name (e.g. 'discord-free') or a size like '25MB' / '500KB' / '2GB'."""
    key = target.strip().lower()
    if key in TARGETS:
        return TARGETS[key]
    return _parse_size(target)


def _parse_size(text: str) -> int:
    text = text.strip().upper()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    for suffix, mult in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return int(float(number) * mult)
            except ValueError:
                break
    try:
        return int(text)
    except ValueError:
        raise ValueError(
            f"Could not parse size target '{text}'. Use a preset ({', '.join(TARGETS)}) "
            "or a size like 25MB, 500KB, 2GB."
        )
