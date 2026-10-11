"""
Sample Geospatial Data Generator.

Generates realistic test datasets in both Shapefile (.zip) and KML (.kml) formats:
1. `urban_parcels.zip`       : Polygons (land parcels with attributes, EPSG:4326)
2. `metro_network.zip`       : LineStrings (transit lines, EPSG:4326)
3. `city_landmarks.zip`      : Points (civic points of interest, EPSG:4326)
4. `natural_reserves.kml`    : KML with Polygons (parks and nature preserves)
5. `nature_trails.kml`       : KML with LineStrings (hiking trails)

Run directly:
    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import shapefile

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def create_zipped_shapefile(
    output_filename: str,
    shapes: list,
    shape_type: int,
    records: list[list],
    fields: list[tuple[str, str, int]],
):
    """Write an ESRI Shapefile bundle directly into a .zip file."""
    shp_buf = io.BytesIO()
    shx_buf = io.BytesIO()
    dbf_buf = io.BytesIO()

    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shape_type)
    for fname, ftype, fsize in fields:
        writer.field(fname, ftype, size=fsize)

    for s, r in zip(shapes, records):
        if shape_type == shapefile.POLYGON:
            writer.poly(s)
        elif shape_type == shapefile.POLYLINE:
            writer.line(s)
        elif shape_type == shapefile.POINT:
            writer.point(s[0], s[1])
        writer.record(*r)

    writer.close()

    dest_zip = OUTPUT_DIR / output_filename
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        stem = Path(output_filename).stem
        zf.writestr(f"{stem}.shp", shp_buf.getvalue())
        zf.writestr(f"{stem}.shx", shx_buf.getvalue())
        zf.writestr(f"{stem}.dbf", dbf_buf.getvalue())
        zf.writestr(f"{stem}.prj", WGS84_PRJ)

    print(f"Created: {dest_zip} ({dest_zip.stat().st_size} bytes)")


def generate_samples():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Urban Parcels (Polygons) in Bangalore tech corridor
    parcels_shapes = [
        # Parcel A - Tech Park Alpha
        [[[77.6850, 12.9260], [77.6910, 12.9260], [77.6910, 12.9320], [77.6850, 12.9320], [77.6850, 12.9260]]],
        # Parcel B - Residential Complex
        [[[77.6920, 12.9260], [77.6980, 12.9270], [77.6970, 12.9330], [77.6915, 12.9325], [77.6920, 12.9260]]],
        # Parcel C - Commercial Zone
        [[[77.6850, 12.9330], [77.6950, 12.9335], [77.6945, 12.9390], [77.6845, 12.9385], [77.6850, 12.9330]]],
    ]
    parcels_fields = [
        ("id", "N", 10),
        ("name", "C", 40),
        ("zoning", "C", 20),
        ("assessed", "N", 12),
    ]
    parcels_records = [
        [101, "Tech Corridor Block A", "Commercial", 45000000],
        [102, "Greenwood Meadows", "Residential", 28000000],
        [103, "Innovation Hub North", "Commercial", 62000000],
    ]
    create_zipped_shapefile("urban_parcels.zip", parcels_shapes, shapefile.POLYGON, parcels_records, parcels_fields)

    # 2. Metro Network (LineStrings)
    metro_shapes = [
        # Purple Line Spur (~5.5 km)
        [[[77.5800, 12.9700], [77.6000, 12.9750], [77.6200, 12.9780], [77.6400, 12.9810]]],
        # Outer Ring Road Express Line (~8.2 km)
        [[[77.6700, 12.9100], [77.6800, 12.9300], [77.6900, 12.9500], [77.7000, 12.9700]]],
    ]
    metro_fields = [
        ("line_id", "N", 6),
        ("line_name", "C", 30),
        ("status", "C", 20),
        ("capacity", "N", 8),
    ]
    metro_records = [
        [1, "East-West Transit Line", "Operational", 120000],
        [2, "ORR Phase 2A Extension", "Under Construction", 180000],
    ]
    create_zipped_shapefile("metro_network.zip", metro_shapes, shapefile.POLYLINE, metro_records, metro_fields)

    # 3. City Landmarks (Points)
    landmark_shapes = [
        [77.5946, 12.9716],  # Cubbon Park
        [77.5806, 12.9797],  # Vidhana Soudha
        [77.6095, 12.9352],  # Forum Mall
    ]
    landmark_fields = [
        ("id", "N", 6),
        ("name", "C", 35),
        ("type", "C", 25),
    ]
    landmark_records = [
        [201, "Cubbon Botanical Park", "Civic Park"],
        [202, "State Secretariat", "Government"],
        [203, "Koramangala Commercial Hub", "Retail"],
    ]
    create_zipped_shapefile("city_landmarks.zip", landmark_shapes, shapefile.POINT, landmark_records, landmark_fields)

    # 4. Natural Reserves KML (Polygons)
    kml_polygons = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Protected Wildlife Reserves</name>
    <Placemark>
      <name>Bannerghatta Biological Zone</name>
      <description>National park conservation zone with elephant corridor</description>
      <ExtendedData>
        <Data name="category"><value>National Park</value></Data>
        <Data name="established"><value>1971</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5600,12.7800,0
              77.6100,12.7800,0
              77.6100,12.8300,0
              77.5600,12.8300,0
              77.5600,12.7800,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Hesaraghatta Grasslands</name>
      <description>Ecological sensitive bird sanctuary and wetland</description>
      <ExtendedData>
        <Data name="category"><value>Wetland Reserve</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.4700,13.1400,0
              77.5100,13.1400,0
              77.5100,13.1700,0
              77.4700,13.1700,0
              77.4700,13.1400,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    kml_poly_path = OUTPUT_DIR / "natural_reserves.kml"
    kml_poly_path.write_text(kml_polygons, encoding="utf-8")
    print(f"Created: {kml_poly_path} ({kml_poly_path.stat().st_size} bytes)")

    # 5. Nature Trails KML (LineStrings)
    kml_lines = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Nandi Hills Trekking Trails</name>
    <Placemark>
      <name>Sunrise Summit Ridge Path</name>
      <description>Moderate difficulty trekking trail with scenic views</description>
      <ExtendedData>
        <Data name="difficulty"><value>Moderate</value></Data>
      </ExtendedData>
      <LineString>
        <coordinates>
          77.6750,13.3650,0
          77.6800,13.3700,0
          77.6830,13.3740,0
          77.6850,13.3800,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    kml_lines_path = OUTPUT_DIR / "nature_trails.kml"
    kml_lines_path.write_text(kml_lines, encoding="utf-8")
    print(f"Created: {kml_lines_path} ({kml_lines_path.stat().st_size} bytes)")

    print("\nAll sample geospatial datasets generated successfully in ./sample_data/")


if __name__ == "__main__":
    generate_samples()
