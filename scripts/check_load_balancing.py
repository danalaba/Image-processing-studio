"""Validate real HTTP balancing and shared state through the running Nginx.

Creates two temporary accounts without printing credentials; removes its job.
This is separate from scripts/check_queue.py's two-worker distribution check.
"""
import argparse
from collections import Counter
from io import BytesIO
import secrets
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    expected = {"api-1", "api-2"}

    def backend(response):
        assert response.headers.get("x-load-balancer") == "nginx", "Request did not pass through Nginx"
        instance = response.headers.get("x-instance-id")
        assert instance in expected, f"Unexpected backend identity: {instance}"
        return instance

    with httpx.Client(base_url=args.url, timeout=20, trust_env=False) as client:
        counts = Counter()
        for _ in range(12):
            response = client.get("/api/health")
            response.raise_for_status()
            instance = backend(response)
            assert response.json()["instance_id"] == instance
            counts[instance] += 1
        assert set(counts) == expected, f"Both APIs must receive HTTP requests: {dict(counts)}"
        print("HTTP distribution:", dict(counts))

        response = client.post("/api/auth/register", json={
            "username": "balance-" + secrets.token_hex(6), "password": secrets.token_urlsafe(32),
        })
        response.raise_for_status()
        registered_on = backend(response)
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        seen = set()
        user_ids = set()
        for _ in range(8):
            response = client.get("/api/auth/me")
            response.raise_for_status()
            seen.add(backend(response))
            user_ids.add(response.json()["id"])
        assert seen == expected and len(user_ids) == 1, "Session was not shared between APIs"
        # Redirects must retain the public port and ignore a forged proto header.
        redirect = client.get("/api/jobs/", headers={"X-Forwarded-Proto": "https"})
        assert redirect.status_code == 307
        assert urlsplit(redirect.headers["location"]).netloc == urlsplit(args.url).netloc
        assert urlsplit(redirect.headers["location"]).scheme == urlsplit(args.url).scheme

        data = BytesIO()
        with Image.new("RGB", (600, 300), "green") as image:
            image.save(data, format="PNG")
        response = client.post("/api/jobs", files={"file": ("balance.png", data.getvalue(), "image/png")},
                               data={"width": 200, "height": 200})
        assert response.status_code == 202, response.text
        created_on = backend(response)
        job_id = response.json()["id"]
        seen = set()
        for _ in range(8):
            response = client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            seen.add(backend(response))
            assert response.json()["id"] == job_id
        assert seen == expected, "Job metadata is not readable across both APIs"

        deadline = time.monotonic() + 100
        while True:
            response = client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["status"] == "COMPLETED":
                break
            assert job["status"] in ("QUEUED", "RUNNING"), job
            if time.monotonic() > deadline:
                raise RuntimeError("Worker did not finish the HTTP smoke job")
            time.sleep(.2)
        payloads, seen = set(), set()
        for _ in range(8):
            response = client.get(f"/api/jobs/{job_id}/result")
            response.raise_for_status()
            seen.add(backend(response))
            payloads.add(response.content)
        assert seen == expected and len(payloads) == 1, "Results differ between API instances"
        with Image.open(BytesIO(next(iter(payloads)))) as image:
            image.load()
            assert image.size == (200, 100) and image.format == "PNG"

        with httpx.Client(base_url=args.url, timeout=20, trust_env=False) as other:
            response = other.post("/api/auth/register", json={
                "username": "other-" + secrets.token_hex(6), "password": secrets.token_urlsafe(32),
            })
            response.raise_for_status()
            other.headers["Authorization"] = "Bearer " + response.json()["access_token"]
            seen = set()
            for _ in range(8):
                response = other.get(f"/api/jobs/{job_id}/result")
                assert response.status_code == 404
                seen.add(backend(response))
            assert seen == expected, "Ownership was not enforced by both APIs"
            other.post("/api/auth/logout").raise_for_status()
        client.delete(f"/api/jobs/{job_id}").raise_for_status()
        client.post("/api/auth/logout").raise_for_status()
        seen = set()
        for _ in range(8):
            response = client.get("/api/auth/me")
            assert response.status_code == 401
            seen.add(backend(response))
        assert seen == expected, "Logout was not shared between APIs"
        print(f"Shared state passed: registered_on={registered_on}, created_on={created_on}, readable_on=api-1,api-2")
    print("HTTP load balancing passed: two real APIs, shared session/history/result, ownership and logout.")


if __name__ == "__main__":
    main()
