"""Explicit public error construction; no exception introspection or catch-all."""
from fastapi import HTTPException


def error_content(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def http_error(
    status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None,
) -> HTTPException:
    return HTTPException(status_code, detail=error_content(code, message), headers=headers)
