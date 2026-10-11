"""
KML Parser Service.

Parses OGC KML 2.2 files using standard Python XML parsing and Shapely.
Extracts Placemarks, attributes (name, description, ExtendedData), and supports:
- Points
- LineStrings
- Polygons (with outer ring and interior hole support)
- MultiGeometry
OGC KML 2.2 coordinates are natively WGS84 (EPSG:4326).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
)
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)


class KMLParseError(Exception):
    """Raised when a KML file is invalid or malformed."""


def _clean_tag(tag: str) -> str:
    """Strip XML namespace prefix from tag (e.g. '{http://...}Placemark' -> 'Placemark')."""
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_coordinates(coord_text: Optional[str]) -> list[tuple[float, float]]:
    """
    Parse a whitespace-separated KML coordinate string:
    'lon,lat,alt lon,lat,alt ...' into a list of (lon, lat) tuples.
    """
    if not coord_text:
        return []

    coords: list[tuple[float, float]] = []
    # Split on any whitespace
    tokens = coord_text.strip().split()
    for tok in tokens:
        parts = tok.strip().split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append((lon, lat))
            except ValueError:
                continue
    return coords


def _parse_geometry(elem: ET.Element) -> Optional[BaseGeometry]:
    """Recursively parse KML geometry elements into Shapely geometry objects."""
    tag = _clean_tag(elem.tag)

    if tag == "Point":
        for child in elem:
            if _clean_tag(child.tag) == "coordinates":
                coords = _parse_coordinates(child.text)
                if coords:
                    return Point(coords[0])
        return None

    if tag == "LineString":
        for child in elem:
            if _clean_tag(child.tag) == "coordinates":
                coords = _parse_coordinates(child.text)
                if len(coords) >= 2:
                    return LineString(coords)
        return None

    if tag == "LinearRing":
        for child in elem:
            if _clean_tag(child.tag) == "coordinates":
                coords = _parse_coordinates(child.text)
                if len(coords) >= 3:
                    return Polygon(coords)
        return None

    if tag == "Polygon":
        shell_coords: list[tuple[float, float]] = []
        holes_coords: list[list[tuple[float, float]]] = []

        for child in elem:
            ctag = _clean_tag(child.tag)
            if ctag == "outerBoundaryIs":
                for ring in child:
                    if _clean_tag(ring.tag) == "LinearRing":
                        for c in ring:
                            if _clean_tag(c.tag) == "coordinates":
                                shell_coords = _parse_coordinates(c.text)
            elif ctag == "innerBoundaryIs":
                for ring in child:
                    if _clean_tag(ring.tag) == "LinearRing":
                        for c in ring:
                            if _clean_tag(c.tag) == "coordinates":
                                hole = _parse_coordinates(c.text)
                                if len(hole) >= 3:
                                    holes_coords.append(hole)

        if len(shell_coords) >= 3:
            return Polygon(shell=shell_coords, holes=holes_coords)
        return None

    if tag == "MultiGeometry":
        parts: list[BaseGeometry] = []
        for child in elem:
            part = _parse_geometry(child)
            if part is not None and not part.is_empty:
                parts.append(part)

        if not parts:
            return None

        # If all parts are Polygons, return MultiPolygon
        if all(isinstance(p, Polygon) for p in parts):
            return MultiPolygon(parts)
        # If all parts are LineStrings, return MultiLineString
        if all(isinstance(p, LineString) for p in parts):
            return MultiLineString(parts)
        # If all parts are Points, return MultiPoint
        if all(isinstance(p, Point) for p in parts):
            return MultiPoint(parts)

        return GeometryCollection(parts)

    return None


def _extract_placemark_properties(placemark_elem: ET.Element) -> dict[str, Any]:
    """Extract name, description, and ExtendedData from a <Placemark>."""
    props: dict[str, Any] = {}

    for child in placemark_elem:
        ctag = _clean_tag(child.tag)
        if ctag == "name" and child.text:
            props["name"] = child.text.strip()
        elif ctag == "description" and child.text:
            props["description"] = child.text.strip()
        elif ctag == "ExtendedData":
            for ext in child:
                ext_tag = _clean_tag(ext.tag)
                # Handle <Data name="foo"><value>bar</value></Data>
                if ext_tag == "Data":
                    d_name = ext.attrib.get("name")
                    if d_name:
                        for val_node in ext:
                            if _clean_tag(val_node.tag) == "value" and val_node.text:
                                props[d_name] = val_node.text.strip()
                # Handle <SchemaData><SimpleData name="foo">bar</SimpleData></SchemaData>
                elif ext_tag == "SchemaData":
                    for s_child in ext:
                        if _clean_tag(s_child.tag) == "SimpleData":
                            s_name = s_child.attrib.get("name")
                            if s_name and s_child.text:
                                props[s_name] = s_child.text.strip()

    return props


def parse_kml_file(kml_path: Path) -> dict[str, Any]:
    """
    Parse a .kml file.

    Parameters
    ----------
    kml_path : Path
        Filesystem path to the .kml file.

    Returns
    -------
    dict with:
        - "crs": "EPSG:4326" (OGC standard)
        - "features": list of feature dicts
    """
    try:
        tree = ET.parse(str(kml_path))
        root = tree.getroot()
    except ET.ParseError as exc:
        raise KMLParseError(f"Malformed XML in KML file: {exc}") from exc
    except Exception as exc:
        raise KMLParseError(f"Failed to read KML file: {exc}") from exc

    features: list[dict[str, Any]] = []

    # Find all Placemark elements regardless of nesting
    for idx, elem in enumerate(root.iter()):
        if _clean_tag(elem.tag) != "Placemark":
            continue

        props = _extract_placemark_properties(elem)

        # Find geometry element inside the placemark
        geom: Optional[BaseGeometry] = None
        for child in elem:
            candidate = _parse_geometry(child)
            if candidate is not None:
                geom = candidate
                break

        if geom is None or geom.is_empty:
            continue

        geo_iface = mapping(geom)

        features.append({
            "index": len(features),
            "geometry_type": geom.geom_type,
            "geometry_wkt": geom.wkt,
            "geometry_geojson": geo_iface,
            "properties": props,
        })

    logger.info("Parsed KML '%s': %d features, CRS: EPSG:4326", kml_path.name, len(features))

    return {
        "crs": "EPSG:4326",
        "features": features,
    }
