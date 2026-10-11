"""
Unified File Parser Service.

Orchestrates parsing of incoming geospatial files:
- `.zip`: Dispatches to `shapefile_parser`
- `.kml`: Dispatches to `kml_parser`

Uses pure Python libraries (pyshp, ElementTree, Shapely, PyProj) ensuring
seamless cross-platform operation without GDAL compilation or binary C-binding headaches.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.kml_parser import KMLParseError, parse_kml_file
from app.services.shapefile_parser import ShapefileParseError, parse_shapefile_zip

logger = logging.getLogger(__name__)


class FileParseError(Exception):
    """Raised when an uploaded geospatial file cannot be parsed or is invalid."""


def parse_file(file_path: Path) -> dict[str, Any]:
    """
    Parse an uploaded geospatial file and extract standard features.

    Parameters
    ----------
    file_path : Path
        Path to the saved uploaded file.

    Returns
    -------
    dict with:
        - "crs": str | None (standardized CRS identifier, e.g. "EPSG:4326")
        - "features": list of feature dicts:
            - "index": int
            - "geometry_type": str
            - "geometry_wkt": str
            - "geometry_geojson": dict
            - "properties": dict
    """
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".zip":
            return parse_shapefile_zip(file_path)
        elif suffix == ".kml":
            return parse_kml_file(file_path)
        else:
            raise FileParseError(
                f"Unsupported file format '{suffix}'. Supported formats: .zip (Shapefile) or .kml"
            )
    except (ShapefileParseError, KMLParseError) as exc:
        logger.warning("Parser validation failed for '%s': %s", file_path.name, exc)
        raise FileParseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error parsing '%s': %s", file_path.name, exc)
        raise FileParseError(f"Could not process geospatial file: {exc}") from exc
