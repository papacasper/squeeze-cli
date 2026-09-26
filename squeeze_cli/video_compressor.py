"""Bitrate/resolution ladder re-encode via ffmpeg, mirroring VideoCompressor.kt."""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_ATTEMPTS = 8
MIN_BITRATE = 100_000  # bits/sec
MAX_BITRATE = 20_000_000
HEIGHT_LADDER = [1080, 720, 540, 480, 360, 240]

MIN_AUDIO_BITRATE = 32_000
MAX_AUDIO_BITRATE = 128_000
AUDIO_SHARE_OF_TARGET = 0.10  # audio gets ~10% of the total budget, clamped to the range above
TARGET_FILL = 0.95  # aim slightly under the target; the rest absorbs container overhead


class EncodeError(RuntimeError):
    """ffmpeg/ffprobe failed; the message carries the tail of its stderr."""


@dataclass
class MediaInfo:
    duration_sec: float
    height: int
    has_audio: bool


def probe(source_path: str) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_entries", "format=duration:stream=height,codec_type",
            source_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise EncodeError(f"ffprobe could not read {source_path}: {_tail(result.stderr)}")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and "height" in s), None)
    if video is None:
        raise EncodeError(f"{source_path} has no video stream")

    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = 10.0
    return MediaInfo(
        duration_sec=max(duration, 1.0),
        height=int(video["height"]),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def audio_bitrate_for(target_bytes: int, duration_sec: float, has_audio: bool) -> int:
    if not has_audio:
        return 0
    total_bps = target_bytes * 8 / duration_sec
    return int(min(MAX_AUDIO_BITRATE, max(MIN_AUDIO_BITRATE, total_bps * AUDIO_SHARE_OF_TARGET)))


def initial_video_bitrate(target_bytes: int, duration_sec: float, audio_bps: int) -> int:
    video_bps = target_bytes * 8 * TARGET_FILL / duration_sec - audio_bps
    return int(min(MAX_BITRATE, max(MIN_BITRATE, video_bps)))


def next_video_bitrate(bitrate: int, pass_bytes: int, target_bytes: int, audio_bytes: float) -> int:
    """Scale the bitrate by how far the video portion of the last pass was from its budget."""
    if pass_bytes <= 0:
        return max(MIN_BITRATE, int(bitrate * 0.5))
    pass_video = max(pass_bytes - audio_bytes, pass_bytes * 0.1)
    target_video = max(target_bytes - audio_bytes, target_bytes * 0.1)
    return max(MIN_BITRATE, int(bitrate * (target_video / pass_video) * 0.85))


def compress_video(
    source_path: str,
    target_bytes: int,
    output_path: str,
    on_progress=lambda msg: None,
) -> str:
    info = probe(source_path)
    audio_bps = audio_bitrate_for(target_bytes, info.duration_sec, info.has_audio)
    audio_bytes = audio_bps * info.duration_sec / 8
    bitrate = initial_video_bitrate(target_bytes, info.duration_sec, audio_bps)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    codec = "libx265"
    best_path: Path | None = None
    best_bytes = float("inf")
    previous_pass_bytes = float("inf")
    ladder_index = 0

    # Temp passes live beside the output (same filesystem, so the final move is atomic) and are
    # removed on every exit path, including Ctrl-C.
    with tempfile.TemporaryDirectory(prefix=".squeeze-", dir=output.parent) as tmp:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            target_height = min(HEIGHT_LADDER[ladder_index], info.height)
            pass_path = Path(tmp) / f"pass{attempt}{output.suffix}"

            on_progress(
                f"Encoding pass {attempt}/{MAX_ATTEMPTS} "
                f"({bitrate // 1000} kbps, {target_height}p, {_codec_name(codec)})..."
            )
            try:
                _encode(source_path, pass_path, bitrate, audio_bps, target_height, info.height, codec)
            except EncodeError as first_error:
                if codec != "libx265":
                    if best_path is not None:
                        break
                    raise
                on_progress(f"HEVC encode failed, switching to H.264 ({_first_line(first_error)})")
                codec = "libx264"
                try:
                    _encode(source_path, pass_path, bitrate, audio_bps, target_height, info.height, codec)
                except EncodeError:
                    if best_path is not None:
                        break
                    raise

            pass_bytes = pass_path.stat().st_size if pass_path.exists() else 0
            if pass_bytes <= 0:
                if best_path is not None:
                    break
                raise EncodeError("ffmpeg produced no output")

            if pass_bytes < best_bytes:
                if best_path is not None:
                    best_path.unlink(missing_ok=True)
                best_path = pass_path
                best_bytes = pass_bytes
            else:
                pass_path.unlink(missing_ok=True)

            if pass_bytes <= target_bytes:
                break

            # If the last resolution step barely moved the needle, the bitrate request is
            # likely already near-optimal for this resolution — escalate downscaling instead.
            if previous_pass_bytes not in (float("inf"), 0):
                shrink_ratio = pass_bytes / previous_pass_bytes
                if attempt > 1 and shrink_ratio > 0.9 and ladder_index < len(HEIGHT_LADDER) - 1:
                    ladder_index += 1
            previous_pass_bytes = pass_bytes

            if bitrate <= MIN_BITRATE and ladder_index == len(HEIGHT_LADDER) - 1:
                on_progress("Reached minimum bitrate and resolution; can't shrink further.")
                break

            bitrate = next_video_bitrate(bitrate, pass_bytes, target_bytes, audio_bytes)

        if best_path is None:
            raise EncodeError("Video compression failed to produce output")
        best_path.replace(output)

    return str(output)


def _encode(source_path, pass_path: Path, bitrate: int, audio_bps: int,
            target_height: int, original_height: int, codec: str) -> None:
    # Explicit maps keep the first video + first audio track only. Without them, ffmpeg's
    # default stream selection can drag in subtitle/data streams the MP4 muxer rejects.
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(source_path),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-c:v", codec, "-b:v", str(bitrate), "-pix_fmt", "yuv420p",
    ]
    if codec == "libx265":
        cmd += ["-tag:v", "hvc1"]  # Apple/QuickTime and most players need this tag for HEVC-in-MP4
    if target_height < original_height:
        cmd += ["-vf", f"scale=-2:{target_height}"]
    if audio_bps:
        cmd += ["-c:a", "aac", "-b:a", str(audio_bps)]
    cmd += ["-movflags", "+faststart", str(pass_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise EncodeError(f"ffmpeg failed: {_tail(result.stderr)}")


def _codec_name(codec: str) -> str:
    return "H.265" if codec == "libx265" else "H.264"


def _tail(text: str, lines: int = 5) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:]) or "(no output)"


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0]
