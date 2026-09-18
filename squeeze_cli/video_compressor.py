"""Bitrate/resolution ladder re-encode via ffmpeg, mirroring VideoCompressor.kt."""

import json
import subprocess
import sys
from pathlib import Path

MAX_ATTEMPTS = 8
MIN_BITRATE = 100_000  # bits/sec
HEIGHT_LADDER = [1080, 720, 540, 480, 360, 240]


def probe(source_path: str) -> tuple[float, int]:
    """Returns (duration_seconds, height)."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_entries", "format=duration:stream=height,codec_type",
            source_path,
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    duration = float(data.get("format", {}).get("duration", 10.0)) or 10.0
    height = 1080
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and "height" in stream:
            height = int(stream["height"])
            break
    return max(duration, 1.0), height


def compress_video(
    source_path: str,
    target_bytes: int,
    output_path: str,
    on_progress=lambda msg: None,
) -> str:
    duration_sec, original_height = probe(source_path)

    # Reserve ~12% of the target for audio + container overhead, matching the app.
    video_target_bits = int(target_bytes * 8 * 0.88 / duration_sec)
    bitrate = max(MIN_BITRATE, min(video_target_bits, 20_000_000))

    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    best_path = None
    best_bytes = float("inf")
    previous_pass_bytes = float("inf")
    ladder_index = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        target_height = min(HEIGHT_LADDER[min(ladder_index, len(HEIGHT_LADDER) - 1)], original_height)
        codec = "libx265"
        pass_path = out_dir / f"pass{attempt}_{Path(output_path).name}"

        on_progress(
            f"Encoding pass {attempt}/{MAX_ATTEMPTS} (target {bitrate // 1000} kbps, {target_height}p)..."
        )
        try:
            _encode(source_path, pass_path, bitrate, target_height, original_height, codec)
        except subprocess.CalledProcessError:
            # Hardware/codec issue with HEVC — retry this pass with H.264.
            on_progress(f"HEVC pass failed, retrying pass {attempt} with H.264...")
            try:
                _encode(source_path, pass_path, bitrate, target_height, original_height, "libx264")
            except subprocess.CalledProcessError:
                pass_path.unlink(missing_ok=True)
                if best_path is not None:
                    break
                raise

        if not pass_path.exists():
            if best_path is not None:
                break
            raise RuntimeError("ffmpeg produced no output")

        pass_bytes = pass_path.stat().st_size

        if 0 < pass_bytes < best_bytes:
            if best_path is not None:
                Path(best_path).unlink(missing_ok=True)
            best_path = pass_path
            best_bytes = pass_bytes
        else:
            pass_path.unlink(missing_ok=True)

        if 0 < pass_bytes <= target_bytes:
            break

        # If the last resolution step barely moved the needle, the bitrate request is
        # likely already near-optimal for this resolution — escalate downscaling instead.
        shrink_ratio = (
            pass_bytes / previous_pass_bytes if previous_pass_bytes not in (float("inf"), 0) else 0.0
        )
        if attempt > 1 and shrink_ratio > 0.9 and ladder_index < len(HEIGHT_LADDER) - 1:
            ladder_index += 1
        previous_pass_bytes = pass_bytes

        if bitrate <= MIN_BITRATE and ladder_index == len(HEIGHT_LADDER) - 1:
            on_progress("Reached minimum bitrate and resolution; can't shrink further.")
            break

        ratio = target_bytes / pass_bytes if pass_bytes > 0 else 0.5
        bitrate = max(MIN_BITRATE, int(bitrate * ratio * 0.85))

    if best_path is None:
        raise RuntimeError("Video compression failed to produce output")

    if str(best_path) != output_path:
        Path(best_path).replace(output_path)
    return output_path


def _encode(source_path, pass_path, bitrate: int, target_height: int, original_height: int, codec: str):
    pass_path = Path(pass_path)
    if pass_path.exists():
        pass_path.unlink()

    cmd = ["ffmpeg", "-y", "-i", str(source_path), "-c:v", codec, "-b:v", str(bitrate)]
    if target_height < original_height:
        cmd += ["-vf", f"scale=-2:{target_height}"]
    cmd += ["-c:a", "aac", "-b:a", "128k", str(pass_path)]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
