"""Small ASGI ingress guard; counts actual bytes even without Content-Length."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class InferenceBodyLimitMiddleware:
    """Bound JSON request size before FastAPI reads or parses the body."""

    def __init__(self, app: ASGIApp, max_bytes: int = 16_384) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        if not str(scope.get("path", "")).startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if content_type != b"application/json":
            await self._error(send, 415, "Content-Type must be application/json.")
            return

        supplied_length = headers.get(b"content-length")
        if supplied_length is not None:
            try:
                length = int(supplied_length)
            except ValueError:
                await self._error(send, 400, "Invalid Content-Length.")
                return
            if length < 0:
                await self._error(send, 400, "Invalid Content-Length.")
                return
            if length > self.max_bytes:
                await self._error(send, 413, "Request body is too large.")
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._error(send, 413, "Request body is too large.")
                return
            if not message.get("more_body", False):
                break

        buffered = bytes(body)
        consumed = False

        async def replay() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _error(send: Send, status_code: int, detail: str) -> None:
        content = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(content)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": content})
