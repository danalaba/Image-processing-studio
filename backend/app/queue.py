"""Celery transports IDs only; PostgreSQL is the source of truth."""
import os
import logging

from celery import Celery

logger = logging.getLogger(__name__)

celery = Celery("studio", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
                include=["app.tasks"])
celery.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    task_ignore_result=True, task_default_queue="studio",
    worker_prefetch_multiplier=1, worker_max_tasks_per_child=100,
    task_acks_late=True, task_reject_on_worker_lost=False,
    broker_connection_retry_on_startup=True, broker_connection_timeout=2,
    broker_transport_options={"visibility_timeout": 120, "socket_connect_timeout": 2, "socket_timeout": 2},
    task_publish_retry=False,
    beat_schedule={"recover-and-dispatch": {"task": "studio.dispatch", "schedule": 5.0}},
)


def publish_job(job_id):
    try:
        celery.send_task("studio.resize", args=[str(job_id)], retry=False)
        return True
    except Exception as error:
        # A committed QUEUED row is a durable outbox. Beat dispatches it later,
        # including after a broker outage. Never put image bytes in a message.
        logger.warning("Job %s retained for redispatch (%s)", job_id, type(error).__name__)
        return False
