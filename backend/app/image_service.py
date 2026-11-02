"""Одна обмежена операція Pillow, незалежна від маршруту та інтерфейсу."""

import warnings
from io import BytesIO
from threading import BoundedSemaphore

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from .limits import (
    MAX_CONCURRENT_RESIZES,
    MAX_FILE_BYTES,
    MAX_INPUT_PIXELS,
    MAX_INPUT_SIDE,
    MAX_OUTPUT_SIDE,
)

Image.MAX_IMAGE_PIXELS = MAX_INPUT_PIXELS
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
resize_slots = BoundedSemaphore(MAX_CONCURRENT_RESIZES)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image(data: bytes) -> int:
    """Reject invalid headers, formats and excessive work before queue admission."""
    if not data:
        raise HTTPException(400, "Файл порожній.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Файл перевищує 10 MiB.")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in ALLOWED_FORMATS:
                raise HTTPException(415, "Підтримуються лише JPG, PNG і WebP.")
            if source.width * source.height > MAX_INPUT_PIXELS or max(source.size) > MAX_INPUT_SIDE:
                raise HTTPException(413, "Максимум 12 млн пікселів і 12000 px на сторону.")
            if getattr(source, "n_frames", 1) != 1:
                raise HTTPException(415, "Анімовані зображення поки не підтримуються.")
            source.verify()
            return source.width * source.height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(413, "Фото перевищує ліміт у 12 млн пікселів.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(400, "Не вдалося прочитати зображення. Файл пошкоджений.") from None


def resize_image(data: bytes, width: int, height: int, checkpoint=None) -> tuple[bytes, int, int]:
    """Stage callbacks allow cooperative cancellation outside Pillow calls."""
    validate_image(data)
    if not (1 <= width <= MAX_OUTPUT_SIDE and 1 <= height <= MAX_OUTPUT_SIDE):
        raise HTTPException(422, "Кожна сторона рамки має бути від 1 до 4096 px.")
    if not resize_slots.acquire(blocking=False):
        raise HTTPException(503, "Сервер зайнятий.", headers={"Retry-After": "2"})
    def report(progress, stage):
        if checkpoint:
            checkpoint(progress, stage)
    try:
        report(20, "decoding")
        with Image.open(BytesIO(data)) as source:
            source.load()
            report(45, "orienting")
            oriented = ImageOps.exif_transpose(source)
            try:
                has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                with oriented.convert("RGBA" if has_alpha else "RGB") as image:
                    report(60, "resizing")
                    image.thumbnail((width, height), Image.Resampling.LANCZOS)
                    image.info.clear()
                    report(85, "encoding")
                    output = BytesIO()
                    image.save(output, format="PNG")
                    report(95, "saving")
                    return output.getvalue(), image.width, image.height
            finally:
                oriented.close()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(400, "Не вдалося прочитати зображення. Файл пошкоджений.") from None
    finally:
        resize_slots.release()
