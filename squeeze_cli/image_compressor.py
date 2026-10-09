"""JPEG quality binary search + downscale fallback, mirroring ImageCompressor.kt."""

import io

from PIL import Image, ImageOps

try:  # registers .heic/.heif with Pillow
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # pragma: no cover - pillow-heif is a declared dependency
    pass


def compress_image(source_path: str, target_bytes: int, output_path: str) -> str:
    image = Image.open(source_path)
    image = ImageOps.exif_transpose(image)  # respects EXIF orientation
    image = _to_jpeg_mode(image)

    working = image
    best: bytes | None = None

    for _ in range(4):
        lo, hi = 2, 95
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = _encode_jpeg(working, mid)
            if len(data) <= target_bytes:
                best = data
                lo = mid + 1
            else:
                hi = mid - 1
        if best is not None:
            break

        # Even quality=2 was too big -> downscale 30% and retry.
        new_w = max(1, int(working.width * 0.7))
        new_h = max(1, int(working.height * 0.7))
        working = working.resize((new_w, new_h), Image.LANCZOS)

    final_bytes = best if best is not None else _encode_jpeg(working, 2)

    with open(output_path, "wb") as f:
        f.write(final_bytes)
    return output_path


def _to_jpeg_mode(image: Image.Image) -> Image.Image:
    """JPEG takes RGB, L or CMYK only; transparency is flattened onto white rather than dropped."""
    if image.mode in ("RGB", "L", "CMYK"):
        return image
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
