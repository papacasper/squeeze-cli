import subprocess

from tests.conftest import needs_ffmpeg
from squeeze_cli.cli import main
from squeeze_cli.gif_compressor import MAX_SHRINK, next_width


def run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["squeeze", *map(str, args)])
    return main()


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,avg_frame_rate",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    codec, width, rate = out.split(",")
    num, den = rate.split("/")
    return codec, int(width), float(num) / float(den)


def test_next_width_shrinks_at_least_five_percent_and_stays_even():
    assert next_width(480, 1_010_000, 1_000_000, 160) <= int(480 * MAX_SHRINK) // 2 * 2
    assert next_width(480, 1_010_000, 1_000_000, 160) % 2 == 0
    assert next_width(480, 4_000_000, 1_000_000, 160) % 2 == 0
    assert next_width(200, 10_000_000, 1_000, 160) == 160


@needs_ffmpeg
def test_video_to_gif_keeps_frame_rate_and_fits(monkeypatch, mp4_silent, tmp_path):
    out = tmp_path / "out.gif"
    assert run(monkeypatch, mp4_silent, "--gif", "-t", "2MB", "-o", out) == 0
    codec, width, fps = _probe(out)
    assert codec == "gif" and width <= 480
    assert fps >= 24  # the source is 25 fps; shrinking must not drop frames
    assert out.stat().st_size <= 2 * 1024 * 1024


@needs_ffmpeg
def test_gif_input_is_compressed_as_gif_by_default(monkeypatch, mp4_silent, tmp_path):
    big = tmp_path / "big.gif"
    assert run(monkeypatch, mp4_silent, "--gif", "-t", "5MB", "-o", big) == 0
    small = tmp_path / "small.gif"
    assert run(monkeypatch, big, "-t", "300KB", "-f", "-o", small) in (0, 2)
    assert small.stat().st_size < big.stat().st_size
    assert _probe(small)[0] == "gif"


@needs_ffmpeg
def test_gif_flag_rejects_non_gif_output_name(monkeypatch, mp4_silent, tmp_path, capsys):
    assert run(monkeypatch, mp4_silent, "--gif", "-o", tmp_path / "x.mp4") == 1
    assert "must end in .gif" in capsys.readouterr().err


@needs_ffmpeg
def test_gif_temp_files_live_beside_the_output(monkeypatch, mp4_silent, tmp_path):
    # Passes used to be built in the system temp dir and moved, which fails across filesystems
    # (tmpfs /tmp -> /home). With the system temp dir unusable, the GIF must still be written.
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "no-such-dir"))
    out = tmp_path / "out" / "clip.gif"
    assert run(monkeypatch, mp4_silent, "--gif", "-t", "2MB", "-o", out) == 0
    assert out.exists()
    assert [p.name for p in out.parent.iterdir()] == ["clip.gif"]
