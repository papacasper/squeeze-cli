import random

from PIL import Image

from squeeze_cli.image_compressor import compress_image


def _noisy_png(path, size=(800, 600)):
    rnd = random.Random(1)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    img.save(path)


def test_fits_target(tmp_path):
    src = tmp_path / "a.png"
    _noisy_png(src)
    out = tmp_path / "a.jpg"
    compress_image(str(src), 100 * 1024, str(out))
    assert 0 < out.stat().st_size <= 100 * 1024
    assert Image.open(out).format == "JPEG"


def test_rgba_input(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (200, 200), (255, 0, 0, 128)).save(src)
    out = tmp_path / "a.jpg"
    compress_image(str(src), 50 * 1024, str(out))
    assert out.stat().st_size > 0


def test_downscales_when_quality_alone_is_not_enough(tmp_path):
    src = tmp_path / "a.png"
    _noisy_png(src, (1200, 1200))
    out = tmp_path / "a.jpg"
    compress_image(str(src), 10 * 1024, str(out))
    assert out.stat().st_size <= 10 * 1024
    assert Image.open(out).width < 1200
