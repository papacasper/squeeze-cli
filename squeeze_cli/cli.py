import argparse
import shutil
import sys
from pathlib import Path

from .gif_compressor import compress_gif
from .image_compressor import compress_image
from .targets import TARGETS, load_user_presets, presets_path, resolve_target_bytes
from .policy import Floors
from .video_compressor import HW_BACKENDS, EncodeError, compress_video
from . import __version__

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
# Output containers we can mux H.265/H.264 + AAC into. Input ext doesn't matter (.webm/.avi -> .mp4).
VIDEO_OUT_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
IMAGE_OUT_EXTS = {".jpg", ".jpeg"}  # the image path always emits JPEG
GIF_OUT_EXTS = {".gif"}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="squeeze",
        description="Compress images or videos on-device to fit a target size.",
    )
    parser.add_argument("--version", action="version", version=f"squeeze {__version__}")
    parser.add_argument("inputs", nargs="*", metavar="input", help="image/video files or directories")
    parser.add_argument(
        "-t", "--target",
        default="discord-free",
        help="size target: a preset name (see --list-presets) or a size like 25MB (default: discord-free)",
    )
    parser.add_argument(
        "-o", "--output",
        help="output file (single input) or output directory (several inputs / a directory); "
             "default: <input>-squeezed.jpg for images, .mp4 for video, beside the input",
    )
    parser.add_argument("-f", "--force", action="store_true", help="re-encode even if already under target")
    parser.add_argument("-r", "--recursive", action="store_true", help="descend into subdirectories")
    parser.add_argument(
        "--hw", default="none", choices=["none", "auto", *HW_BACKENDS],
        help="hardware video encoder (faster, less size-efficient): auto picks the first that works (default: none)",
    )
    parser.add_argument(
        "--two-pass", action="store_true",
        help="two-pass software encoding: slower per attempt, lands closer to the target in fewer attempts",
    )
    parser.add_argument(
        "--gif", action="store_true",
        help="write videos as GIFs (first 30 s, frame rate kept, width shrinks to fit); .gif inputs are always compressed as GIFs",
    )
    parser.add_argument("--min-height", type=int, default=720, metavar="PX",
                        help="never scale video below this height (default: 720)")
    parser.add_argument("--min-fps", type=float, default=24, metavar="FPS",
                        help="never drop video below this frame rate (default: 24)")
    parser.add_argument("--min-audio-kbps", type=int, default=32, metavar="KBPS",
                        help="lowest audio bitrate to step down to (default: 32)")
    parser.add_argument("--list-presets", action="store_true", help="show built-in and user presets, then exit")
    args = parser.parse_args()

    if args.list_presets:
        return _list_presets()
    if not args.inputs:
        parser.error("no input given")

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("error: ffmpeg/ffprobe not found on PATH", file=sys.stderr)
        return 1

    try:
        target_bytes = resolve_target_bytes(args.target)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.min_height < 144 or args.min_fps <= 0 or args.min_audio_kbps < 8:
        print("error: --min-height/--min-fps/--min-audio-kbps out of range", file=sys.stderr)
        return 1
    floors = Floors(args.min_height, args.min_fps, args.min_audio_kbps * 1000)

    sources, missing = _collect_sources(args.inputs, args.recursive)
    for m in missing:
        print(f"error: {m} does not exist", file=sys.stderr)
    if not sources:
        if not missing:
            print("error: no supported image or video files found", file=sys.stderr)
        return 1

    batch = len(sources) > 1 or any(Path(i).is_dir() for i in args.inputs)
    out_dir = None
    if batch and args.output:
        out_dir = Path(args.output)
        if out_dir.exists() and not out_dir.is_dir():
            print(f"error: -o must be a directory for batch input (got file {out_dir})", file=sys.stderr)
            return 1

    worst = 1 if missing else 0
    try:
        for i, source in enumerate(sources, 1):
            if batch:
                print(f"[{i}/{len(sources)}] {source}")
            output = (out_dir / _default_name(source, args.gif)) if out_dir else (Path(args.output) if args.output else None)
            worst = max(worst, _process(source, target_bytes, output, args.force, args.hw, args.two_pass, args.gif, floors))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return worst


def _list_presets() -> int:
    try:
        user = load_user_presets()
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for name, size in {**TARGETS, **user}.items():
        print(f"{name:<16}{_human(size)}{'  (user)' if name in user else ''}")
    print(f"\nuser presets: {presets_path()}")
    return 0


def _kind(path: Path, gif: bool = False):
    ext = path.suffix.lower()
    if ext == ".gif" or (gif and ext in VIDEO_EXTS):
        return "gif", ".gif", GIF_OUT_EXTS
    if ext in IMAGE_EXTS:
        return "image", ".jpg", IMAGE_OUT_EXTS
    if ext in VIDEO_EXTS:
        return "video", ".mp4", VIDEO_OUT_EXTS
    return None


def _default_name(source: Path, gif: bool = False) -> str:
    return f"{source.stem}-squeezed{_kind(source, gif)[1]}"


def _collect_sources(inputs, recursive):
    """Expand directories into their supported files (skipping earlier *-squeezed outputs)."""
    sources, missing = [], []
    for raw in inputs:
        path = Path(raw)
        if not path.exists():
            missing.append(path)
        elif path.is_dir():
            walker = path.rglob("*") if recursive else path.iterdir()
            sources += sorted(
                p for p in walker
                if p.is_file() and _kind(p) and not p.stem.endswith("-squeezed") and not p.name.startswith(".")
            )
        else:
            sources.append(path)
    return sources, missing


def _process(source: Path, target_bytes: int, output: Path | None, force: bool,
             hw: str = "none", two_pass: bool = False, gif: bool = False, floors: Floors = Floors()) -> int:
    """Compress one file. Returns 0 ok, 1 error, 2 still over target."""
    info = _kind(source, gif)
    if info is None:
        print(f"error: unsupported file type '{source.suffix.lower()}'", file=sys.stderr)
        return 1
    kind, _default_ext, allowed = info

    if output is None:
        output = source.with_name(_default_name(source, gif))
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
    converting = kind == "gif" and source.suffix.lower() != ".gif"  # video -> GIF is a format change, never a no-op
    if source_size <= target_bytes and not force and not converting:
        print(f"{source.name} is already under target ({_human(source_size)} <= {_human(target_bytes)}); nothing to do (use --force to re-encode)")
        return 0

    try:
        print(f"Compressing {kind} to fit {_human(target_bytes)}...")
        if kind == "gif":
            compress_gif(str(source), target_bytes, str(output), on_progress=print)
        elif kind == "image":
            output.parent.mkdir(parents=True, exist_ok=True)
            compress_image(str(source), target_bytes, str(output))
        else:
            compress_video(str(source), target_bytes, str(output), on_progress=print, hw=hw, two_pass=two_pass, floors=floors)
    except (EncodeError, OSError, ValueError) as e:  # PIL raises OSError on corrupt images
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
