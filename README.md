# squeeze-cli

Linux CLI companion to [Squeeze](https://github.com/papacasper/squeeze) — compresses an image or video to fit a chosen size target, on-device, no cloud.

## Install

Requires `ffmpeg`/`ffprobe` on PATH.

```bash
pip install -e .
```

## Usage

```bash
squeeze video.mp4 -t discord-free          # 20MB
squeeze photo.jpg -t 5MB
squeeze clip.mov -t whatsapp -o out.mp4
squeeze *.mp4 -t 25MB -o small/            # batch: several files, output into a directory
squeeze ~/Videos -r -t discord-free         # a directory (add -r to descend into subfolders)
squeeze --list-presets
```

Batch runs continue past failures; the exit code is the worst result (0 ok, 1 error, 2 still over target). Earlier `*-squeezed` outputs are skipped when scanning a directory.

Your own presets go in `~/.config/squeeze/presets.json` (or `$XDG_CONFIG_HOME/squeeze/`), overriding built-ins of the same name:

```json
{"tiny": "8MB", "forum": "4MB"}
```

Presets: `discord-free` (20MB), `discord-basic` (50MB), `discord-nitro` (500MB), `email` (20MB), `text` (100MB), `whatsapp` (2GB), `telegram` (2GB). Or pass any size like `25MB`, `500KB`, `2GB`.

## How it works

- **Images**: JPEG quality binary search (2-95), falls back to downscaling 30% per round if quality=2 still exceeds target. Respects EXIF orientation.
- **Video**: re-encodes via ffmpeg (`libx265`, falling back to `libx264` on failure), retrying up to 8 passes with progressively lower bitrate, and stepping resolution down a ladder (1080p → 720p → 540p → 480p → 360p → 240p) if bitrate reduction alone stops helping.

Same size-target logic as the Squeeze Android app — see `squeeze_cli/video_compressor.py` and `image_compressor.py`.

## License

MIT
