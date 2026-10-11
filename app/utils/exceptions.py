"""Custom exception classes and FastAPI exception handlers."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class FileNotFoundError_(Exception):
    """Raised when a requested GeoFile id does not exist in the database."""

    def __init__(self, file_id: str) -> None:
        self.file_id = file_id
        super().__init__(f"File with id '{file_id}' not found")


class UnsupportedFileError(Exception):
    """Raised when the uploaded file type is not supported."""


# ── FastAPI exception handlers ───────────────────────────────────────

async def file_not_found_handler(request: Request, exc: FileNotFoundError_) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)},
    )


async def unsupported_file_handler(request: Request, exc: UnsupportedFileError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )
