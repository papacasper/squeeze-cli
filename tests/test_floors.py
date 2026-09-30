import json
import subprocess

from squeeze_cli.cli import main
from tests.conftest import needs_ffmpeg


def _stream(path, kind):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries",
         "stream=height,r_frame_rate,bit_rate", "-print_format", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["streams"][0]


@needs_ffmpeg
def test_floors_hold_and_audio_steps_down(monkeypatch, tmp_path, capsys):
    src = tmp_path / "hd.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=8:r=30",
         "-f", "lavfi", "-i", "sine=d=8", "-c:v", "libx264", "-b:v", "6M", "-c:a", "aac", "-b:a", "256k", str(src)],
        check=True,
    )
    monkeypatch.setattr("sys.argv", ["squeeze", str(src), "-t", "300KB", "-o", str(tmp_path / "out.mp4")])
    main()
    out = capsys.readouterr().out
    video = _stream(tmp_path / "out.mp4", "v:0")
    assert video["height"] >= 720
    num, den = video["r_frame_rate"].split("/")
    assert float(num) / float(den) >= 24 - 0.01
    assert "can't reach" in out or "look rough" in out
    assert "audio" in out
