"""Photo processing: downscaling, format conversion and thumbnails.

Photos (uploaded through a "Photos" field) are rotated upright and, when
they're larger than PHOTO_MAX_PX or PHOTO_MAX_MB or in a format browsers
can't show (e.g. iPhone HEIC), re-encoded as JPEG. Other uploads are never
altered. Every image Pillow can read, including TIFFs, gets a small JPEG
thumbnail for display.

Needs Pillow (and pillow-heif for HEIC). Without them, uploads are stored
unchanged and shown without thumbnails, so the app keeps working.
"""
import io
from pathlib import Path

from backend.config import settings

try:
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
except ImportError:  # pragma: no cover - depends on the environment
    Image = None

# Formats every browser can display directly
BROWSER_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def available() -> bool:
    return Image is not None


def _has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def process_photo(data: bytes, filename: str) -> tuple[bytes, str, str] | None:
    """Return (data, filename, mime) for a photo to store, or None to store it as uploaded.

    Small photos already in a browser format are kept byte-for-byte, so they
    don't lose quality to a needless re-encode."""
    if not available():
        return None
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        if fmt == "GIF" and getattr(img, "is_animated", False):
            return None
        too_big = max(img.size) > settings.PHOTO_MAX_PX or len(data) > settings.PHOTO_MAX_MB * 1024 * 1024
        if fmt in BROWSER_FORMATS and not too_big:
            return None
        img = ImageOps.exif_transpose(img)
        img.thumbnail((settings.PHOTO_MAX_PX, settings.PHOTO_MAX_PX), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        stem = Path(filename).stem or "photo"
        if _has_alpha(img):
            img.save(out, "PNG", optimize=True)
            return out.getvalue(), f"{stem}.png", "image/png"
        return _jpeg_within_limit(img.convert("RGB")), f"{stem}.jpg", "image/jpeg"
    except Exception:
        return None   # not an image Pillow understands: keep the original


def _jpeg_within_limit(img) -> bytes:
    """Encode as JPEG, lowering quality and then size until under PHOTO_MAX_MB."""
    limit = settings.PHOTO_MAX_MB * 1024 * 1024
    quality = settings.PHOTO_JPEG_QUALITY
    while True:
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        if out.tell() <= limit or max(img.size) <= 640:
            return out.getvalue()
        if quality > 65:
            quality -= 10
        else:
            img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.Resampling.LANCZOS)


def make_thumbnail(data: bytes) -> bytes | None:
    """A small upright JPEG preview, or None if the data isn't a readable image."""
    if not available():
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            # 16-bit / float data (e.g. SEM, AFM TIFFs): stretch its range to 8 bits
            img = img.convert("F")
            lo, hi = img.getextrema()
            scale = 255.0 / (hi - lo) if hi > lo else 1.0
            img = img.point(lambda v: (v - lo) * scale).convert("L")
        img.thumbnail((settings.THUMB_PX, settings.THUMB_PX), Image.Resampling.LANCZOS)
        if _has_alpha(img):  # flatten transparency onto white
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
            img = bg
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=80, optimize=True)
        return out.getvalue()
    except Exception:
        return None
