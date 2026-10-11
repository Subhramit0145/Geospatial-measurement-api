"""
Router for Geospatial File API endpoints.

Endpoints:
- POST   /api/files/                     Upload and process Shapefile (.zip) or KML (.kml)
- GET    /api/files/                     List uploaded files (paginated)
- GET    /api/files/{file_id}/           Get metadata of uploaded file
- GET    /api/files/{file_id}/measurements/ Get computed measurements per feature
- GET    /api/files/{file_id}/geojson/   Export parsed features as GeoJSON FeatureCollection
- DELETE /api/files/{file_id}/           Delete file and associated measurements
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from shapely import wkt
from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Feature, GeoFile
from app.schemas import (
    FeatureMeasurement,
    FileInfoResponse,
    FileListResponse,
    FileUploadResponse,
    MeasurementSummary,
    MeasurementsResponse,
)
from app.services.file_parser import FileParseError, parse_file
from app.services.measurement import compute_measurement
from app.utils.exceptions import FileNotFoundError_, UnsupportedFileError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["geospatial-files"])

ALLOWED_EXTENSIONS = {".zip", ".kml"}


def _save_upload(upload: UploadFile) -> Path:
    """
    Safely persist the uploaded file to disk with filename sanitization.
    """
    raw_name = upload.filename or "uploaded_file"
    safe_name = Path(raw_name).name  # prevent directory traversal attacks
    suffix = Path(safe_name).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file format '{suffix}'. Allowed formats: .zip (Shapefile), .kml"
        )

    upload_dir = settings.ensure_upload_dir()
    dest = upload_dir / safe_name

    # Avoid collisions with a timestamp/counter suffix
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{Path(safe_name).stem}_{counter}{suffix}"
        counter += 1

    total_bytes = 0
    with open(dest, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):  # 1MB chunks
            total_bytes += len(chunk)
            if total_bytes > settings.max_upload_bytes:
                # Clean up partial file
                f.close()
                if dest.exists():
                    dest.unlink()
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds maximum allowed size of {settings.max_upload_size_mb} MB",
                )
            f.write(chunk)

    return dest


# ── POST /api/files/ ────────────────────────────────────────────────

@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a geospatial file",
    description="Upload and process a zipped Shapefile (.zip) or a KML file (.kml).",
)
def upload_file(
    file: UploadFile = File(..., description="Zipped Shapefile (.zip) or KML (.kml) file"),
    db: Session = Depends(get_db),
):
    saved_path = _save_upload(file)

    # Initialize file record in database
    geo_file = GeoFile(
        filename=file.filename or saved_path.name,
        status="PROCESSING",
    )
    db.add(geo_file)
    db.commit()
    db.refresh(geo_file)

    try:
        # Extract features and CRS using unified parser
        parsed = parse_file(saved_path)
        crs_str = parsed["crs"]
        raw_features = parsed["features"]

        geo_file.original_crs = crs_str
        geo_file.feature_count = len(raw_features)

        # Process each feature and compute geometric measurements
        for feat in raw_features:
            geom = wkt.loads(feat["geometry_wkt"])
            measurement_res = compute_measurement(geom, feat["geometry_type"], crs_str)

            db_feature = Feature(
                file_id=geo_file.id,
                feature_index=feat["index"],
                geometry_type=feat["geometry_type"],
                geometry_wkt=feat["geometry_wkt"],
                measurement_value=measurement_res.value,
                measurement_unit=measurement_res.unit,
                measurement_type=measurement_res.measurement_type,
                projected_crs=measurement_res.projected_crs,
                properties_json=json.dumps(feat.get("properties", {})),
            )
            db.add(db_feature)

        geo_file.status = "COMPLETED"
        db.commit()
        db.refresh(geo_file)

    except (FileParseError, UnsupportedFileError) as exc:
        geo_file.status = "FAILED"
        geo_file.error_message = str(exc)
        db.commit()
        raise UnsupportedFileError(str(exc))
    except Exception as exc:
        geo_file.status = "FAILED"
        geo_file.error_message = str(exc)
        db.commit()
        logger.exception("Unexpected error processing file %s: %s", geo_file.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while processing the file: {exc}",
        )

    return FileUploadResponse(
        id=geo_file.id,
        filename=geo_file.filename,
        feature_count=geo_file.feature_count,
        crs=geo_file.original_crs,
        status=geo_file.status,
    )


# ── GET /api/files/ ─────────────────────────────────────────────────

@router.get(
    "/",
    response_model=FileListResponse,
    summary="List uploaded files",
    description="Retrieve a paginated list of all uploaded geospatial files.",
)
def list_files(
    skip: int = Query(0, ge=0, description="Offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
):
    total = db.query(GeoFile).count()
    items = (
        db.query(GeoFile)
        .order_by(GeoFile.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return FileListResponse(
        total=total,
        files=[
            FileInfoResponse(
                id=f.id,
                filename=f.filename,
                feature_count=f.feature_count,
                crs=f.original_crs,
                status=f.status,
                error_message=f.error_message,
                created_at=f.created_at,
            )
            for f in items
        ],
    )


# ── GET /api/files/{file_id}/ ──────────────────────────────────────

@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Get file information",
    description="Retrieve metadata about an uploaded geospatial file by ID.",
)
def get_file_info(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(GeoFile).filter(GeoFile.id == file_id).first()
    if not geo_file:
        raise FileNotFoundError_(file_id)

    return FileInfoResponse(
        id=geo_file.id,
        filename=geo_file.filename,
        feature_count=geo_file.feature_count,
        crs=geo_file.original_crs,
        status=geo_file.status,
        error_message=geo_file.error_message,
        created_at=geo_file.created_at,
    )


# ── GET /api/files/{file_id}/measurements/ ─────────────────────────

@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get feature measurements",
    description="Retrieve geometric measurements (area / length) for all features in the file.",
)
def get_measurements(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(GeoFile).filter(GeoFile.id == file_id).first()
    if not geo_file:
        raise FileNotFoundError_(file_id)

    features = (
        db.query(Feature)
        .filter(Feature.file_id == file_id)
        .order_by(Feature.feature_index.asc())
        .all()
    )

    measurements_list: list[FeatureMeasurement] = []
    polygons_count = 0
    linestrings_count = 0
    points_count = 0
    unsupported_count = 0
    total_area: float = 0.0
    total_length: float = 0.0

    for feat in features:
        props = {}
        if feat.properties_json:
            try:
                props = json.loads(feat.properties_json)
            except Exception:
                props = {}

        # Reconstruct GeoJSON geometry
        geo_dict = None
        try:
            geom_obj = wkt.loads(feat.geometry_wkt)
            geo_dict = mapping(geom_obj)
        except Exception:
            pass

        # Aggregate metrics
        if feat.measurement_type == "area" and feat.measurement_value is not None:
            polygons_count += 1
            total_area += feat.measurement_value
        elif feat.measurement_type == "length" and feat.measurement_value is not None:
            linestrings_count += 1
            total_length += feat.measurement_value
        elif "Point" in feat.geometry_type:
            points_count += 1
        else:
            unsupported_count += 1

        measurements_list.append(
            FeatureMeasurement(
                feature_index=feat.feature_index,
                geometry_type=feat.geometry_type,
                geometry=geo_dict,
                geometry_wkt=feat.geometry_wkt,
                crs=geo_file.original_crs,
                measurement_type=feat.measurement_type,
                measurement_value=feat.measurement_value,
                measurement_unit=feat.measurement_unit,
                projected_crs=feat.projected_crs,
                properties=props,
            )
        )

    summary = MeasurementSummary(
        total_features=len(features),
        polygons_measured=polygons_count,
        linestrings_measured=linestrings_count,
        points_skipped=points_count,
        unsupported_skipped=unsupported_count,
        total_area_sq_meters=round(total_area, 4) if polygons_count > 0 else None,
        total_length_meters=round(total_length, 4) if linestrings_count > 0 else None,
    )

    return MeasurementsResponse(
        file_id=geo_file.id,
        filename=geo_file.filename,
        crs=geo_file.original_crs,
        feature_count=geo_file.feature_count,
        summary=summary,
        measurements=measurements_list,
    )


# ── GET /api/files/{file_id}/geojson/ ──────────────────────────────

@router.get(
    "/{file_id}/geojson/",
    summary="Export as GeoJSON FeatureCollection",
    description="Export all parsed features with their measurements as standard GeoJSON.",
)
def export_geojson(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(GeoFile).filter(GeoFile.id == file_id).first()
    if not geo_file:
        raise FileNotFoundError_(file_id)

    features = (
        db.query(Feature)
        .filter(Feature.file_id == file_id)
        .order_by(Feature.feature_index.asc())
        .all()
    )

    geojson_features = []
    for feat in features:
        props = {}
        if feat.properties_json:
            try:
                props = json.loads(feat.properties_json)
            except Exception:
                props = {}

        # Add measurement fields to properties
        props["_feature_index"] = feat.feature_index
        props["_measurement_type"] = feat.measurement_type
        props["_measurement_value"] = feat.measurement_value
        props["_measurement_unit"] = feat.measurement_unit
        props["_projected_crs"] = feat.projected_crs

        try:
            geom_obj = wkt.loads(feat.geometry_wkt)
            geom_dict = mapping(geom_obj)
        except Exception:
            continue

        geojson_features.append({
            "type": "Feature",
            "geometry": geom_dict,
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "name": geo_file.filename,
        "crs": {
            "type": "name",
            "properties": {"name": geo_file.original_crs or "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": geojson_features,
    }


# ── DELETE /api/files/{file_id}/ ───────────────────────────────────

@router.delete(
    "/{file_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a file",
    description="Delete an uploaded file record, its extracted features, and local disk copy.",
)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(GeoFile).filter(GeoFile.id == file_id).first()
    if not geo_file:
        raise FileNotFoundError_(file_id)

    # Delete local file if it exists
    upload_dir = settings.ensure_upload_dir()
    for candidate in upload_dir.glob(f"{Path(geo_file.filename).stem}*"):
        try:
            if candidate.is_file():
                candidate.unlink()
        except Exception as exc:
            logger.warning("Could not delete file %s: %s", candidate, exc)

    db.delete(geo_file)
    db.commit()
    return None
