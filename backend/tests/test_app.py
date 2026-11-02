import importlib
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from support import DatabaseTestCase
from app.main import app


class AppTests(DatabaseTestCase):

    def test_health_contract(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertTrue(response.json()["instance_id"])
        self.assertEqual(response.json()["service"], "image-processing-studio")
        self.assertEqual(response.headers["x-instance-id"], response.json()["instance_id"])

    def test_frontend_and_assets_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        for asset in ("theme.css", "styles.css", "app.js"):
            with self.subTest(asset=asset):
                self.assertEqual(self.client.get(f"/static/{asset}").status_code, 200)

    def test_instance_id_can_be_set_per_server(self):
        import app.main as main

        try:
            with patch.dict(os.environ, {"INSTANCE_ID": "api-test-2"}):
                reloaded = importlib.reload(main)
                response = TestClient(reloaded.app).get("/api/health")
                self.assertEqual(response.json()["instance_id"], "api-test-2")
                self.assertEqual(response.headers["x-instance-id"], "api-test-2")
        finally:
            importlib.reload(main)

    def test_personal_history_starts_empty(self):
        self.assertEqual(self.client.get("/api/jobs").json(), {"jobs": [], "limit": 20})


if __name__ == "__main__":
    unittest.main()
