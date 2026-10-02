# Changelog

## 0.2.0
Brings the CLI in line with the Squeeze app's sizing policy.
- 720p / 24 fps / 32 kbps floors (`--min-height`, `--min-fps`, `--min-audio-kbps`), audio cap and step-down, and a warning when a target can't be reached without going below them.
- Two-pass encoding (`--two-pass`) and hardware encoder selection (`--hw auto|nvenc|vaapi|qsv|amf`).
- GIF output (`--gif`) and `.gif` inputs, with the frame rate kept.
- Several inputs or directories in one run; user presets; repeated passes at the minimum bitrate are skipped.
- `--version`.

## 0.1.0
First release: ffmpeg-based port of Squeeze's size-target compression.
