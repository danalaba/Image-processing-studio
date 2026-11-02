"""HTTP smoke for an already running API + Redis + Celery stack.

Creates a temporary test account (retained without results) and removes its jobs.
Credentials are generated only in memory. Does not stop services or clear data.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import secrets
import time
from zipfile import ZipFile

import httpx
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--require-two-workers", action="store_true")
    parser.add_argument("--batch", action="store_true", help="Submit two images per job and verify ZIP results")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=20, trust_env=False) as client:
        client.get("/api/health").raise_for_status()
        response = client.post("/api/auth/register", json={
            "username": "queue-check-" + secrets.token_hex(6), "password": secrets.token_urlsafe(32),
        })
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        # A bounded, realistic image gives both ready workers time to consume.
        source = BytesIO()
        with Image.effect_noise((3000, 3000), 70) as image:
            image.save(source, format="JPEG", quality=80)
        def submit(_):
            uploads = [("file", (f"check-{index + 1}.jpg", source.getvalue(), "image/jpeg")) for index in range(2 if args.batch else 1)]
            result = client.post("/api/jobs", files=uploads,
                                 data={"width": 2000, "height": 2000})
            assert result.status_code == 202, result.text
            job = result.json()
            assert job["status"] == "QUEUED" and job["progress"] == 0
            return job["id"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            job_ids = list(executor.map(submit, range(2)))
        workers = set()
        for job_id in job_ids:
            deadline = time.monotonic() + 100
            while True:
                response = client.get(f"/api/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                assert 0 <= job["progress"] <= 100
                if job["status"] not in ("QUEUED", "RUNNING", "CANCELLING"):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("No job completion; check workers, Redis and scheduler logs")
                time.sleep(.2)
            assert job["status"] == "COMPLETED", job
            assert job["progress"] == 100 and job["worker_id"]
            assert job["processed_files"] == job["file_count"] == (2 if args.batch else 1)
            workers.add(job["worker_id"])
            result = client.get(f"/api/jobs/{job_id}/result")
            result.raise_for_status()
            def check_png(data):
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    assert image.format == "PNG" and image.size == (2000, 2000)
            if args.batch:
                assert result.headers["content-type"] == "application/zip"
                with ZipFile(BytesIO(result.content)) as archive:
                    assert len(archive.namelist()) == 2 and archive.testzip() is None
                    for name in archive.namelist():
                        check_png(archive.read(name))
            else:
                check_png(result.content)
            print(f"job={job_id} status=COMPLETED progress=100 files={job['file_count']} worker={job['worker_id']}")
            client.delete(f"/api/jobs/{job_id}").raise_for_status()
        client.post("/api/auth/logout").raise_for_status()
        assert client.get("/api/jobs").status_code == 401
        if args.require_two_workers:
            assert len(workers) == 2, f"Expected two distinct ready workers, observed {len(workers)}"
    print("Queue smoke passed: HTTP 202, real background results, progress, download, deletion, logout.")


if __name__ == "__main__":
    main()
