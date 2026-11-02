from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from support import DatabaseTestCase
from test_resize import image_bytes
from app.database import database
from app.tasks import process_job, dispatch_pending


class QueueTests(DatabaseTestCase):
    def submit(self, client=None):
        return (client or self.client).post("/api/jobs", files={"file": ("test.png", image_bytes())},
                                           data={"width": "200", "height": "200"})

    def test_returns_202_without_processing_then_reports_progress_and_result(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual((job["status"], job["progress"]), ("QUEUED", 0))
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/result").status_code, 409)
        stages = []
        from app.tasks import resize_image
        def tracking_resize(data, width, height, checkpoint):
            def track(progress, stage):
                checkpoint(progress, stage)
                current = self.client.get(f"/api/jobs/{job['id']}").json()
                stages.append((current["progress"], current["stage"]))
            return resize_image(data, width, height, track)
        with patch("app.tasks.resize_image", side_effect=tracking_resize):
            process_job(job["id"], "worker-a")
        current = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual((current["status"], current["progress"], current["worker_id"]), ("COMPLETED", 100, "worker-a"))
        self.assertEqual([progress for progress, _ in stages], sorted(progress for progress, _ in stages))
        self.assertIn((60, "resizing"), stages)
        with database() as connection:
            self.assertIsNone(connection.execute("SELECT input_data FROM jobs WHERE id = %s", (job["id"],)).fetchone()["input_data"])

    def test_invalid_image_never_enters_queue(self):
        response = self.client.post("/api/jobs", files={"file": ("bad.png", b"invalid")}, data={"width": 200, "height": 200})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/jobs").json()["jobs"], [])

    def test_queued_cancel_is_immediate_idempotent_and_worker_skips_it(self):
        job_id = self.submit().json()["id"]
        for _ in range(2):
            self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "CANCELLED")
        with patch("app.tasks.resize_image") as resize:
            process_job(job_id, "late-worker")
            resize.assert_not_called()
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 204)

    def test_running_cancel_honoured_at_next_stage(self):
        job_id = self.submit().json()["id"]
        ready, proceed = Event(), Event()
        def slow_stage(data, width, height, checkpoint):
            checkpoint(20, "decoding")
            ready.set()
            self.assertTrue(proceed.wait(10))
            checkpoint(60, "resizing")
            self.fail("Cancellation must prevent later work")
        with patch("app.tasks.resize_image", side_effect=slow_stage), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(process_job, job_id, "slow-worker")
            try:
                self.assertTrue(ready.wait(10))
                self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "CANCELLING")
            finally:
                proceed.set()
            future.result(timeout=10)
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "CANCELLED")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 409)

    def test_cancel_has_ownership_checks(self):
        job_id = self.submit().json()["id"]
        self.assertEqual(self.second_user().post(f"/api/jobs/{job_id}/cancel").status_code, 404)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "QUEUED")

    def test_duplicate_delivery_only_processes_once(self):
        job_id = self.submit().json()["id"]
        from app.tasks import resize_image
        with patch("app.tasks.resize_image", wraps=resize_image) as resize:
            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(lambda worker: process_job(job_id, worker), ("one", "two")))
            self.assertEqual(resize.call_count, 1)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "COMPLETED")

    def test_completed_cancel_does_not_discard_result(self):
        job_id = self.submit().json()["id"]
        process_job(job_id, "worker")
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "COMPLETED")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 200)

    def test_outbox_recovers_unpublished_job_without_storing_image_in_message(self):
        job_id = self.submit().json()["id"]
        with patch("app.tasks.publish_job", return_value=True) as publish:
            dispatch_pending()
            self.assertEqual(str(publish.call_args.args[0]), job_id)
            dispatch_pending()
            self.assertEqual(publish.call_count, 1)

    def test_abandoned_running_job_marked_failed_and_input_cleared(self):
        job_id = self.submit().json()["id"]
        with database() as connection:
            connection.execute("UPDATE jobs SET status = 'RUNNING', started_at = now() - interval '100 seconds' WHERE id = %s", (job_id,))
        dispatch_pending()
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "FAILED")
        with database() as connection:
            self.assertIsNone(connection.execute("SELECT input_data FROM jobs WHERE id = %s", (job_id,)).fetchone()["input_data"])

    def test_global_queue_limit_is_enforced(self):
        with patch("app.jobs.MAX_PENDING_JOBS", 1):
            self.assertEqual(self.submit().status_code, 202)
            self.assertEqual(self.submit(self.second_user()).status_code, 503)
