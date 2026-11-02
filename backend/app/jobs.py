"""Persistent jobs and bounded results, owned by the authenticated user."""
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Response

from .auth import User
from .database import database
from .image_service import resize_image
from .limits import MAX_JOBS_PER_USER, MAX_ACTIVE_JOBS_PER_USER, MAX_RESULT_BYTES

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
METADATA = "id, status, target_width, target_height, width, height, error, created_at, finished_at"


def process_resize(user_id, data, width, height):
    job_id = uuid4()
    with database() as connection:
        # Serialize admission per user across all API processes.
        connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
        counts = connection.execute("""
            SELECT count(*) AS total, count(*) FILTER (WHERE status = 'RUNNING') AS active
            FROM jobs WHERE user_id = %s
        """, (user_id,)).fetchone()
        if counts["total"] >= MAX_JOBS_PER_USER:
            raise HTTPException(409, "Досягнуто ліміт у 20 задач. Видаліть старі задачі з історії.")
        if counts["active"] >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(429, "Ви вже обробляєте два зображення.", headers={"Retry-After": "2"})
        connection.execute("""
            INSERT INTO jobs(id, user_id, status, target_width, target_height)
            VALUES (%s, %s, 'RUNNING', %s, %s)
        """, (job_id, user_id, width, height))
    try:
        result, actual_width, actual_height = resize_image(data, width, height)
        if len(result) > MAX_RESULT_BYTES:
            raise HTTPException(413, "Результат перевищує 20 MiB. Оберіть меншу рамку.")
        with database() as connection:
            connection.execute("""
                UPDATE jobs SET status = 'COMPLETED', result = %s, width = %s, height = %s,
                    finished_at = now() WHERE id = %s
            """, (result, actual_width, actual_height, job_id))
        return result, actual_width, actual_height, job_id
    except Exception as error:
        message = error.detail if isinstance(error, HTTPException) else "Не вдалося обробити зображення."
        with database() as connection:
            connection.execute("UPDATE jobs SET status = 'FAILED', error = %s, finished_at = now() WHERE id = %s",
                               (message, job_id))
        raise


def owned_job(connection, user_id, job_id, fields=METADATA):
    job = connection.execute(f"SELECT {fields} FROM jobs WHERE id = %s AND user_id = %s",
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
        if job["status"] == "RUNNING":
            raise HTTPException(409, "Дочекайтеся завершення обробки.")
        connection.execute("DELETE FROM jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
