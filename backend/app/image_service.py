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


def resize_image(data: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Вписуємо фото у рамку без розтягування і без збільшення оригіналу."""
    if not data:
        raise HTTPException(400, "Файл порожній.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Файл перевищує 10 MiB.")
    if not (1 <= width <= MAX_OUTPUT_SIDE and 1 <= height <= MAX_OUTPUT_SIDE):
        raise HTTPException(422, "Кожна сторона рамки має бути від 1 до 4096 px.")
    if not resize_slots.acquire(blocking=False):
        raise HTTPException(503, "Сервер зараз обробляє інші фото. Спробуйте за кілька секунд.", headers={"Retry-After": "2"})

    try:
        try:
            with Image.open(BytesIO(data)) as source:
                # Перевіряємо фактичний формат, а не розширення чи MIME від браузера.
                if source.format not in ALLOWED_FORMATS:
                    raise HTTPException(415, "Підтримуються лише JPG, PNG і WebP.")
                if source.width * source.height > MAX_INPUT_PIXELS or max(source.size) > MAX_INPUT_SIDE:
                    raise HTTPException(413, "Фото має перевищення: максимум 12 млн пікселів і 12000 px на сторону.")
                if getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(415, "Анімовані та багатокадрові зображення поки не підтримуються.")
                source.verify()

            # Після verify() Pillow потребує повторного відкриття.
            with Image.open(BytesIO(data)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                    with oriented.convert("RGBA" if has_alpha else "RGB") as image:
                        image.thumbnail((width, height), Image.Resampling.LANCZOS)
                        image.info.clear()
                        output = BytesIO()
                        image.save(output, format="PNG")
                        return output.getvalue(), image.width, image.height
                finally:
                    oriented.close()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(413, "Фото перевищує ліміт у 12 млн пікселів.") from None
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            raise HTTPException(400, "Не вдалося прочитати зображення. Файл пошкоджений або має некоректний вміст.") from None
    finally:
        resize_slots.release()
