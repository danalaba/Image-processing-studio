from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi import HTTPException
from PIL import Image

from support import DatabaseTestCase
from test_resize import image_bytes
from app.database import database
from app.tasks import process_job


class BatchTests(DatabaseTestCase):
    def submit(self, files=None):
        files = files if files is not None else [("one.png", image_bytes()), ("two.jpg", image_bytes("JPEG"))]
        return self.client.post("/api/jobs", files=[("file", (name, data)) for name, data in files],
                                data={"width": "200", "height": "200"})

    def inputs_cleared(self, job_id):
        with database() as connection:
            row = connection.execute("SELECT input_data, input_files, result FROM jobs WHERE id = %s", (job_id,)).fetchone()
        self.assertIsNone(row["input_data"])
        self.assertIsNone(row["input_files"])
        return row

    def test_multiple_formats_download_real_zip_with_safe_unique_png_names(self):
        response = self.submit([("../../same.jpg", image_bytes("JPEG")), ("C:\\path\\same.png", image_bytes()),
                                ("українське.webp", image_bytes("WEBP", size=(100, 50)))])
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["id"]
        self.assertEqual(response.json()["file_count"], 3)
        self.assertEqual(response.json()["result_type"], "application/zip")
        process_job(job_id, "batch-worker")
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual((job["status"], job["processed_files"], job["progress"]), ("COMPLETED", 3, 100))
        result = self.client.get(f"/api/jobs/{job_id}/result")
        self.assertEqual(result.headers["content-type"], "application/zip")
        self.assertIn("resized-images.zip", result.headers["content-disposition"])
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ["01-same.png", "02-same.png", "03-українське.png"])
            for name, size in zip(archive.namelist(), [(200, 100), (200, 100), (100, 50)]):
                with Image.open(BytesIO(archive.read(name))) as image:
                    image.load()
                    self.assertEqual((image.format, image.size), ("PNG", size))
        self.inputs_cleared(job_id)
        other = self.second_user()
        self.assertEqual(other.get(f"/api/jobs/{job_id}/result").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 404)

    def test_bad_file_rejects_entire_batch_before_admission(self):
        self.assertEqual(self.submit([("good.png", image_bytes()), ("bad.png", b"bad")]).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs").json()["jobs"], [])

    def test_more_than_ten_files_rejected(self):
        self.assertEqual(self.submit([("image.png", image_bytes())] * 11).status_code, 413)

    def test_ten_files_accepted_as_one_job(self):
        response = self.submit([("image.png", image_bytes(size=(10, 10)))] * 10)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["file_count"], 10)
        self.assertEqual(len(self.client.get("/api/jobs").json()["jobs"]), 1)

    def test_aggregate_bytes_limit_enforced_even_when_each_file_is_valid(self):
        data = image_bytes()
        with patch("app.jobs.MAX_BATCH_BYTES", 2 * len(data) - 1):
            self.assertEqual(self.submit([("one.png", data), ("two.png", data)]).status_code, 413)

    def test_aggregate_pixel_limit_enforced(self):
        with patch("app.jobs.MAX_BATCH_PIXELS", 2 * 600 * 300 - 1):
            self.assertEqual(self.submit().status_code, 413)

    def test_archive_limit_leaves_no_partial_result_or_inputs(self):
        job_id = self.submit().json()["id"]
        with patch("app.tasks.MAX_ARCHIVE_BYTES", 1):
            process_job(job_id, "worker")
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "FAILED")
        self.assertIn("ZIP", job["error"])
        self.assertIsNone(self.inputs_cleared(job_id)["result"])

    def test_second_file_failure_does_not_publish_partial_zip(self):
        job_id = self.submit().json()["id"]
        with patch("app.tasks.resize_image", side_effect=[(image_bytes(size=(200, 100)), 200, 100), HTTPException(400, "Пошкоджено")]):
            process_job(job_id, "worker")
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual((job["status"], job["processed_files"]), ("FAILED", 1))
        self.assertIn("Фото 2", job["error"])
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 409)
        self.assertIsNone(self.inputs_cleared(job_id)["result"])

    def test_queued_cancellation_clears_all_files(self):
        job_id = self.submit().json()["id"]
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "CANCELLED")
        self.inputs_cleared(job_id)
        with patch("app.tasks.resize_image") as resize:
            process_job(job_id, "worker")
            resize.assert_not_called()

    def test_cancellation_during_second_file_stops_whole_batch(self):
        job_id = self.submit().json()["id"]
        ready, proceed = Event(), Event()
        from app.tasks import resize_image
        calls = 0
        def controlled(data, width, height, checkpoint):
            nonlocal calls
            calls += 1
            if calls == 2:
                checkpoint(20, "decoding")
                ready.set()
                self.assertTrue(proceed.wait(10))
                checkpoint(60, "resizing")
                self.fail("Cancellation should stop processing")
            return resize_image(data, width, height, checkpoint)
        with patch("app.tasks.resize_image", side_effect=controlled), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(process_job, job_id, "worker")
            try:
                self.assertTrue(ready.wait(10))
                job = self.client.get(f"/api/jobs/{job_id}").json()
                self.assertEqual(job["processed_files"], 1)
                self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "CANCELLING")
            finally:
                proceed.set()
            future.result(timeout=10)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "CANCELLED")
        self.assertIsNone(self.inputs_cleared(job_id)["result"])

    def test_legacy_single_file_queued_job_still_works(self):
        job_id, user_id = uuid4(), self.client.get("/api/auth/me").json()["id"]
        with database() as connection:
            connection.execute("INSERT INTO jobs(id,user_id,status,input_data,target_width,target_height) VALUES (%s,%s,'QUEUED',%s,200,200)",
                               (job_id, user_id, image_bytes()))
        process_job(job_id, "new-worker")
        response = self.client.get(f"/api/jobs/{job_id}/result")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
