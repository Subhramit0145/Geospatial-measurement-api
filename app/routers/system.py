"""
System Telemetry, Metrics & Cache Management Router.

Exposes endpoints for monitoring performance, cache efficiency,
and database connection pool status under heavy request traffic.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db, get_db_pool_status
from app.services.cache import cache

router = APIRouter(prefix="/api/system", tags=["system-metrics"])

_START_TIME = time.time()
_REQUEST_COUNTER = 0


def increment_request_counter():
    global _REQUEST_COUNTER
    _REQUEST_COUNTER += 1


@router.get(
    "/metrics",
    summary="Get System & Performance Metrics",
    description="Returns real-time telemetry including cache hit ratio, database pool status, memory, and uptime.",
)
def get_system_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    # Check DB liveness
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    # Process memory if psutil or os available
    memory_mb = None
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        pass

    uptime_seconds = round(time.time() - _START_TIME, 2)

    return {
        "status": "operational",
        "uptime_seconds": uptime_seconds,
        "total_requests_processed": _REQUEST_COUNTER,
        "memory_rss_mb": memory_mb,
        "database": {
            "status": db_status,
            "pool": get_db_pool_status(),
        },
        "cache": cache.get_stats(),
    }


@router.post(
    "/cache/clear",
    status_code=status.HTTP_200_OK,
    summary="Purge All Caches",
    description="Flushes in-memory and Redis caches to synchronize with raw storage.",
)
def clear_system_cache() -> dict[str, str]:
    cache.clear()
    return {"message": "All caches cleared successfully"}
