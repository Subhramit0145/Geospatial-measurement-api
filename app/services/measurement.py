"""
Measurement Service.

Computes physical metric measurements for geospatial features:
- Polygon / MultiPolygon       -> Area (square meters, sq_meters)
- LineString / MultiLineString -> Length (meters)
- Point / MultiPoint           -> Skipped gracefully (null)
- Other / Unsupported          -> Handled gracefully without raising exceptions

Performs automatic projection into an optimal local metric CRS (e.g. UTM) before
measurement so results are accurate physical quantities instead of degree approximations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyproj
import shapely
from shapely.geometry.base import BaseGeometry

from app.services.crs_handler import determine_target_projected_crs

logger = logging.getLogger(__name__)

POLYGON_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString"}
SUPPORTED_MEASUREMENT_TYPES = POLYGON_TYPES | LINE_TYPES


@dataclass
class MeasurementResult:
    """Encapsulates the measurement outcome for a single feature."""

    value: Optional[float] = None
    unit: Optional[str] = None
    measurement_type: Optional[str] = None
    projected_crs: Optional[str] = None


def reproject_geometry(
    geometry: BaseGeometry,
    source_crs: str,
    target_crs: str,
) -> BaseGeometry:
    """
    Transform a geometry between coordinate reference systems using PyProj.
    Uses always_xy=True to enforce (lon, lat) / (x, y) order consistently.
    """
    transformer = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)

    try:
        # Modern Shapely 2.0+ vectorized coordinate transformation
        return shapely.transform(
            geometry,
            lambda coords: np.column_stack(transformer.transform(coords[:, 0], coords[:, 1])),
        )
    except Exception as exc:
        logger.debug("Vectorized transform failed, falling back to shapely.ops.transform: %s", exc)
        from shapely.ops import transform as ops_transform
        return ops_transform(transformer.transform, geometry)


def compute_measurement(
    geometry: BaseGeometry,
    geometry_type: str,
    source_crs: Optional[str],
) -> MeasurementResult:
    """
    Calculate area or length for a given geometry if supported.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry instance.
    geometry_type : str
        e.g., 'Polygon', 'LineString', 'Point'
    source_crs : Optional[str]
        Original CRS string (e.g. 'EPSG:4326')

    Returns
    -------
    MeasurementResult
        Populated with metric value and unit, or None if unsupported (e.g. Point).
    """
    if geometry_type not in SUPPORTED_MEASUREMENT_TYPES:
        return MeasurementResult()

    # Repair topological anomalies (e.g. self-intersections) if necessary
    geom_to_measure = geometry
    if not geom_to_measure.is_valid:
        try:
            geom_to_measure = shapely.make_valid(geom_to_measure)
        except Exception:
            pass

    target_crs = determine_target_projected_crs(geom_to_measure, source_crs)

    if target_crs is not None:
        src_crs = source_crs or "EPSG:4326"
        try:
            projected_geom = reproject_geometry(geom_to_measure, src_crs, target_crs)
        except Exception as exc:
            logger.warning("Reprojection from %s to %s failed: %s", src_crs, target_crs, exc)
            projected_geom = geom_to_measure
            target_crs = source_crs
    else:
        projected_geom = geom_to_measure
        target_crs = source_crs

    if geometry_type in POLYGON_TYPES:
        area_val = round(float(projected_geom.area), 4)
        return MeasurementResult(
            value=area_val,
            unit="sq_meters",
            measurement_type="area",
            projected_crs=target_crs,
        )

    if geometry_type in LINE_TYPES:
        length_val = round(float(projected_geom.length), 4)
        return MeasurementResult(
            value=length_val,
            unit="meters",
            measurement_type="length",
            projected_crs=target_crs,
        )

    return MeasurementResult()
