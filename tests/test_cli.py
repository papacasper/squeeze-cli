import subprocess

import pytest
from PIL import Image

from squeeze_cli.cli import main
from tests.conftest import needs_ffmpeg


def run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["squeeze", *map(str, argv)])
    return main()


def test_missing_input(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, tmp_path / "nope.mp4") == 1
    assert "does not exist" in capsys.readouterr().err


def test_unsupported_type(monkeypatch, tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    assert run(monkeypatch, f) == 1
    assert "unsupported" in capsys.readouterr().err


def test_bad_target(monkeypatch, tmp_path, capsys):
    f = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(f)
    assert run(monkeypatch, f, "-t", "banana") == 1


def test_under_target_is_noop(monkeypatch, tmp_path, capsys):
    f = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(f)
    assert run(monkeypatch, f, "-t", "20MB") == 0
    assert not (tmp_path / "a-squeezed.jpg").exists()
    assert "nothing to do" in capsys.readouterr().out


def test_force_reencodes_png_to_jpg(monkeypatch, tmp_path):
    f = tmp_path / "a.png"
    Image.new("RGB", (100, 100), "red").save(f)
    assert run(monkeypatch, f, "-t", "20MB", "--force") == 0
    assert Image.open(tmp_path / "a-squeezed.jpg").format == "JPEG"


def test_refuses_output_equal_input(monkeypatch, tmp_path, capsys):
    f = tmp_path / "a.jpg"
    Image.new("RGB", (100, 100)).save(f)
    assert run(monkeypatch, f, "-t", "1KB", "-o", f) == 1
    assert "refusing" in capsys.readouterr().err


def test_bad_output_extension(monkeypatch, tmp_path, capsys):
    f = tmp_path / "a.png"
    Image.new("RGB", (100, 100)).save(f)
    assert run(monkeypatch, f, "-t", "1KB", "-o", tmp_path / "x.png") == 1


@needs_ffmpeg
def test_video_fits_and_is_hvc1_faststart(monkeypatch, mp4, tmp_path):
    out = tmp_path / "out.mp4"
    target = 400 * 1024
    assert run(monkeypatch, mp4, "-t", f"{target}", "-o", out) == 0
    assert out.stat().st_size <= target
    tag = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_tag_string",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert tag in ("hvc1", "avc1")
    # faststart: moov atom precedes mdat
    data = out.read_bytes()
    assert data.find(b"moov") < data.find(b"mdat")


@needs_ffmpeg
def test_webm_input_and_no_leftover_temp(monkeypatch, webm, tmp_path):
    assert run(monkeypatch, webm, "-t", "300KB") == 0
    assert (tmp_path / "in-squeezed.mp4").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".squeeze-")]


@needs_ffmpeg
def test_silent_video(monkeypatch, mp4_silent, tmp_path):
    assert run(monkeypatch, mp4_silent, "-t", "300KB") == 0


@needs_ffmpeg
def test_corrupt_video_reports_error(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"junk" * 1000)
    assert run(monkeypatch, bad, "-t", "1KB") == 1
    assert "error:" in capsys.readouterr().err


@needs_ffmpeg
def test_impossible_target_exits_2(monkeypatch, mp4, tmp_path):
    assert run(monkeypatch, mp4, "-t", "1KB", "-o", tmp_path / "t.mp4") == 2


def test_batch_directory_writes_into_output_dir(monkeypatch, tmp_path, capsys):
    src = tmp_path / "in"
    src.mkdir()
    for n in ("a", "b"):
        Image.new("RGB", (100, 100), "red").save(src / f"{n}.png")
    (src / "notes.txt").write_text("skip me")
    out = tmp_path / "out"
    assert run(monkeypatch, src, "-t", "20MB", "--force", "-o", out) == 0
    assert sorted(p.name for p in out.iterdir()) == ["a-squeezed.jpg", "b-squeezed.jpg"]
    assert "[2/2]" in capsys.readouterr().out


def test_batch_skips_prior_outputs_and_recurses_only_on_request(monkeypatch, tmp_path):
    (tmp_path / "sub").mkdir()
    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    Image.new("RGB", (50, 50)).save(tmp_path / "sub" / "b.png")
    Image.new("RGB", (50, 50)).save(tmp_path / "old-squeezed.jpg")
    assert run(monkeypatch, tmp_path, "--force") == 0
    assert (tmp_path / "a-squeezed.jpg").exists()
    assert not (tmp_path / "sub" / "b-squeezed.jpg").exists()
    assert not (tmp_path / "old-squeezed-squeezed.jpg").exists()
    assert run(monkeypatch, tmp_path, "--force", "-r") == 0
    assert (tmp_path / "sub" / "b-squeezed.jpg").exists()


def test_batch_continues_after_failure_and_reports_worst(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    good = tmp_path / "good.png"
    Image.new("RGB", (50, 50)).save(good)
    assert run(monkeypatch, bad, good, "--force") == 1
    assert (tmp_path / "good-squeezed.jpg").exists()


def test_batch_output_must_be_directory(monkeypatch, tmp_path, capsys):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    for f in (a, b):
        Image.new("RGB", (50, 50)).save(f)
    afile = tmp_path / "file.jpg"
    afile.write_text("x")
    assert run(monkeypatch, a, b, "-o", afile) == 1


def test_user_preset_and_list(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "cfg"
    (cfg / "squeeze").mkdir(parents=True)
    (cfg / "squeeze" / "presets.json").write_text('{"tiny": "10KB"}')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    assert run(monkeypatch, "--list-presets") == 0
    assert "tiny" in capsys.readouterr().out
    f = tmp_path / "a.png"
    Image.new("RGB", (400, 400)).save(f)
    assert run(monkeypatch, f, "-t", "tiny", "--force") in (0, 2)


def test_bad_presets_file(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "cfg"
    (cfg / "squeeze").mkdir(parents=True)
    (cfg / "squeeze" / "presets.json").write_text("{nope")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    f = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(f)
    assert run(monkeypatch, f) == 1
    assert "bad presets file" in capsys.readouterr().err


@needs_ffmpeg
def test_two_pass_fits_target(monkeypatch, mp4, tmp_path):
    out = tmp_path / "tp.mp4"
    target = 400 * 1024
    assert run(monkeypatch, mp4, "-t", f"{target}", "--two-pass", "-o", out) == 0
    assert out.stat().st_size <= target
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".squeeze-")]


@needs_ffmpeg
def test_hw_auto_falls_back_or_fits(monkeypatch, mp4, tmp_path):
    out = tmp_path / "hw.mp4"
    target = 400 * 1024
    assert run(monkeypatch, mp4, "-t", f"{target}", "--hw", "auto", "-o", out) == 0
    assert out.stat().st_size <= target


@needs_ffmpeg
def test_hw_unavailable_backend_errors(monkeypatch, mp4, tmp_path, capsys):
    monkeypatch.setattr("squeeze_cli.video_compressor._hw_works", lambda enc: False)
    assert run(monkeypatch, mp4, "-t", "300KB", "--hw", "qsv") == 1
    assert "not available" in capsys.readouterr().err
