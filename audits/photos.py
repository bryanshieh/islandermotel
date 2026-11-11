"""Shrinks uploaded photos so phone-camera pictures do not fill the disk."""

from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 1600  # pixels on the longest side; plenty to see damage clearly
JPEG_QUALITY = 80


class NotAPhoto(Exception):
    """The uploaded file is not an image the app can read."""


def shrink_photo(uploaded):
    """Return the upload as a JPEG no larger than MAX_SIDE, turned upright."""
    try:
        image = Image.open(uploaded)
        image.load()
        # Phones store rotation as metadata; apply it so the photo is upright.
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    except Exception as error:  # Pillow raises many types for bad files
        raise NotAPhoto(str(error)) from error
    stem = Path(getattr(uploaded, "name", "") or "photo").stem[:50] or "photo"
    return ContentFile(buffer.getvalue(), name=f"{stem}.jpg")
