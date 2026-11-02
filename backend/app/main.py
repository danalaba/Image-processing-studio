"""Етап 5: спільний стан для кількох API та фонових workers."""

import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import User, router as auth_router
from .database import database, initialize
from .jobs import create_job, router as jobs_router
from .limits import MAX_FILE_BYTES, MAX_OUTPUT_SIDE, MAX_FILES_PER_JOB, MAX_BATCH_BYTES
from .middleware import UploadBodyLimitMiddleware

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
INSTANCE_ID = os.getenv("INSTANCE_ID") or socket.gethostname()

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(initialize)
    yield


app = FastAPI(title="Image Processing Studio", version="0.5.0", lifespan=lifespan)
app.add_middleware(UploadBodyLimitMiddleware)
app.include_router(auth_router)
app.include_router(jobs_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Never echo passwords or uploaded contents in validation responses.
    return JSONResponse(status_code=422, content={"detail": [
        {key: value for key, value in item.items() if key in ("loc", "msg", "type")}
        for item in error.errors()
    ]})


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Instance-ID"] = INSTANCE_ID
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
    return response


class HealthResponse(BaseModel):
    status: str
    service: str
    instance_id: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    with database() as connection:
        connection.execute("SELECT 1")
    return HealthResponse(
        status="ok", service="image-processing-studio", instance_id=INSTANCE_ID
    )


@app.post("/api/jobs", status_code=202)
@app.post("/api/images/resize", status_code=202, deprecated=True)
async def resize(
    request: Request,
    user: User,
    file: Annotated[list[UploadFile], File(description="1–10 фото, до 10 MiB кожне й 30 MiB разом")],
    width: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
    height: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
) -> dict:
    form = await request.form()
    # Repeated 'file' fields are the batch; dimensions must still occur once.
    if set(form.keys()) != {"file", "width", "height"} or any(
        len(form.getlist(key)) != 1 for key in ("width", "height")
    ):
        raise HTTPException(422, "Надішліть фото у полях file та по одному значенню width і height.")
    if not 1 <= len(file) <= MAX_FILES_PER_JOB:
        raise HTTPException(413, "Оберіть від 1 до 10 фото.")
    data, total = [], 0
    for upload in file:
        item = await upload.read(MAX_FILE_BYTES + 1)
        total += len(item)
        if len(item) > MAX_FILE_BYTES or total > MAX_BATCH_BYTES:
            raise HTTPException(413, "Максимум 10 MiB на фото та 30 MiB на весь пакет.")
        data.append(item)
    # Validation/admission run outside the event loop; full processing is Celery-only.
    job = await run_in_threadpool(
        create_job, user["id"], data, width, height, [upload.filename or "image" for upload in file]
    )
    return job


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
