"""Етап 2: одна операція зі зображенням та статична сторінка."""

import os
import socket
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .image_service import resize_image
from .limits import MAX_FILE_BYTES, MAX_OUTPUT_SIDE
from .middleware import UploadBodyLimitMiddleware

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
INSTANCE_ID = os.getenv("INSTANCE_ID") or socket.gethostname()

app = FastAPI(title="Image Processing Studio", version="0.2.0")
app.add_middleware(UploadBodyLimitMiddleware)


class HealthResponse(BaseModel):
    status: str
    service: str
    instance_id: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    # Це перевірка API; перевірки БД та черги додамо разом із ними.
    return HealthResponse(
        status="ok", service="image-processing-studio", instance_id=INSTANCE_ID
    )


@app.post("/api/images/resize", responses={200: {"content": {"image/png": {}}}})
async def resize(
    request: Request,
    file: Annotated[UploadFile, File(description="Одне фото JPG, PNG або WebP до 10 MiB")],
    width: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
    height: Annotated[int, Form(ge=1, le=MAX_OUTPUT_SIDE)],
) -> Response:
    form = await request.form()
    # FastAPI вже розібрав форму. Не дозволяємо додаткові файли чи дублікати.
    if set(form.keys()) != {"file", "width", "height"} or any(
        len(form.getlist(key)) != 1 for key in form.keys()
    ):
        raise HTTPException(422, "Надішліть рівно один файл та по одному значенню width і height.")
    data = await file.read(MAX_FILE_BYTES + 1)
    # Pillow не виконується в event loop: health та інші HTTP-запити
    # можуть обслуговуватися паралельно. Celery додамо окремим етапом.
    result, actual_width, actual_height = await run_in_threadpool(
        resize_image, data, width, height
    )
    return Response(
        content=result,
        media_type="image/png",
        headers={
            "Content-Disposition": 'attachment; filename="resized-image.png"',
            "Cache-Control": "no-store",
            "X-Image-Width": str(actual_width),
            "X-Image-Height": str(actual_height),
            "X-Instance-ID": INSTANCE_ID,
        },
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
