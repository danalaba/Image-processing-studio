import unittest
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from support import DatabaseTestCase

from app.image_service import resize_slots, resize_image
from fastapi import HTTPException
from app.limits import MAX_BODY_BYTES, MAX_CONCURRENT_RESIZES, MAX_FILE_BYTES
from app.main import app


def image_bytes(fmt="PNG", size=(600, 300), mode="RGB", **save_options):
    output = BytesIO()
    with Image.new(mode, size) as image:
        image.save(output, format=fmt, **save_options)
    return output.getvalue()


class ResizeTests(DatabaseTestCase):

    def resize(self, data=None, width="200", height="200", name="photo.png"):
        return self.finish_job(self.client.post(
            "/api/images/resize",
            files={"file": (name, image_bytes() if data is None else data, "application/octet-stream")},
            data={"width": width, "height": height},
        ))

    def test_supported_formats_return_real_png_and_keep_ratio(self):
        for fmt in ("JPEG", "PNG", "WEBP"):
            with self.subTest(format=fmt):
                # MIME і назва навмисно не відповідають формату: довіряємо байтам.
                response = self.resize(image_bytes(fmt), name="untrusted-name.dat")
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertEqual(response.headers["content-type"], "image/png")
                self.assertIn("attachment", response.headers["content-disposition"])
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["x-image-width"], "200")
                self.assertEqual(response.headers["x-image-height"], "100")
                with Image.open(BytesIO(response.content)) as result:
                    result.load()
                    self.assertEqual(result.size, (200, 100))
                    self.assertEqual(result.format, "PNG")

    def test_small_image_is_not_upscaled(self):
        response = self.resize(image_bytes(size=(30, 20)))
        with Image.open(BytesIO(response.content)) as result:
            self.assertEqual(result.size, (30, 20))

    def test_transparency_is_preserved(self):
        response = self.resize(image_bytes(mode="RGBA"))
        with Image.open(BytesIO(response.content)) as result:
            self.assertEqual(result.mode, "RGBA")
            self.assertEqual(result.getpixel((0, 0))[3], 0)

    def test_phone_exif_orientation_is_applied(self):
        exif = Image.Exif()
        exif[274] = 6  # Поворот на 90 градусів.
        response = self.resize(image_bytes("JPEG", size=(60, 30), exif=exif))
        with Image.open(BytesIO(response.content)) as result:
            self.assertEqual(result.size, (30, 60))
            self.assertNotIn(274, result.getexif())

    def test_empty_and_fake_image_rejected(self):
        for data in (b"", b"this is text, not a photo"):
            with self.subTest(data=data):
                self.assertEqual(self.resize(data).status_code, 400)

    def test_corrupted_png_rejected(self):
        self.assertEqual(self.resize(image_bytes()[:50]).status_code, 400)

    def test_unsupported_format_rejected_even_with_png_filename(self):
        self.assertEqual(self.resize(image_bytes("GIF")).status_code, 415)

    def test_animated_png_rejected(self):
        output = BytesIO()
        with Image.new("RGB", (20, 20), "red") as first, Image.new("RGB", (20, 20), "blue") as second:
            first.save(output, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        self.assertEqual(self.resize(output.getvalue()).status_code, 415)

    def test_pixel_limit_rejected_before_decoding(self):
        self.assertEqual(self.resize(image_bytes(size=(4001, 3000))).status_code, 413)

    def test_long_thin_image_rejected(self):
        self.assertEqual(self.resize(image_bytes(size=(12001, 1))).status_code, 413)

    def test_invalid_target_dimensions_rejected(self):
        for value in ("0", "-1", "4097", "2.5", "abc"):
            with self.subTest(width=value):
                self.assertEqual(self.resize(width=value).status_code, 422)

    def test_file_limit_checked_separately_from_body_limit(self):
        self.assertEqual(self.resize(b"x" * (MAX_FILE_BYTES + 1)).status_code, 413)

    def test_body_limit_with_content_length(self):
        response = self.client.post(
            "/api/images/resize", content=b"small",
            headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
        )
        self.assertEqual(response.status_code, 413)

    def test_body_limit_without_content_length(self):
        def chunks():
            yield b"x" * MAX_BODY_BYTES
            yield b"x"

        response = self.client.post("/api/images/resize", content=chunks())
        self.assertEqual(response.status_code, 413)

    def test_unexpected_upload_field_rejected(self):
        response = self.client.post(
            "/api/images/resize",
            files=[("file", ("one.png", image_bytes())), ("extra", ("two.png", image_bytes()))],
            data={"width": "200", "height": "200"},
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_file_rejected(self):
        response = self.client.post("/api/images/resize", data={"width": "200", "height": "200"})
        self.assertEqual(response.status_code, 422)

    def test_busy_server_returns_retry_and_recovers(self):
        acquired = 0
        try:
            for _ in range(MAX_CONCURRENT_RESIZES):
                self.assertTrue(resize_slots.acquire(blocking=False))
                acquired += 1
            with self.assertRaises(HTTPException) as raised:
                resize_image(image_bytes(), 200, 200)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(raised.exception.headers["Retry-After"], "2")
        finally:
            for _ in range(acquired):
                resize_slots.release()
        self.assertEqual(self.resize().status_code, 200)


if __name__ == "__main__":
    unittest.main()
