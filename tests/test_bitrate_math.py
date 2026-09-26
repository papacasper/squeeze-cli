from squeeze_cli.video_compressor import (
    MAX_AUDIO_BITRATE, MAX_BITRATE, MIN_AUDIO_BITRATE, MIN_BITRATE,
    audio_bitrate_for, initial_video_bitrate, next_video_bitrate,
)


def test_no_audio_means_zero():
    assert audio_bitrate_for(10_000_000, 60, has_audio=False) == 0


def test_audio_clamped():
    assert audio_bitrate_for(1_000, 600, True) == MIN_AUDIO_BITRATE
    assert audio_bitrate_for(2 * 1024**3, 60, True) == MAX_AUDIO_BITRATE


def test_initial_bitrate_leaves_room_for_audio_and_clamps():
    target, dur = 20 * 1024**2, 60
    audio = audio_bitrate_for(target, dur, True)
    video = initial_video_bitrate(target, dur, audio)
    assert MIN_BITRATE <= video < target * 8 / dur - audio
    assert initial_video_bitrate(1_000, 600, 32_000) == MIN_BITRATE
    assert initial_video_bitrate(2 * 1024**3, 1, 0) == MAX_BITRATE


def test_next_bitrate_shrinks_when_over_and_never_below_min():
    lowered = next_video_bitrate(1_000_000, pass_bytes=30_000_000, target_bytes=20_000_000, audio_bytes=1_000_000)
    assert lowered < 1_000_000
    assert next_video_bitrate(MIN_BITRATE, 1_000_000_000, 1_000, 0) == MIN_BITRATE
    assert next_video_bitrate(500_000, 0, 1_000, 0) >= MIN_BITRATE
