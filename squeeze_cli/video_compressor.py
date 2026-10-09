"""Bitrate/resolution ladder re-encode via ffmpeg, mirroring VideoCompressor.kt."""

import functools
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import policy
from .policy import MIN_BITRATE, Floors

MAX_ATTEMPTS = 8


HW_BACKENDS = ("nvenc", "vaapi", "qsv", "amf")  # probed in this order for --hw auto
VAAPI_DEVICE = "/dev/dri/renderD128"


class EncodeError(RuntimeError):
    """ffmpeg/ffprobe failed; the message carries the tail of its stderr."""


@dataclass
class MediaInfo:
    duration_sec: float
    height: int
    has_audio: bool
    width: int = 0
    fps: float = 30.0
    audio_bps: int = 0


def probe(source_path: str) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_entries", "format=duration:stream=width,height,codec_type,r_frame_rate,bit_rate",
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
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        audio_bps = int(audio.get("bit_rate")) if audio else 0
    except (TypeError, ValueError):
        audio_bps = policy.FALLBACK_AUDIO_BITRATE
    return MediaInfo(
        duration_sec=max(duration, 1.0),
        height=int(video["height"]),
        has_audio=audio is not None,
        width=int(video.get("width", 0)),
        fps=_parse_fps(video.get("r_frame_rate")),
        audio_bps=audio_bps or (policy.FALLBACK_AUDIO_BITRATE if audio else 0),
    )


def _parse_fps(text) -> float:
    try:
        num, _, den = str(text).partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 30.0


def _hw_args(encoder: str) -> list[str]:
    return ["-vaapi_device", VAAPI_DEVICE] if encoder.endswith("_vaapi") else []


@functools.lru_cache(maxsize=None)
def _hw_works(encoder: str) -> bool:
    """A listed hardware encoder isn't necessarily usable (no GPU/driver), so try a tiny encode."""
    vf = "format=nv12,hwupload" if encoder.endswith("_vaapi") else "format=yuv420p"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", *_hw_args(encoder),
        "-f", "lavfi", "-i", "testsrc2=s=256x144:d=0.2:r=10",
        "-vf", vf, "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_hw_encoder(hw: str) -> str | None:
    """Resolve --hw (none/auto/nvenc/vaapi/qsv/amf) to a working hevc_* encoder name, or None."""
    if hw == "none":
        return None
    backends = HW_BACKENDS if hw == "auto" else (hw,)
    for backend in backends:
        if _hw_works(f"hevc_{backend}"):
            return f"hevc_{backend}"
    if hw != "auto":
        raise EncodeError(f"hardware encoder '{hw}' is not available on this machine")
    return None


def encoder_chain(hw: str = "none") -> list[str]:
    """Encoders to try in order; a failing one falls through to the next."""
    chain = ["libx265", "libx264"]
    hw_encoder = pick_hw_encoder(hw)
    return [hw_encoder, *chain] if hw_encoder else chain


