"""
Coordinate Reference System (CRS) Handler Service.

Implements an adaptive projection strategy for geospatial features:
1. Geographic Coordinate Systems (e.g. EPSG:4326 / WGS 84):
   Coordinates are in angular degrees (latitude/longitude). Calculating Euclidean
   distance or area directly produces physically meaningless values (square degrees).
   We dynamically project each feature to its optimal Universal Transverse Mercator (UTM)
   zone (EPSG:32601-32660 for North, EPSG:32701-32760 for South), which minimizes local
   distortion (< 0.04% along central meridian).
2. Polar Features (|lat| > 84°):
   UTM is undefined beyond 84°N / 80°S. We automatically fall back to Web Mercator (EPSG:3857)
   or Polar Stereographic.
3. Pre-projected Systems:
   If the incoming dataset already has a projected CRS (e.g., State Plane, preexisting UTM),
   it is preserved without unnecessary reprojection overhead.
4. Missing CRS:
   If no CRS was declared, coordinates in range [-180, 180] x [-90, 90] are treated as
   WGS84 geographic and projected to UTM. Larger values are treated as existing projected meters.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from pyproj import CRS
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)


def is_geographic_crs(crs_input: Optional[str]) -> bool:
    """
    Determine if a given CRS string represents an angular/geographic coordinate system.
    """
    if not crs_input:
        return True

    try:
        crs = CRS.from_user_input(crs_input)
        return crs.is_geographic
    except Exception:
        # If unparseable but formatted like EPSG:4326
        if "4326" in str(crs_input):
            return True
        return False


def get_utm_epsg_for_coordinates(lon: float, lat: float) -> int:
    """
    Compute the standard EPSG code for the UTM zone covering the given coordinate.

    UTM divides the world into 60 longitudinal zones of 6 degrees each.
    - EPSG:32601 to 32660: Northern Hemisphere (WGS 84 / UTM zones 1N-60N)
    - EPSG:32701 to 32760: Southern Hemisphere (WGS 84 / UTM zones 1S-60S)
    """
    # Normalize longitude to [-180, 180)
    lon_norm = ((lon + 180.0) % 360.0) - 180.0

    # Polar limits where standard UTM grid is not defined
    if lat > 84.0 or lat < -80.0:
        return 3857  # Fallback to Web Mercator

    zone = int(math.floor((lon_norm + 180.0) / 6.0)) + 1
    zone = max(1, min(60, zone))

    if lat >= 0.0:
        return 32600 + zone
    else:
        return 32700 + zone


def determine_target_projected_crs(
    geometry: BaseGeometry,
    source_crs: Optional[str],
) -> Optional[str]:
    """
    Determine whether reprojection is necessary and return the target projected CRS EPSG.

    Returns:
    --------
    Optional[str]:
        Target EPSG string (e.g. "EPSG:32643") if reprojection is required.
        None if the geometry is already in a metric projected coordinate system.
    """
    centroid = geometry.centroid

    # If no CRS provided, inspect coordinate magnitudes
    if not source_crs:
        if abs(centroid.x) <= 180.0 and abs(centroid.y) <= 90.0:
            epsg = get_utm_epsg_for_coordinates(centroid.x, centroid.y)
            return f"EPSG:{epsg}"
        return None  # Coordinates already appear to be in planar meters

    if not is_geographic_crs(source_crs):
        return None  # Source CRS is already projected

    epsg = get_utm_epsg_for_coordinates(centroid.x, centroid.y)
    return f"EPSG:{epsg}"
