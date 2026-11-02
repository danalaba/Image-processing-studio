"""Persistent jobs and bounded results, owned by the authenticated user."""
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Response

from .auth import User
from .database import database
from .image_service import validate_image
from .limits import MAX_JOBS_PER_USER, MAX_ACTIVE_JOBS_PER_USER, MAX_PENDING_JOBS, MAX_OUTPUT_SIDE
from .queue import publish_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
METADATA = "id, status, progress, stage, target_width, target_height, width, height, error, created_at, started_at, finished_at, worker_id"
ACTIVE = {"QUEUED", "RUNNING", "CANCELLING"}


def create_job(user_id, data, width, height):
    validate_image(data)
    if not (1 <= width <= MAX_OUTPUT_SIDE and 1 <= height <= MAX_OUTPUT_SIDE):
        raise HTTPException(422, "Рамка має бути від 1 до 4096 px на сторону.")
    job_id = uuid4()
    with database() as connection:
        # Consistent lock order: global admission, then user. Locks are not held
        # while images are processed or while contacting the broker.
        connection.execute("SELECT pg_advisory_xact_lock(710033)")
        connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
        counts = connection.execute("""
            SELECT count(*) AS total,
                count(*) FILTER (WHERE status IN ('QUEUED','RUNNING','CANCELLING')) AS active
            FROM jobs WHERE user_id = %s
        """, (user_id,)).fetchone()
        if counts["total"] >= MAX_JOBS_PER_USER:
            raise HTTPException(409, "Досягнуто ліміт у 20 задач. Видаліть старі задачі з історії.")
        if counts["active"] >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(429, "У вас уже є дві незавершені задачі.", headers={"Retry-After": "2"})
        pending = connection.execute("SELECT count(*) AS n FROM jobs WHERE status IN ('QUEUED','RUNNING','CANCELLING')").fetchone()["n"]
        if pending >= MAX_PENDING_JOBS:
            raise HTTPException(503, "Черга заповнена. Спробуйте пізніше.", headers={"Retry-After": "10"})
        job = connection.execute(f"""
            INSERT INTO jobs(id, user_id, status, stage, input_data, target_width, target_height)
            VALUES (%s, %s, 'QUEUED', 'queued', %s, %s, %s) RETURNING {METADATA}
        """, (job_id, user_id, data, width, height)).fetchone()
    if publish_job(job_id):
        with database() as connection:
            connection.execute("UPDATE jobs SET dispatched_at = now() WHERE id = %s AND status = 'QUEUED'", (job_id,))
    return job


def owned_job(connection, user_id, job_id, fields=METADATA, lock=False):
    job = connection.execute(f"SELECT {fields} FROM jobs WHERE id = %s AND user_id = %s" + (" FOR UPDATE" if lock else ""),
                             (job_id, user_id)).fetchone()
    if not job:
        raise HTTPException(404, "Задачу не знайдено.")
    return job


@router.get("")
def history(user: User, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database() as connection:
        jobs = connection.execute(f"SELECT {METADATA} FROM jobs WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
                                  (user["id"], MAX_JOBS_PER_USER)).fetchall()
    return {"jobs": jobs, "limit": MAX_JOBS_PER_USER}


@router.get("/{job_id}")
def detail(job_id: UUID, user: User, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database() as connection:
        return owned_job(connection, user["id"], job_id)


@router.get("/{job_id}/result")
def download(job_id: UUID, user: User):
    with database() as connection:
        job = owned_job(connection, user["id"], job_id, "status, result, width, height")
    if job["status"] != "COMPLETED":
        raise HTTPException(409, "Результат ще недоступний.")
    return Response(content=bytes(job["result"]), media_type="image/png", headers={
        "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="resized-image.png"',
        "X-Image-Width": str(job["width"]), "X-Image-Height": str(job["height"]),
    })


@router.delete("/{job_id}", status_code=204)
def delete(job_id: UUID, user: User):
    with database() as connection:
        # Same user lock as admission; active jobs cannot be deleted.
        connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user["id"],))
        job = owned_job(connection, user["id"], job_id)
        if job["status"] in ACTIVE:
            raise HTTPException(409, "Дочекайтеся завершення обробки.")
        connection.execute("DELETE FROM jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))


@router.post("/{job_id}/cancel")
def cancel(job_id: UUID, user: User):
    with database() as connection:
        job = owned_job(connection, user["id"], job_id, lock=True)
        if job["status"] == "QUEUED":
            connection.execute("""
                UPDATE jobs SET status = 'CANCELLED', stage = 'cancelled',
                    input_data = NULL, finished_at = now() WHERE id = %s
            """, (job_id,))
        elif job["status"] == "RUNNING":
            connection.execute("UPDATE jobs SET status = 'CANCELLING', stage = 'cancelling' WHERE id = %s", (job_id,))
        return owned_job(connection, user["id"], job_id)
