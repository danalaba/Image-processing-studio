"""Integration fixtures. Only an explicitly selected *_test PostgreSQL is reset."""
import os
import unittest
from urllib.parse import urlsplit, unquote
from unittest.mock import patch

from fastapi.testclient import TestClient

test_url = os.environ.get("TEST_DATABASE_URL", "")
if not test_url or not unquote(urlsplit(test_url).path).endswith("_test"):
    raise RuntimeError("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test; see README")
os.environ["DATABASE_URL"] = test_url

from app.database import database
from app.main import app

PASSWORD = "test-password-123"


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("app.jobs.publish_job", return_value=False))
        self.client = self.enterContext(TestClient(app))
        with database() as connection:
            connection.execute("TRUNCATE jobs, sessions, users, auth_limits CASCADE")
        response = self.client.post("/api/auth/register", json={"username": "tester", "password": PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)
        self.token = response.json()["access_token"]
        self.client.headers["Authorization"] = "Bearer " + self.token

    def finish_job(self, response, client=None):
        """Execute a submitted job in-process; real broker/worker smoke is separate."""
        if response.status_code != 202:
            return response
        from app.tasks import process_job
        job_id = response.json()["id"]
        process_job(job_id, "integration-test-worker")
        result = (client or self.client).get(f"/api/jobs/{job_id}/result")
        result.headers["x-job-id"] = job_id
        return result

    def second_user(self):
        client = self.enterContext(TestClient(app))
        response = client.post("/api/auth/register", json={"username": "another", "password": PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        return client
