"""Етап 4: асинхронна обробка зі статусом, прогресом і скасуванням."""

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
from .limits import MAX_FILE_BYTES, MAX_OUTPUT_SIDE
from .middleware import UploadBodyLimitMiddleware

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
INSTANCE_ID = os.getenv("INSTANCE_ID") or socket.gethostname()

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(initialize)
    yield


app = FastAPI(title="Image Processing Studio", version="0.4.0", lifespan=lifespan)
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
    file: Annotated[UploadFile, File(description="Одне фото JPG, PNG або WebP до 10 MiB")],
    width: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
    height: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
) -> dict:
    form = await request.form()
    # FastAPI вже розібрав форму. Не дозволяємо додаткові файли чи дублікати.
    if set(form.keys()) != {"file", "width", "height"} or any(
        len(form.getlist(key)) != 1 for key in form.keys()
    ):
        raise HTTPException(422, "Надішліть рівно один файл та по одному значенню width і height.")
    data = await file.read(MAX_FILE_BYTES + 1)
    # Validation/admission run outside the event loop; full processing is Celery-only.
    job = await run_in_threadpool(
        create_job, user["id"], data, width, height
    )
    return job


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
