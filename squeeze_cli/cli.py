import argparse
import shutil
import sys
from pathlib import Path

from .image_compressor import compress_image
from .targets import TARGETS, resolve_target_bytes
from .video_compressor import compress_video

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="squeeze",
        description="Compress an image or video on-device to fit a target size.",
    )
    parser.add_argument("input", help="path to the source image or video")
    parser.add_argument(
        "-t", "--target",
        default="discord-free",
        help=f"size target: preset ({', '.join(TARGETS)}) or a size like 25MB (default: discord-free)",
    )
    parser.add_argument("-o", "--output", help="output path (default: <input>-squeezed<ext>)")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 1

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("error: ffmpeg/ffprobe not found on PATH", file=sys.stderr)
        return 1

    try:
        target_bytes = resolve_target_bytes(args.target)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    ext = source.suffix.lower()
    output = Path(args.output) if args.output else source.with_name(f"{source.stem}-squeezed{source.suffix}")

    if source.stat().st_size <= target_bytes:
        print(f"{source.name} is already under target ({_human(source.stat().st_size)} <= {_human(target_bytes)})")

    if ext in IMAGE_EXTS:
        print(f"Compressing image to fit {_human(target_bytes)}...")
        compress_image(str(source), target_bytes, str(output))
    elif ext in VIDEO_EXTS:
        print(f"Compressing video to fit {_human(target_bytes)}...")
        compress_video(str(source), target_bytes, str(output), on_progress=print)
    else:
        print(f"error: unsupported file type '{ext}'", file=sys.stderr)
        return 1

    final_size = output.stat().st_size
    status = "OK" if final_size <= target_bytes else "still over target"
    print(f"Done: {output} ({_human(final_size)}, {status})")
    return 0


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


if __name__ == "__main__":
    sys.exit(main())
