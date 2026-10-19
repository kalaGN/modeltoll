"""Shared bounded byte reading; callers retain authentication and parse ordering."""
from typing import Any

from fastapi import HTTPException, Request


async def read_limited_body(request: Request, max_bytes: int, *, detail: Any) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(413, detail=detail)
        body.extend(chunk)
    return bytes(body)
