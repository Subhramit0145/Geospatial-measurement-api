"""
Unit and integration tests for geospatial file uploads (POST /api/files/).
"""

from __future__ import annotations

import io
import zipfile
import shapefile

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

UTM43N_PRJ = (
    'PROJCS["WGS 84 / UTM zone 43N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",75],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1]]'
)


def make_shapefile_zip(
    shapes: list,
    shape_type: int,
    prj_text: str | None = None,
    folder_prefix: str = "",
) -> io.BytesIO:
    """Build a valid Shapefile archive entirely in-memory."""
    shp_buf = io.BytesIO()
    shx_buf = io.BytesIO()
    dbf_buf = io.BytesIO()

    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shape_type)
    writer.field("name", "C", size=50)
    writer.field("category", "C", size=30)

    for i, s in enumerate(shapes):
        if shape_type == shapefile.POLYGON:
            writer.poly(s)
        elif shape_type == shapefile.POLYLINE:
            writer.line(s)
        elif shape_type == shapefile.POINT:
            writer.point(s[0], s[1])
        writer.record(f"Feature_{i}", "Survey")

    writer.close()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        p = f"{folder_prefix}/" if folder_prefix else ""
        zf.writestr(f"{p}dataset.shp", shp_buf.getvalue())
        zf.writestr(f"{p}dataset.shx", shx_buf.getvalue())
        zf.writestr(f"{p}dataset.dbf", dbf_buf.getvalue())
        if prj_text:
            zf.writestr(f"{p}dataset.prj", prj_text)

    zip_buf.seek(0)
    return zip_buf


def make_kml_content(placemarks_xml: str) -> io.BytesIO:
    """Wrap placemark fragments in standard OGC KML 2.2 document."""
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Survey Dataset</name>
    {placemarks_xml}
  </Document>
</kml>"""
    return io.BytesIO(kml.encode("utf-8"))


# ── Test Cases ──────────────────────────────────────────────────────

class TestShapefileUpload:
    def test_upload_polygon_shapefile_success(self, client):
        # Quadrilateral polygon in Bangalore (~0.01 deg x ~0.01 deg)
        polygon_coords = [[[77.5946, 12.9716], [77.6046, 12.9716], [77.6046, 12.9816], [77.5946, 12.9816], [77.5946, 12.9716]]]
        buf = make_shapefile_zip([polygon_coords], shapefile.POLYGON, prj_text=WGS84_PRJ)

        resp = client.post(
            "/api/files/",
            files={"file": ("parcels.zip", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "parcels.zip"
        assert data["feature_count"] == 1
        assert data["status"] == "COMPLETED"
        assert "EPSG:4326" in data["crs"]
        assert len(data["id"]) > 0

    def test_upload_polyline_shapefile(self, client):
        line_coords = [[[77.5, 12.9], [77.6, 13.0], [77.7, 13.1]]]
        buf = make_shapefile_zip([line_coords], shapefile.POLYLINE)

        resp = client.post(
            "/api/files/",
            files={"file": ("roads.zip", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["feature_count"] == 1
        assert data["status"] == "COMPLETED"

    def test_upload_point_shapefile(self, client):
        pt_coords = [77.5946, 12.9716]
        buf = make_shapefile_zip([pt_coords], shapefile.POINT)

        resp = client.post(
            "/api/files/",
            files={"file": ("trees.zip", buf, "application/zip")},
        )
        assert resp.status_code == 201
        assert resp.json()["feature_count"] == 1

    def test_upload_projected_utm_shapefile(self, client):
        # Shapefile already in projected UTM zone 43N
        utm_poly = [[[500000, 1400000], [501000, 1400000], [501000, 1401000], [500000, 1401000], [500000, 1400000]]]
        buf = make_shapefile_zip([utm_poly], shapefile.POLYGON, prj_text=UTM43N_PRJ)

        resp = client.post(
            "/api/files/",
            files={"file": ("projected.zip", buf, "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "32643" in data["crs"]

    def test_upload_shapefile_in_subdirectory(self, client):
        # Many archives wrap shapefiles in a subfolder
        poly = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly], shapefile.POLYGON, folder_prefix="my_export_folder")

        resp = client.post(
            "/api/files/",
            files={"file": ("nested.zip", buf, "application/zip")},
        )
        assert resp.status_code == 201
        assert resp.json()["feature_count"] == 1


class TestKMLUpload:
    def test_upload_kml_polygon(self, client):
        placemark = """
        <Placemark>
          <name>Central Park Zone</name>
          <description>Public recreation area</description>
          <ExtendedData>
            <Data name="zone_code"><value>REC-01</value></Data>
          </ExtendedData>
          <Polygon>
            <outerBoundaryIs>
              <LinearRing>
                <coordinates>
                  77.5946,12.9716,0 77.6046,12.9716,0 77.6046,12.9816,0 77.5946,12.9816,0 77.5946,12.9716,0
                </coordinates>
              </LinearRing>
            </outerBoundaryIs>
          </Polygon>
        </Placemark>
        """
        buf = make_kml_content(placemark)

        resp = client.post(
            "/api/files/",
            files={"file": ("zones.kml", buf, "application/vnd.google-earth.kml+xml")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["feature_count"] == 1
        assert data["crs"] == "EPSG:4326"

    def test_upload_kml_linestring(self, client):
        placemark = """
        <Placemark>
          <name>Metro Line</name>
          <LineString>
            <coordinates>
              77.5900,12.9700,0 77.6000,12.9800,0 77.6100,12.9900,0
            </coordinates>
          </LineString>
        </Placemark>
        """
        buf = make_kml_content(placemark)

        resp = client.post(
            "/api/files/",
            files={"file": ("metro.kml", buf, "application/vnd.google-earth.kml+xml")},
        )
        assert resp.status_code == 201
        assert resp.json()["feature_count"] == 1


class TestUploadValidationAndErrors:
    def test_reject_unsupported_extension(self, client):
        buf = io.BytesIO(b"id,name,lat,lon\n1,Alpha,12.9,77.5")
        resp = client.post(
            "/api/files/",
            files={"file": ("data.csv", buf, "text/csv")},
        )
        assert resp.status_code == 400
        assert "Unsupported file format" in resp.json()["detail"]

    def test_reject_zip_missing_shp(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "No shapefile here")
        buf.seek(0)

        resp = client.post(
            "/api/files/",
            files={"file": ("empty.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400
        assert "does not contain a valid .shp" in resp.json()["detail"]

    def test_reject_malformed_kml(self, client):
        buf = io.BytesIO(b"<kml><broken>tag</kml>")
        resp = client.post(
            "/api/files/",
            files={"file": ("broken.kml", buf, "application/vnd.google-earth.kml+xml")},
        )
        assert resp.status_code == 400
        assert "Malformed XML" in resp.json()["detail"]
