"""GIF output via ffmpeg palettegen/paletteuse, mirroring GifCompressor/VideoToGifConverter in the app.

The frame rate is never lowered to hit the size: only the width shrinks (and only the palette
and dither are what ffmpeg optimises), so motion stays as smooth as the source.
"""

import json
import math
import subprocess
import tempfile
from pathlib import Path

from .video_compressor import EncodeError, _run, _tail

MAX_ATTEMPTS = 8
MAX_VIDEO_SECONDS = 30      # video -> GIF clips are capped, as in the app
VIDEO_FPS = 30
START_WIDTH = 480           # video -> GIF starting width
MIN_WIDTH_VIDEO = 160
MIN_WIDTH_GIF = 120
MAX_SHRINK = 0.95           # always shrink by at least 5% per retry
SAFETY = 0.92               # aim a little under the target so one retry usually lands


def next_width(width: int, size: int, target: int, min_width: int) -> int:
    """Width for the next attempt, scaling area (~size) toward the target; even, never below min_width."""
    ratio = min(math.sqrt(target / size) * SAFETY, MAX_SHRINK)
    return max(int(width * ratio) // 2 * 2, min_width)


def _probe(path: str) -> tuple[int, float, float]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_entries", "stream=width,height,avg_frame_rate,codec_type:format=duration", path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise EncodeError(f"ffprobe could not read {path}: {_tail(r.stderr)}")
    data = json.loads(r.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video" and "width" in s), None)
    if video is None:
        raise EncodeError(f"{path} has no video stream")
    num, _, den = str(video.get("avg_frame_rate", "0/1")).partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    return int(video["width"]), fps, duration


def compress_gif(source_path: str, target_bytes: int, output_path: str, on_progress=print) -> str:
    """Write a GIF of `source_path` (a video or a GIF) at or under target_bytes; keeps the smallest try."""
    is_gif = Path(source_path).suffix.lower() == ".gif"
    src_width, src_fps, _ = _probe(source_path)
    if is_gif:
        fps = src_fps if src_fps > 0 else 15.0
        width, min_width = src_width, MIN_WIDTH_GIF
    else:
        fps = min(VIDEO_FPS, src_fps) if src_fps > 0 else VIDEO_FPS
        width, min_width = min(src_width, START_WIDTH), MIN_WIDTH_VIDEO
    width -= width % 2

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    best_size = None
    with tempfile.TemporaryDirectory(prefix="squeeze-gif-") as tmp:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            on_progress(f"GIF pass {attempt}/{MAX_ATTEMPTS} ({width}px wide, {fps:g} fps)...")
            candidate = Path(tmp) / f"pass{attempt}.gif"
            _encode(source_path, candidate, width, fps, limit_seconds=not is_gif)
            size = candidate.stat().st_size
            if best_size is None or size < best_size:
                best_size = size
                candidate.replace(out)
            if size <= target_bytes or width <= min_width:
                break
            width = next_width(width, size, target_bytes, min_width)
    return str(out)


def _encode(source: str, dest: Path, width: int, fps: float, limit_seconds: bool) -> None:
    graph = (
        f"fps={fps:g},scale={width}:-2:flags=lanczos,split[a][b];"
        "[a]palettegen=stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", source]
    if limit_seconds:
        cmd += ["-t", str(MAX_VIDEO_SECONDS)]
    cmd += ["-filter_complex", graph, "-loop", "0", str(dest)]
    _run(cmd)
