from squeeze_cli import policy
from squeeze_cli.policy import MIN_BITRATE, Floors

PX_8K = 7680 * 4320
PX_1080 = 1920 * 1080


def test_default_ladder_and_floor_override():
    assert Floors().ladder() == [1080, 720]
    assert Floors(min_height=480).ladder() == [1080, 720, 540, 480]
    assert Floors(min_height=900).ladder() == [1080, 900]


def test_initial_bitrate_leaves_room_for_audio_and_clamps():
    video = policy.initial_video_bitrate(20_000_000, 60, 128_000 * 60 / 8)
    assert MIN_BITRATE <= video < 20_000_000 * 8 / 60
    assert policy.initial_video_bitrate(1_000, 600, 4_000_000) == MIN_BITRATE
    assert policy.initial_video_bitrate(2 * 1024**3, 1, 0) == policy.MAX_BITRATE


def test_source_bounded_budget():
    assert policy.initial_video_bitrate(20_000_000, 60, 0, 1_000_000) < policy.initial_video_bitrate(20_000_000, 60, 0)


def test_next_bitrate_shrinks_when_over_and_never_below_min():
    lowered = policy.next_video_bitrate(1_000_000, 30_000_000, 20_000_000, 1_000_000)
    assert MIN_BITRATE <= lowered < 1_000_000
    assert policy.next_video_bitrate(MIN_BITRATE, 1_000_000_000, 1_000, 0) == MIN_BITRATE
    assert policy.next_video_bitrate(500_000, 0, 1_000, 0) >= MIN_BITRATE


def test_audio_capped_to_share_never_above_source():
    # 8K 12:56 clip at 20MB: 256k source audio must be capped
    assert policy.audio_bitrate(256_000, 20_000_000, 776) < 100_000
    assert policy.audio_bitrate(256_000, 20_000_000, 776) >= policy.AUDIO_START_FLOOR
    assert policy.audio_bitrate(96_000, 200_000_000, 60) == 96_000
    assert policy.audio_bitrate(0, 20_000_000, 60) == 0


def test_audio_step_down():
    assert policy.next_lower_audio(69_000) == 64_000
    assert policy.next_lower_audio(64_000) == 48_000
    assert policy.next_lower_audio(32_000) is None
    assert policy.next_lower_audio(48_000, Floors(min_audio=48_000)) is None
    assert policy.next_lower_audio(0) is None


def test_starved_and_starting_rung():
    ladder = Floors().ladder()
    assert not policy.starved_at(8_000_000, PX_1080, 1080, 1080)
    assert policy.starved_at(129_000, PX_8K, 4320, 1080)
    assert policy.starting_ladder_index(129_000, PX_8K, 4320, ladder) == 1
    assert policy.starting_ladder_index(8_000_000, PX_1080, 1080, ladder) == 0


def test_assess_levels():
    assert policy.assess(20_000_000, 776, 256_000, PX_8K, 4320).level == "rough"
    unreachable = policy.assess(20_000_000, 10_800, 128_000, PX_1080, 1080)
    assert unreachable.level == "unreachable" and unreachable.min_bytes > 20_000_000
    assert policy.assess(100_000_000, 60, 128_000, PX_1080, 1080).level == "ok"
    assert policy.assess(20_000_000, 60, 128_000, PX_1080, 1080, source_bytes=5_000_000).level == "ok"
    assert policy.assess(1_000_000, 60, 0, 1280 * 720, 720).min_bytes == 750_000
