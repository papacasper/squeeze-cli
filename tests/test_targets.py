import pytest

from squeeze_cli.targets import TARGETS, resolve_target_bytes


def test_presets_resolve():
    assert resolve_target_bytes("discord-free") == 20 * 1024**2
    assert resolve_target_bytes(" Discord-Nitro ") == TARGETS["discord-nitro"]


@pytest.mark.parametrize("text,expected", [
    ("25MB", 25 * 1024**2), ("500kb", 500 * 1024), ("2GB", 2 * 1024**3),
    ("1.5MB", int(1.5 * 1024**2)), ("1000", 1000), ("10 MB", 10 * 1024**2),
])
def test_sizes(text, expected):
    assert resolve_target_bytes(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "MB", "12XB"])
def test_bad_sizes(bad):
    with pytest.raises(ValueError):
        resolve_target_bytes(bad)
