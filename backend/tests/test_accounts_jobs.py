from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from support import DatabaseTestCase, PASSWORD
from app.auth import token_digest
from app.database import database
from app.jobs import process_resize
from app.limits import MAX_JOBS_PER_USER
from app.main import app


def photo():
    data = BytesIO()
    with Image.new("RGB", (600, 300), "green") as image:
        image.save(data, format="PNG")
    return data.getvalue()


class AccountJobTests(DatabaseTestCase):
    def resize(self, client=None, content=None):
        return (client or self.client).post("/api/images/resize", files={"file": ("sample.png", photo() if content is None else content)},
                                           data={"width": "200", "height": "200"})

    def user_id(self):
        return self.client.get("/api/auth/me").json()["id"]

    def fill_jobs(self, count, status="FAILED"):
        with database() as connection:
            for _ in range(count):
                connection.execute("INSERT INTO jobs(id, user_id, status, target_width, target_height) VALUES (%s,%s,%s,200,200)",
                                   (uuid4(), self.user_id(), status))

    def test_anonymous_requests_cannot_process_or_read_jobs(self):
        anonymous = self.enterContext(TestClient(app))
        for response in (self.resize(anonymous), anonymous.get("/api/jobs"), anonymous.get("/api/auth/me")):
            self.assertEqual(response.status_code, 401)

    def test_registration_normalizes_name_and_rejects_duplicate(self):
        response = self.client.post("/api/auth/register", json={"username": "TESTER", "password": PASSWORD})
        self.assertEqual(response.status_code, 409)

    def test_passwords_and_tokens_are_only_stored_as_hashes(self):
        with database() as connection:
            user = connection.execute("SELECT password_hash FROM users").fetchone()
            session = connection.execute("SELECT token_hash FROM sessions").fetchone()
        self.assertTrue(user["password_hash"].startswith("$argon2id$"))
        self.assertNotIn(PASSWORD, user["password_hash"])
        self.assertEqual(session["token_hash"], token_digest(self.token))

    def test_login_rejects_wrong_password_and_unknown_user(self):
        for username in ("tester", "unknown"):
            response = self.client.post("/api/auth/login", json={"username": username, "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)

    def test_validation_does_not_echo_password(self):
        response = self.client.post("/api/auth/register", json={"username": "bad name", "password": "secret"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret", response.text)

    def test_auth_body_is_bounded(self):
        response = self.client.post("/api/auth/login", content=b"x" * 16385)
        self.assertEqual(response.status_code, 413)

    def test_login_throttled_and_counters_persist(self):
        with database() as connection:
            connection.execute("UPDATE auth_limits SET attempts = 30")
        response = self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "60")

    def test_logout_revokes_current_session(self):
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        response = self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def test_expired_session_is_rejected(self):
        with database() as connection:
            connection.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)

    def test_old_sessions_evicted_after_five_logins(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        with database() as connection:
            self.assertEqual(connection.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"], 5)

    def test_result_survives_new_application_lifespan_and_login(self):
        result = self.resize()
        self.assertEqual(result.status_code, 200, result.text[:200])
        job_id = result.headers["x-job-id"]
        another_process = self.enterContext(TestClient(app))
        response = another_process.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        another_process.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        history = another_process.get("/api/jobs").json()["jobs"]
        self.assertEqual(history[0]["id"], job_id)
        self.assertEqual(history[0]["status"], "COMPLETED")
        self.assertNotIn("result", history[0])
        self.assertEqual(another_process.get(f"/api/jobs/{job_id}/result").content, result.content)

    def test_ownership_for_history_metadata_download_and_delete(self):
        result = self.resize()
        job_id = result.headers["x-job-id"]
        other = self.second_user()
        self.assertEqual(other.get("/api/jobs").json()["jobs"], [])
        for method, path in (("GET", ""), ("GET", "/result"), ("DELETE", "")):
            self.assertEqual(other.request(method, f"/api/jobs/{job_id}{path}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 200)

    def test_failed_job_recorded_without_result(self):
        self.assertEqual(self.resize(content=b"not an image").status_code, 400)
        job = self.client.get("/api/jobs").json()["jobs"][0]
        self.assertEqual(job["status"], "FAILED")
        self.assertTrue(job["finished_at"])
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/result").status_code, 409)

    def test_history_limit_and_deletion_release_capacity(self):
        self.fill_jobs(MAX_JOBS_PER_USER)
        self.assertEqual(self.resize().status_code, 409)
        job = self.client.get("/api/jobs").json()["jobs"][0]
        self.assertEqual(self.client.delete(f"/api/jobs/{job['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").status_code, 404)
        self.assertEqual(self.resize().status_code, 200)

    def test_running_limit_and_running_delete_rejected(self):
        self.fill_jobs(2, "RUNNING")
        self.assertEqual(self.resize().status_code, 429)
        job = self.client.get("/api/jobs").json()["jobs"][0]
        self.assertEqual(self.client.delete(f"/api/jobs/{job['id']}").status_code, 409)

    def test_large_result_is_rejected_and_marked_failed(self):
        with patch("app.jobs.MAX_RESULT_BYTES", 1):
            self.assertEqual(self.resize().status_code, 413)
        self.assertEqual(self.client.get("/api/jobs").json()["jobs"][0]["status"], "FAILED")

    def test_concurrent_admission_does_not_exceed_history_limit(self):
        self.fill_jobs(MAX_JOBS_PER_USER - 1)
        user_id = self.user_id()
        def attempt(_):
            try:
                process_resize(user_id, photo(), 200, 200)
                return 200
            except Exception as error:
                return getattr(error, "status_code", 500)
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(attempt, range(2))), [200, 409])
        self.assertEqual(len(self.client.get("/api/jobs").json()["jobs"]), MAX_JOBS_PER_USER)
