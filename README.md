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
```

Presets: `discord-free` (20MB), `discord-basic` (50MB), `discord-nitro` (500MB), `email` (20MB), `text` (100MB), `whatsapp` (2GB), `telegram` (2GB). Or pass any size like `25MB`, `500KB`, `2GB`.

## How it works

- **Images**: JPEG quality binary search (2-95), falls back to downscaling 30% per round if quality=2 still exceeds target. Respects EXIF orientation.
- **Video**: re-encodes via ffmpeg (`libx265`, falling back to `libx264` on failure), retrying up to 8 passes with progressively lower bitrate, and stepping resolution down a ladder (1080p → 720p → 540p → 480p → 360p → 240p) if bitrate reduction alone stops helping.

Same size-target logic as the Squeeze Android app — see `squeeze_cli/video_compressor.py` and `image_compressor.py`.

## License

MIT
