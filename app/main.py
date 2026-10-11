"""
Application Entry Point.

Configures FastAPI application, sets up CORS middleware, registers routers,
binds exception handlers, and prepares database schema.
"""

from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers.files import router as files_router
from app.utils.exceptions import (
    FileNotFoundError_,
    UnsupportedFileError,
    file_not_found_handler,
    unsupported_file_handler,
)

# Structured application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("geospatial_api")

app = FastAPI(
    title="Geospatial File Measurement API",
    description="""
    A high-performance backend service for uploading, parsing, and measuring geospatial files:
    
    * **Supported Inputs**: Zipped Shapefiles (`.zip`) and Keyhole Markup Language (`.kml`) files.
    * **Dynamic Projection**: Detects geographic coordinates (e.g. WGS84 EPSG:4326) and adaptively transforms geometries to optimal local UTM zones for distortion-free metric calculations.
    * **Geometric Measurements**:
        - **Polygon / MultiPolygon**: Physical Area ($m^2$)
        - **LineString / MultiLineString**: Physical Length ($m$)
        - **Point / MultiPoint**: Gracefully preserved without measurement
    * **Open Standards**: Fully compatible with OGC standards and GeoJSON exports.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for frontend clients / GIS web viewers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database tables on startup
Base.metadata.create_all(bind=engine)

# Register route modules
app.include_router(files_router)

# Register specialized exception handlers
app.add_exception_handler(FileNotFoundError_, file_not_found_handler)
app.add_exception_handler(UnsupportedFileError, unsupported_file_handler)


@app.get("/health", tags=["system"], summary="Health Check")
def health_check():
    """Liveness probe verifying that the service is running and ready."""
    return {
        "status": "healthy",
        "service": "geospatial-measurement-api",
        "version": "1.0.0",
    }


@app.get("/", tags=["system"], include_in_schema=False)
def root():
    """Root redirect / welcome endpoint."""
    return {
        "message": "Welcome to the Geospatial File Measurement API",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }
