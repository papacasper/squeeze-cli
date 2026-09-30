"""Pure sizing policy, mirroring BitrateMath.kt in the Android app (no ffmpeg, no I/O)."""

from dataclasses import dataclass

MIN_BITRATE = 100_000  # bits/sec
MAX_BITRATE = 20_000_000
TARGET_FILL = 0.92  # aim under the target; the rest absorbs container overhead
SOURCE_FILL = 0.8  # a source already under target must shrink, so budget at most this share of it
MAX_AUDIO_SHARE = 0.35
MIN_BITS_PER_PIXEL = 0.04
ASSUMED_FPS = 30.0
FALLBACK_AUDIO_BITRATE = 128_000
AUDIO_START_FLOOR = 64_000  # audio is first capped no lower than this
AUDIO_STEPS = (64_000, 48_000, 32_000)  # then stepped down these when video is already at its floor
FULL_LADDER = (1080, 720, 540, 480, 360, 240)


@dataclass(frozen=True)
class Floors:
    """The lowest quality the user accepts; defaults match the app."""
    min_height: int = 720
    min_fps: float = 24.0
    min_audio: int = 32_000

    def ladder(self) -> list[int]:
        rungs = [h for h in FULL_LADDER if h > self.min_height]
        return rungs + [self.min_height]

    def audio_steps(self) -> list[int]:
        return [s for s in AUDIO_STEPS if s >= self.min_audio]


def initial_video_bitrate(target_bytes: int, duration_sec: float, audio_bytes: float,
                          source_bytes: float = float("inf")) -> int:
    budget = min(target_bytes * TARGET_FILL, source_bytes * SOURCE_FILL)
    return int(min(MAX_BITRATE, max(MIN_BITRATE, (budget - audio_bytes) * 8 / duration_sec)))


def next_video_bitrate(bitrate: int, pass_bytes: int, target_bytes: int, audio_bytes: float) -> int:
    """Scale the bitrate by how far the video portion of the last pass was from its budget."""
    if pass_bytes <= 0:
        return max(MIN_BITRATE, int(bitrate * 0.5))
    pass_video = max(pass_bytes - audio_bytes, pass_bytes * 0.1)
    target_video = max(target_bytes - audio_bytes, target_bytes * 0.1)
    return max(MIN_BITRATE, int(bitrate * (target_video / pass_video) * 0.85))


def _rung_pixels(source_pixels: int, source_height: int, rung: int) -> float:
    return source_pixels * rung * rung / (source_height * source_height)


def starved_at(bitrate: int, source_pixels: int, source_height: int, rung: int) -> bool:
    """True when frames at `rung` would get under MIN_BITS_PER_PIXEL at the assumed frame rate."""
    if source_pixels <= 0 or source_height <= 0:
        return False
    return _rung_pixels(source_pixels, source_height, rung) * ASSUMED_FPS > bitrate / MIN_BITS_PER_PIXEL


def starting_ladder_index(bitrate: int, source_pixels: int, source_height: int, ladder: list[int]) -> int:
    """First rung whose frames still get MIN_BITS_PER_PIXEL, else the last rung."""
    for i, rung in enumerate(ladder):
        if not starved_at(bitrate, source_pixels, source_height, rung):
            return i
    return len(ladder) - 1


def audio_bitrate(source_bps: int, target_bytes: int, duration_sec: float) -> int:
    """Bitrate to encode audio at: the source's own, capped to MAX_AUDIO_SHARE of the budget. 0 = no audio."""
    if source_bps <= 0:
        return 0
    share = int(target_bytes * TARGET_FILL * MAX_AUDIO_SHARE * 8 / duration_sec)
    return min(source_bps, max(AUDIO_START_FLOOR, share))


def next_lower_audio(current: int, floors: Floors = Floors()) -> int | None:
    """Next step down below `current`, or None when at the floor or there's no audio."""
    if current <= 0:
        return None
    return next((s for s in floors.audio_steps() if s < current), None)


@dataclass(frozen=True)
class Assessment:
    level: str  # "ok" | "rough" | "unreachable"
    min_bytes: int
    video_bitrate: int


def assess(target_bytes: int, duration_sec: float, source_audio_bps: int, source_pixels: int,
           source_height: int, source_bytes: float = float("inf"), floors: Floors = Floors()) -> Assessment:
    dur = max(duration_sec, 1.0)
    steps = floors.audio_steps()
    lowest_audio = 0 if source_audio_bps <= 0 else min(source_audio_bps, steps[-1] if steps else floors.min_audio)
    min_bytes = int((MIN_BITRATE + lowest_audio) * dur / 8)
    audio_bps = audio_bitrate(source_audio_bps, target_bytes, dur)
    video_bps = initial_video_bitrate(target_bytes, dur, audio_bps * dur / 8, source_bytes)
    if min_bytes > target_bytes * TARGET_FILL:
        level = "unreachable"
    elif source_bytes * SOURCE_FILL < target_bytes * TARGET_FILL:
        level = "ok"  # the source's own size is the limit, not the target
    elif starved_at(video_bps, source_pixels, source_height, min(floors.min_height, source_height)):
        level = "rough"
    else:
        level = "ok"
    return Assessment(level, min_bytes, video_bps)
