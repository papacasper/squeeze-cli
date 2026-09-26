"""Named size targets, mirroring the Squeeze Android app's presets, plus user-defined ones."""

import json
import os
from pathlib import Path

TARGETS = {
    "discord-free": 20 * 1024 * 1024,
    "discord-basic": 50 * 1024 * 1024,
    "discord-nitro": 500 * 1024 * 1024,
    "email": 20 * 1024 * 1024,
    "text": 100 * 1024 * 1024,
    "whatsapp": 2 * 1024 * 1024 * 1024,
    "telegram": 2 * 1024 * 1024 * 1024,
}


def presets_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "squeeze" / "presets.json"


def load_user_presets() -> dict[str, int]:
    """Reads {"name": "size"} from presets.json; a missing file means no user presets."""
    path = presets_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
        return {str(k).strip().lower(): _parse_size(str(v)) for k, v in raw.items()}
    except (ValueError, OSError) as e:  # JSONDecodeError is a ValueError
        raise ValueError(f"bad presets file {path}: {e}")


def all_targets() -> dict[str, int]:
    """Built-ins overridden by user presets."""
    return {**TARGETS, **load_user_presets()}


def resolve_target_bytes(target: str) -> int:
    """Accepts a preset name (built-in or from presets.json) or a size like '25MB' / '500KB' / '2GB'."""
    key = target.strip().lower()
    targets = all_targets()
    if key in targets:
        return targets[key]
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
