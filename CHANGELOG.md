# Changelog

## 0.2.1
- Fix: `--gif` failed with "Invalid cross-device link" when /tmp is a separate filesystem (tmpfs); GIF passes now live beside the output.
- Fix: inputs with the same name (`clip.mp4`, `clip.mov`) wrote the same `clip-squeezed.mp4`; later ones now get `-2`, `-3`...
- Fix: `.heic`/`.heif` images can be read (new dependency: pillow-heif).
- Fix: grayscale+alpha and other non-RGB images failed; transparency is now flattened onto white.
- Fix: a partial file from a failed ffmpeg pass could be kept as the result.

## 0.2.0
Brings the CLI in line with the Squeeze app's sizing policy.
- 720p / 24 fps / 32 kbps floors (`--min-height`, `--min-fps`, `--min-audio-kbps`), audio cap and step-down, and a warning when a target can't be reached without going below them.
- Two-pass encoding (`--two-pass`) and hardware encoder selection (`--hw auto|nvenc|vaapi|qsv|amf`).
- GIF output (`--gif`) and `.gif` inputs, with the frame rate kept.
- Several inputs or directories in one run; user presets; repeated passes at the minimum bitrate are skipped.
- `--version`.

## 0.1.0
First release: ffmpeg-based port of Squeeze's size-target compression.
