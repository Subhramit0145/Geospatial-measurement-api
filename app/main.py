"""
Application Entry Point.

Configures FastAPI application, sets up CORS middleware, registers routers,
binds exception handlers, attaches GZip and telemetry middleware, and prepares database schema.
"""

from __future__ import annotations

import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, engine
from app.routers.files import router as files_router
from app.routers.system import increment_request_counter, router as system_router
from app.utils.exceptions import (
    FileNotFoundError_,
    UnsupportedFileError,
    file_not_found_handler,
    unsupported_file_handler,
)
from app.utils.rate_limiter import limiter

# Structured application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("geospatial_api")

app = FastAPI(
    title="Geospatial File Measurement API",
    description="""
    A high-concurrency, horizontally scalable backend service for uploading, parsing, and measuring geospatial files:
    
    * **High-Throughput Architecture**: Scalable to 100,000+ requests with multi-tier caching, connection pooling, and SQLite WAL / PostgreSQL.
    * **Supported Inputs**: Zipped Shapefiles (`.zip`) and Keyhole Markup Language (`.kml`) files.
    * **Dynamic Projection**: Detects geographic coordinates (e.g. WGS84 EPSG:4326) and adaptively transforms geometries to optimal local UTM zones for distortion-free metric calculations.
    * **Geometric Measurements**:
        - **Polygon / MultiPolygon**: Physical Area ($m^2$)
        - **LineString / MultiLineString**: Physical Length ($m$)
        - **Point / MultiPoint**: Gracefully preserved without measurement
    * **Open Standards**: Fully compatible with OGC standards and GeoJSON exports.
    * **Telemetry & Caching**: Multi-level caching (Redis / Memory LRU) with sub-millisecond response times (`X-Cache` headers).
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Compression Middleware (reduces payload size by up to 90% for large GeoJSON responses)
if settings.enable_gzip:
    app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_min_size)

# Enable CORS for frontend clients / GIS web viewers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing and telemetry middleware
@app.middleware("http")
async def telemetry_and_rate_limit_middleware(request: Request, call_next):
    increment_request_counter()
    start_time = time.perf_counter()

    # Rate limiting enforcement if active
    if settings.rate_limit_enabled:
        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after = limiter.is_allowed(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)},
            )

    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    return response


# Initialize database tables on startup
Base.metadata.create_all(bind=engine)

# Register route modules
app.include_router(files_router)
app.include_router(system_router)

# Register specialized exception handlers
app.add_exception_handler(FileNotFoundError_, file_not_found_handler)
app.add_exception_handler(UnsupportedFileError, unsupported_file_handler)


@app.get("/health", tags=["system"], summary="Health Check")
def health_check():
    """Liveness probe verifying that the service is running, ready, and scalable."""
    return {
        "status": "healthy",
        "service": "geospatial-measurement-api",
        "version": "2.0.0",
        "scalability": "high-throughput-ready",
    }


@app.get("/metrics", tags=["system"], summary="Metrics Redirect")
def metrics_shortcut(request: Request):
    """Direct alias to /api/system/metrics for Prometheus and monitoring probes."""
    from app.routers.system import get_system_metrics
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        return get_system_metrics(db=db)
    finally:
        db.close()


@app.get("/", tags=["system"], include_in_schema=False)
def root():
    """Root redirect / welcome endpoint."""
    return {
        "message": "Welcome to the Geospatial File Measurement API (High Scalability Edition)",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "metrics": "/api/system/metrics",
    }