def compress_video(
    source_path: str,
    target_bytes: int,
    output_path: str,
    on_progress=lambda msg: None,
    hw: str = "none",
    two_pass: bool = False,
    floors: Floors = Floors(),
) -> str:
    info = probe(source_path)
    ladder = floors.ladder()
    audio_bps = policy.audio_bitrate(info.audio_bps, target_bytes, info.duration_sec)
    audio_bytes = audio_bps * info.duration_sec / 8
    source_bytes = Path(source_path).stat().st_size
    bitrate = policy.initial_video_bitrate(target_bytes, info.duration_sec, audio_bytes, source_bytes)
    pixels = info.width * info.height
    verdict = policy.assess(target_bytes, info.duration_sec, info.audio_bps, pixels, info.height,
                            source_bytes, floors)
    if verdict.level == "unreachable":
        on_progress(f"Warning: can't reach this size; the smallest possible is about {verdict.min_bytes // 1024 // 1024} MB "
                    f"at {floors.min_height}p / {floors.min_fps:g} fps. Trying anyway.")
    elif verdict.level == "rough":
        on_progress(f"Warning: will fit, but the video will look rough (about {verdict.video_bitrate // 1000} kbps).")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    chain = encoder_chain(hw)
    codec_index = 0
    codec = chain[0]
    best_path: Path | None = None
    best_bytes = float("inf")
    previous_pass_bytes = float("inf")
    ladder_index = policy.starting_ladder_index(bitrate, pixels, info.height, ladder)
    # Still starved at the chosen rung: cap the frame rate (a no-op for sources already at or below the floor).
    cap_fps = policy.starved_at(bitrate, pixels, info.height, min(ladder[ladder_index], info.height))

    # Temp passes live beside the output (same filesystem, so the final move is atomic) and are
    # removed on every exit path, including Ctrl-C.
    with tempfile.TemporaryDirectory(prefix=".squeeze-", dir=output.parent) as tmp:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            target_height = min(ladder[ladder_index], info.height)
            capped = cap_fps and info.fps > floors.min_fps
            fps_label = f", {floors.min_fps:g} fps" if capped else ""
            audio_label = f", audio {audio_bps // 1000} kbps" if audio_bps else ""
            pass_path = Path(tmp) / f"pass{attempt}{output.suffix}"

            while True:
                on_progress(
                    f"Encoding pass {attempt}/{MAX_ATTEMPTS} "
                    f"({bitrate // 1000} kbps, {target_height}p{fps_label}{audio_label}, {_codec_name(codec)})..."
                )
                try:
                    _encode(source_path, pass_path, bitrate, audio_bps, target_height, info.height,
                            codec, two_pass, Path(tmp) / "stats", floors.min_fps if capped else None)
                    break
                except EncodeError as error:
                    pass_path.unlink(missing_ok=True)  # ffmpeg can leave a truncated file behind
                    if best_path is not None:
                        break
                    if codec_index == len(chain) - 1:
                        raise
                    codec_index += 1
                    codec = chain[codec_index]
                    on_progress(f"Encoder failed, switching to {_codec_name(codec)} ({_first_line(error)})")
            if best_path is not None and not pass_path.exists():
                break

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
                if attempt > 1 and shrink_ratio > 0.9 and ladder_index < len(ladder) - 1:
                    ladder_index += 1
            previous_pass_bytes = pass_bytes

            if ladder_index == len(ladder) - 1:
                cap_fps = True  # out of resolution to give up
            if bitrate <= MIN_BITRATE and ladder_index == len(ladder) - 1 and (capped or info.fps <= floors.min_fps):
                lower = policy.next_lower_audio(audio_bps, floors)
                if lower is None:
                    on_progress("Reached minimum bitrate, resolution, frame rate and audio; can't shrink further.")
                    break
                audio_bps = lower
                audio_bytes = audio_bps * info.duration_sec / 8
                bitrate = policy.initial_video_bitrate(target_bytes, info.duration_sec, audio_bytes, source_bytes)
                previous_pass_bytes = float("inf")
                continue

            bitrate = policy.next_video_bitrate(bitrate, pass_bytes, target_bytes, audio_bytes)
            if bitrate == MIN_BITRATE and ladder_index < len(ladder) - 1:
                # Bitrate is floored, so another pass at this height would just repeat; drop a rung.
                ladder_index += 1

        if best_path is None:
            raise EncodeError("Video compression failed to produce output")
        best_path.replace(output)

    return str(output)


def _encode(source_path, pass_path: Path, bitrate: int, audio_bps: int,
            target_height: int, original_height: int, codec: str,
            two_pass: bool = False, stats: Path | None = None, cap_fps: float | None = None) -> None:
    hw = codec.startswith("hevc_") or codec.endswith("_vaapi")
    vaapi = codec.endswith("_vaapi")
    filters = []
    if target_height < original_height:
        filters.append(f"scale=-2:{target_height}")
    if cap_fps:
        filters.append(f"fps={cap_fps:g}")
    if vaapi:
        filters += ["format=nv12", "hwupload"]

    def command(extra: list[str], audio: bool, out: str) -> list[str]:
        # Explicit maps keep the first video + first audio track only. Without them, ffmpeg's
        # default stream selection can drag in subtitle/data streams the MP4 muxer rejects.
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *_hw_args(codec), "-i", str(source_path),
               "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
               "-c:v", codec, "-b:v", str(bitrate)]
        if not vaapi:
            cmd += ["-pix_fmt", "yuv420p"]
        if codec == "libx265" or codec.startswith("hevc_"):
            cmd += ["-tag:v", "hvc1"]  # Apple/QuickTime and most players need this tag for HEVC-in-MP4
        if filters:
            cmd += ["-vf", ",".join(filters)]
        cmd += extra
        if audio and audio_bps:
            cmd += ["-c:a", "aac", "-b:a", str(audio_bps)]
        return cmd + (["-movflags", "+faststart"] if audio else []) + [out]

    if two_pass and not hw and stats is not None:
        first, second = _two_pass_args(codec, stats)
        _run(command(first, False, "-")[:-1] + ["-an", "-f", "null", os.devnull])
        _run(command(second, True, str(pass_path)))
    else:
        _run(command([], True, str(pass_path)))


def _two_pass_args(codec: str, stats: Path) -> tuple[list[str], list[str]]:
    if codec == "libx265":
        return (["-x265-params", f"pass=1:stats={stats}"], ["-x265-params", f"pass=2:stats={stats}"])
    return (["-pass", "1", "-passlogfile", str(stats)], ["-pass", "2", "-passlogfile", str(stats)])


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise EncodeError(f"ffmpeg failed: {_tail(result.stderr)}")


def _codec_name(codec: str) -> str:
    if codec.startswith("hevc_"):
        return f"H.265 {codec.split('_')[1]}"
    return "H.265" if codec == "libx265" else "H.264"


def _tail(text: str, lines: int = 5) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:]) or "(no output)"


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0]
