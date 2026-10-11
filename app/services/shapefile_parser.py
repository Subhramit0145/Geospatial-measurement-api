"""
Shapefile Parser Service.

Handles reading zipped ESRI Shapefiles (.shp, .shx, .dbf, .prj) without requiring
system-level GDAL / C++ binaries by using the pure-Python `pyshp` library and `shapely`.
Supports nested folder structures inside zip archives, case-insensitive extensions,
and automatic projection extraction from .prj files via `pyproj`.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pyproj
import shapefile
from shapely.geometry import shape as to_shapely_shape
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)


class ShapefileParseError(Exception):
    """Raised when a Shapefile archive is invalid or unreadable."""


def _parse_prj_content(prj_text: str) -> Optional[str]:
    """
    Attempt to parse ESRI WKT from a .prj file into a standardized EPSG or CRS string.
    """
    prj_text = prj_text.strip()
    if not prj_text:
        return None

    try:
        crs = pyproj.CRS.from_user_input(prj_text)
        epsg = crs.to_epsg()
        if epsg:
            return f"EPSG:{epsg}"
        # Fallback to standard identifier or name if no exact EPSG code exists
        if crs.name:
            return crs.name
        return "UNKNOWN_PROJECTED"
    except Exception as exc:
        logger.warning("Could not parse .prj content '%s': %s", prj_text[:60], exc)
        return None


def _sanitize_record_value(val: Any) -> Any:
    """Ensure DBF attribute values (dates, byte strings, etc.) are JSON-serializable."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, (int, float, str, bool)) or val is None:
        return val
    return str(val)


def parse_shapefile_zip(zip_path: Path) -> dict[str, Any]:
    """
    Parse a zipped shapefile archive.

    Parameters
    ----------
    zip_path : Path
        Filesystem path to the .zip archive.

    Returns
    -------
    dict with:
        - "crs": str | None (e.g. "EPSG:4326")
        - "features": list of feature dicts (index, geometry_type, geometry_wkt, properties, etc.)
    """
    if not zipfile.is_zipfile(zip_path):
        raise ShapefileParseError("Uploaded file is not a valid zip archive.")

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        # Find .shp file inside the zip (supporting subdirectories)
        shp_candidates = [n for n in namelist if n.lower().endswith(".shp") and not n.startswith("__MACOSX/")]
        if not shp_candidates:
            raise ShapefileParseError(
                "The zip archive does not contain a valid .shp file. "
                "Ensure your zipped Shapefile contains .shp, .shx, and .dbf files."
            )

        shp_entry = shp_candidates[0]
        prefix = shp_entry[:-4]  # path without .shp extension

        # Locate corresponding shx and dbf entries (case-insensitive)
        def find_entry(ext: str) -> Optional[str]:
            target = f"{prefix.lower()}{ext.lower()}"
            for name in namelist:
                if name.lower() == target:
                    return name
            # Also try matching basename regardless of folder
            base = Path(prefix).name.lower()
            for name in namelist:
                if Path(name).stem.lower() == base and Path(name).suffix.lower() == ext.lower():
                    return name
            return None

        dbf_entry = find_entry(".dbf")
        shx_entry = find_entry(".shx")
        prj_entry = find_entry(".prj")

        if not dbf_entry:
            raise ShapefileParseError(
                f"Missing required .dbf attribute table for '{Path(shp_entry).name}'."
            )

        # Read CRS from .prj if available
        crs_str: Optional[str] = None
        if prj_entry:
            try:
                prj_bytes = zf.read(prj_entry)
                prj_text = prj_bytes.decode("utf-8", errors="replace")
                crs_str = _parse_prj_content(prj_text)
            except Exception as exc:
                logger.warning("Failed reading .prj file: %s", exc)

        # If no .prj exists, default to EPSG:4326 (WGS84 standard geographic)
        if not crs_str:
            crs_str = "EPSG:4326"

        shp_bytes = io.BytesIO(zf.read(shp_entry))
        dbf_bytes = io.BytesIO(zf.read(dbf_entry))
        shx_bytes = io.BytesIO(zf.read(shx_entry)) if shx_entry else None

        try:
            reader = shapefile.Reader(
                shp=shp_bytes,
                dbf=dbf_bytes,
                shx=shx_bytes,
                encoding="utf-8",
                encodingErrors="replace",
            )
        except Exception as exc:
            raise ShapefileParseError(f"Failed to open Shapefile reader: {exc}") from exc

        features: list[dict[str, Any]] = []

        for idx, shape_rec in enumerate(reader.iterShapeRecords()):
            shape_obj = shape_rec.shape

            # Handle Null/empty shapes gracefully
            if shape_obj.shapeType == shapefile.NULL or not shape_obj.points:
                continue

            try:
                geo_iface = shape_obj.__geo_interface__
                geom: BaseGeometry = to_shapely_shape(geo_iface)
            except Exception as exc:
                logger.warning("Failed to construct geometry for shape index %d: %s", idx, exc)
                continue

            if geom.is_empty:
                continue

            # Extract properties from dbf record
            raw_props = shape_rec.record.as_dict()
            sanitized_props = {
                k: _sanitize_record_value(v) for k, v in raw_props.items()
            }

            features.append({
                "index": idx,
                "geometry_type": geom.geom_type,
                "geometry_wkt": geom.wkt,
                "geometry_geojson": geo_iface,
                "properties": sanitized_props,
            })

        logger.info(
            "Parsed Shapefile '%s': %d features, CRS: %s",
            Path(shp_entry).name,
            len(features),
            crs_str,
        )

        return {
            "crs": crs_str,
            "features": features,
        }
