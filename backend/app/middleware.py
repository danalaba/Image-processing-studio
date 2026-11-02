"""Відсікаємо великий HTTP body до того, як multipart-парсер прочитає файл."""

from starlette.responses import JSONResponse

from .limits import MAX_BODY_BYTES


class UploadBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in ("/api/images/resize", "/api/auth/login", "/api/auth/register"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        try:
            declared_size = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await JSONResponse({"detail": "Некоректний Content-Length."}, status_code=400)(scope, receive, send)
            return

        limit = MAX_BODY_BYTES if scope["path"] == "/api/images/resize" else 16 * 1024
        if declared_size > limit:
            await self.reject(scope, receive, send)
            return

        # На цьому етапі буфер обмежений приблизно 10 MiB. Рахуємо реальні
        # байти також, бо Content-Length може бути відсутній або неправильний.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await self.reject(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def reject(scope, receive, send):
        response = JSONResponse(
            {"detail": "Запит завеликий."},
            status_code=413,
        )
        await response(scope, receive, send)
