"""
Pydantic API schemas for request validation and response serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── File-level schemas ──────────────────────────────────────────────

class FileUploadResponse(BaseModel):
    """Returned upon successful upload and processing of a geospatial file."""

    id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original filename")
    feature_count: int = Field(..., description="Total number of extracted features")
    crs: Optional[str] = Field(None, description="Source Coordinate Reference System")
    status: str = Field(..., description="Processing status (e.g. COMPLETED, FAILED)")

    model_config = {"from_attributes": True}


class FileInfoResponse(BaseModel):
    """File metadata response matching specification."""

    id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original filename")
    feature_count: int = Field(..., description="Total feature count")
    crs: Optional[str] = Field(None, description="Detected source CRS")
    status: str = Field(..., description="Processing status")
    error_message: Optional[str] = Field(None, description="Error detail if failed")
    created_at: Optional[datetime] = Field(None, description="Timestamp of upload")

    model_config = {"from_attributes": True}


# ── Feature & Measurement schemas ───────────────────────────────────

class FeatureMeasurement(BaseModel):
    """Detailed measurement and geospatial metadata for a single feature."""

    feature_index: int = Field(..., description="0-indexed feature order in source file")
    geometry_type: str = Field(..., description="Geometry type (e.g. Polygon, LineString, Point)")
    geometry: Optional[dict[str, Any]] = Field(None, description="GeoJSON geometry object")
    geometry_wkt: Optional[str] = Field(None, description="Well-Known Text (WKT) representation")
    crs: Optional[str] = Field(None, description="Source CRS")
    measurement_type: Optional[str] = Field(None, description="'area' for Polygons, 'length' for LineStrings, null for Points")
    measurement_value: Optional[float] = Field(None, description="Calculated metric value in projected CRS")
    measurement_unit: Optional[str] = Field(None, description="'sq_meters' or 'meters', null for Points")
    projected_crs: Optional[str] = Field(None, description="Target projected CRS used for calculation")
    properties: Optional[dict[str, Any]] = Field(default_factory=dict, description="Feature attributes")


class MeasurementSummary(BaseModel):
    """Aggregate calculation summary for the dataset."""

    total_features: int = Field(..., description="Total feature count")
    polygons_measured: int = Field(0, description="Polygons measured for area")
    linestrings_measured: int = Field(0, description="LineStrings measured for length")
    points_skipped: int = Field(0, description="Points skipped (no measurement required)")
    unsupported_skipped: int = Field(0, description="Unsupported geometries skipped")
    total_area_sq_meters: Optional[float] = Field(None, description="Sum of all polygon areas in m²")
    total_length_meters: Optional[float] = Field(None, description="Sum of all linestring lengths in m")


class MeasurementsResponse(BaseModel):
    """Top-level measurements payload for an uploaded file."""

    file_id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original filename")
    crs: Optional[str] = Field(None, description="Source CRS")
    feature_count: int = Field(..., description="Total features in file")
    summary: Optional[MeasurementSummary] = Field(None, description="Aggregated metric summary")
    measurements: list[FeatureMeasurement] = Field(..., description="List of per-feature measurements")


class FileListResponse(BaseModel):
    """Paginated list of files."""

    total: int
    files: list[FileInfoResponse]
