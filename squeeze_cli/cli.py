import argparse
import shutil
import sys
from pathlib import Path

from .image_compressor import compress_image
from .targets import TARGETS, resolve_target_bytes
from .video_compressor import EncodeError, compress_video

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
# Output containers we can mux H.265/H.264 + AAC into. Input ext doesn't matter (.webm/.avi -> .mp4).
VIDEO_OUT_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
IMAGE_OUT_EXTS = {".jpg", ".jpeg"}  # the image path always emits JPEG


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
    parser.add_argument(
        "-o", "--output",
        help="output path (default: <input>-squeezed.jpg for images, .mp4 for video)",
    )
    parser.add_argument("-f", "--force", action="store_true", help="re-encode even if already under target")
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
    if ext in IMAGE_EXTS:
        kind, default_ext, allowed = "image", ".jpg", IMAGE_OUT_EXTS
    elif ext in VIDEO_EXTS:
        kind, default_ext, allowed = "video", ".mp4", VIDEO_OUT_EXTS
    else:
        print(f"error: unsupported file type '{ext}'", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else source.with_name(f"{source.stem}-squeezed{default_ext}")
    if output.suffix.lower() not in allowed:
        print(
            f"error: {kind} output must end in {', '.join(sorted(allowed))} (got '{output.suffix}')",
            file=sys.stderr,
        )
        return 1
    if output.exists() and output.resolve() == source.resolve():
        print("error: output path is the input file; refusing to overwrite it", file=sys.stderr)
        return 1

    source_size = source.stat().st_size
    if source_size <= target_bytes and not args.force:
        print(f"{source.name} is already under target ({_human(source_size)} <= {_human(target_bytes)}); nothing to do (use --force to re-encode)")
        return 0

    try:
        print(f"Compressing {kind} to fit {_human(target_bytes)}...")
        if kind == "image":
            compress_image(str(source), target_bytes, str(output))
        else:
            compress_video(str(source), target_bytes, str(output), on_progress=print)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except EncodeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:  # unreadable/corrupt image (PIL raises OSError), disk errors
        print(f"error: {e}", file=sys.stderr)
        return 1

    final_size = output.stat().st_size
    status = "OK" if final_size <= target_bytes else "still over target"
    print(f"Done: {output} ({_human(final_size)}, {status})")
    return 0 if final_size <= target_bytes else 2


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


if __name__ == "__main__":
    sys.exit(main())
