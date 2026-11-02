"""Idempotent claims, cooperative cancellation and recovery of abandoned work."""
import logging
import time
import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile, ZIP_STORED
from uuid import UUID, uuid4

from billiard.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_init
from fastapi import HTTPException

from .database import database, initialize
from .image_service import resize_image
from .limits import MAX_JOB_SECONDS, MAX_RESULT_BYTES, MAX_ARCHIVE_BYTES
from .queue import celery, publish_job

logger = logging.getLogger(__name__)


@worker_init.connect
def prepare_worker(**kwargs):
    initialize()


class JobCancelled(Exception):
    pass


def process_job(job_id, worker_id):
    job_id, claim_id = UUID(str(job_id)), uuid4()
    with database() as connection:
        job = connection.execute("""
            UPDATE jobs SET status = 'RUNNING', progress = 5, stage = 'validating',
                started_at = now(), worker_id = %s, claim_id = %s
            WHERE id = %s AND status = 'QUEUED'
            RETURNING input_data, input_files, file_names, file_count, target_width, target_height
        """, (worker_id, claim_id, job_id)).fetchone()
    if not job:
        return  # Duplicate delivery, cancellation, or already terminal.
    started = time.monotonic()
    completed_files = 0

    def checkpoint(progress, stage):
        if time.monotonic() - started > MAX_JOB_SECONDS:
            raise SoftTimeLimitExceeded()
        with database() as connection:
            current = connection.execute("SELECT status FROM jobs WHERE id = %s AND claim_id = %s FOR UPDATE",
                                         (job_id, claim_id)).fetchone()
            if not current or current["status"] != "RUNNING":
                raise JobCancelled()
            connection.execute("UPDATE jobs SET progress = %s, stage = %s, processed_files = %s WHERE id = %s",
                               (progress, stage, completed_files, job_id))

    try:
        checkpoint(10, "validating")
        files = job["input_files"] if job["input_files"] is not None else [job["input_data"]]
        count = len(files)
        archive_buffer = BytesIO()
        archive = ZipFile(archive_buffer, "w", compression=ZIP_STORED) if count > 1 else None
        try:
            for index, item in enumerate(files):
                def image_checkpoint(progress, stage):
                    overall = progress if count == 1 else int(10 + 80 * (index + progress / 100) / count)
                    checkpoint(overall, stage)
                try:
                    result, width, height = resize_image(bytes(item), job["target_width"], job["target_height"], image_checkpoint)
                    if len(result) > MAX_RESULT_BYTES:
                        raise HTTPException(413, "Результат одного фото перевищує 20 MiB. Оберіть меншу рамку.")
                except HTTPException as error:
                    raise HTTPException(error.status_code, f"Фото {index + 1}: {error.detail}") from None
                if archive is not None:
                    original = job["file_names"][index] if job["file_names"] else "image"
                    # Fixed index keeps duplicates distinct. No client-controlled paths.
                    stem = PurePosixPath(original.replace("\\", "/")).stem
                    stem = re.sub(r"[^\w .-]", "_", stem).strip(". ")[:80] or "image"
                    filename = f"{index + 1:02d}-{stem}.png"
                    if archive_buffer.tell() + len(result) + 2 * len(filename.encode()) + 256 > MAX_ARCHIVE_BYTES:
                        raise HTTPException(413, "ZIP перевищує 50 MiB. Зменште рамку або кількість фото.")
                    archive.writestr(filename, result)
                completed_files = index + 1
                checkpoint(95 if count == 1 else int(10 + 80 * completed_files / count), "saving" if count == 1 else "processed")
            if archive is not None:
                checkpoint(92, "packing")
                archive.close()
                result, width, height = archive_buffer.getvalue(), None, None
                if len(result) > MAX_ARCHIVE_BYTES:
                    raise HTTPException(413, "ZIP перевищує 50 MiB.")
        finally:
            if archive is not None:
                archive.close()
        checkpoint(95, "saving")
        with database() as connection:
            current = connection.execute("SELECT status FROM jobs WHERE id = %s AND claim_id = %s FOR UPDATE",
                                         (job_id, claim_id)).fetchone()
            if not current or current["status"] != "RUNNING":
                raise JobCancelled()
            connection.execute("""
                UPDATE jobs SET status = 'COMPLETED', progress = 100, stage = 'completed',
                    result = %s, width = %s, height = %s, processed_files = file_count,
                    input_data = NULL, input_files = NULL, finished_at = now()
                WHERE id = %s
            """, (result, width, height, job_id))
    except Exception as error:
        cancelled = isinstance(error, JobCancelled)
        message = error.detail if isinstance(error, HTTPException) else "Не вдалося обробити зображення."
        if isinstance(error, SoftTimeLimitExceeded):
            message = "Перевищено час обробки (до 60 секунд)."
        if not cancelled and not isinstance(error, (HTTPException, SoftTimeLimitExceeded)):
            logger.exception("Image job %s failed", job_id)
        with database() as connection:
            # Do not overwrite a terminal state chosen by another process.
            connection.execute("""
                UPDATE jobs SET status = CASE WHEN status = 'CANCELLING' OR %s THEN 'CANCELLED' ELSE 'FAILED' END,
                    stage = CASE WHEN status = 'CANCELLING' OR %s THEN 'cancelled' ELSE 'failed' END,
                    error = CASE WHEN status = 'CANCELLING' OR %s THEN NULL ELSE %s END,
                    input_data = NULL, input_files = NULL, finished_at = now()
                WHERE id = %s AND claim_id = %s AND status IN ('RUNNING','CANCELLING')
            """, (cancelled, cancelled, cancelled, message, job_id, claim_id))


@celery.task(bind=True, name="studio.resize", soft_time_limit=50, time_limit=MAX_JOB_SECONDS)
def resize_task(self, job_id):
    process_job(job_id, self.request.hostname)


@celery.task(name="studio.dispatch", soft_time_limit=25, time_limit=30)
def dispatch_pending():
    with database() as connection:
        connection.execute("""
            UPDATE jobs SET status = CASE WHEN status = 'CANCELLING' THEN 'CANCELLED' ELSE 'FAILED' END,
                stage = CASE WHEN status = 'CANCELLING' THEN 'cancelled' ELSE 'failed' END,
                error = CASE WHEN status = 'CANCELLING' THEN NULL ELSE 'Worker припинив обробку. Створіть задачу повторно.' END,
                input_data = NULL, input_files = NULL, finished_at = now()
            WHERE status IN ('RUNNING','CANCELLING') AND started_at < now() - interval '90 seconds'
        """)
        pending = connection.execute("""
            SELECT id FROM jobs WHERE status = 'QUEUED'
                AND (dispatched_at IS NULL OR dispatched_at < now() - interval '15 seconds')
            ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED
        """).fetchall()
        for job in pending:
            if not publish_job(job["id"]):
                break
            connection.execute("UPDATE jobs SET dispatched_at = now() WHERE id = %s", (job["id"],))
