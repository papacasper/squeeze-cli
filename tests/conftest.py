import shutil
import subprocess

import pytest

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def _make_video(path, fmt_args, seconds=6, audio=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=640x360:d={seconds}:r=25"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=d={seconds}"]
    subprocess.run(cmd + fmt_args + [str(path)], check=True)
    return path


@pytest.fixture
def mp4(tmp_path):
    return _make_video(tmp_path / "in.mp4", ["-c:v", "libx264", "-b:v", "2M", "-c:a", "aac"])


@pytest.fixture
def mp4_silent(tmp_path):
    return _make_video(tmp_path / "silent.mp4", ["-c:v", "libx264", "-b:v", "2M"], audio=False)


@pytest.fixture
def webm(tmp_path):
    return _make_video(tmp_path / "in.webm", ["-c:v", "libvpx", "-b:v", "2M"], audio=False)
