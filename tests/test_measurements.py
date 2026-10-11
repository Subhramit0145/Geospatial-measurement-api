"""
Unit and integration tests for geometric measurements, projection accuracy, and API endpoints.
"""

from __future__ import annotations

import io
import shapefile
from tests.test_upload import make_kml_content, make_shapefile_zip, WGS84_PRJ
from app.services.crs_handler import get_utm_epsg_for_coordinates, is_geographic_crs


class TestMeasurementCalculations:
    def test_polygon_area_calculated_in_square_meters(self, client):
        """
        Verifies that a 0.01° x 0.01° polygon is projected to UTM and calculated
        in metric square meters (~1.2 million m²), NOT in square degrees (~0.0001).
        """
        poly_coords = [[[77.5946, 12.9716], [77.6046, 12.9716], [77.6046, 12.9816], [77.5946, 12.9816], [77.5946, 12.9716]]]
        buf = make_shapefile_zip([poly_coords], shapefile.POLYGON, prj_text=WGS84_PRJ)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("parcels.zip", buf, "application/zip")},
        )
        assert up_resp.status_code == 201
        file_id = up_resp.json()["id"]

        # Fetch measurements
        m_resp = client.get(f"/api/files/{file_id}/measurements/")
        assert m_resp.status_code == 200
        data = m_resp.json()

        assert data["file_id"] == file_id
        assert data["feature_count"] == 1
        assert data["summary"]["polygons_measured"] == 1
        assert data["summary"]["total_area_sq_meters"] is not None

        feature_m = data["measurements"][0]
        assert feature_m["geometry_type"] == "Polygon"
        assert feature_m["measurement_type"] == "area"
        assert feature_m["measurement_unit"] == "sq_meters"
        assert feature_m["projected_crs"] == "EPSG:32643"  # UTM Zone 43N
        # Area must be ~1.2e6 m² (definitely > 100,000 and < 2,000,000)
        assert 1000000 < feature_m["measurement_value"] < 1500000
        assert feature_m["geometry"] is not None
        assert feature_m["geometry"]["type"] == "Polygon"

    def test_linestring_length_calculated_in_meters(self, client):
        """
        Verifies that a ~0.14° line is projected and measured in physical meters
        (~15-20 km), NOT in degrees (~0.14).
        """
        line_coords = [[[77.5, 12.9], [77.6, 13.0]]]
        buf = make_shapefile_zip([line_coords], shapefile.POLYLINE)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("transmission_line.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        m_resp = client.get(f"/api/files/{file_id}/measurements/")
        assert m_resp.status_code == 200
        data = m_resp.json()

        feature_m = data["measurements"][0]
        assert feature_m["geometry_type"] == "LineString"
        assert feature_m["measurement_type"] == "length"
        assert feature_m["measurement_unit"] == "meters"
        assert feature_m["measurement_value"] > 10000  # > 10 km
        assert data["summary"]["linestrings_measured"] == 1

    def test_point_has_no_measurement_and_is_handled_gracefully(self, client):
        """Points require no measurement and should gracefully return null."""
        pt_coords = [77.5946, 12.9716]
        buf = make_shapefile_zip([pt_coords], shapefile.POINT)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("landmarks.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        m_resp = client.get(f"/api/files/{file_id}/measurements/")
        assert m_resp.status_code == 200
        data = m_resp.json()

        feature_m = data["measurements"][0]
        assert feature_m["geometry_type"] == "Point"
        assert feature_m["measurement_type"] is None
        assert feature_m["measurement_value"] is None
        assert feature_m["measurement_unit"] is None
        assert data["summary"]["points_skipped"] == 1

    def test_kml_polygon_measurement(self, client):
        placemark = """
        <Placemark>
          <name>Lake Reservoir</name>
          <Polygon>
            <outerBoundaryIs>
              <LinearRing>
                <coordinates>
                  77.5900,12.9700,0 77.6000,12.9700,0 77.6000,12.9800,0 77.5900,12.9800,0 77.5900,12.9700,0
                </coordinates>
              </LinearRing>
            </outerBoundaryIs>
          </Polygon>
        </Placemark>
        """
        buf = make_kml_content(placemark)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("lake.kml", buf, "application/vnd.google-earth.kml+xml")},
        )
        file_id = up_resp.json()["id"]

        m_resp = client.get(f"/api/files/{file_id}/measurements/")
        assert m_resp.status_code == 200
        data = m_resp.json()
        assert data["measurements"][0]["measurement_type"] == "area"
        assert data["measurements"][0]["measurement_value"] > 0


class TestAPIEndpoints:
    def test_get_file_info_endpoint(self, client):
        poly_coords = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly_coords], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("survey.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        info_resp = client.get(f"/api/files/{file_id}/")
        assert info_resp.status_code == 200
        info = info_resp.json()
        assert info["id"] == file_id
        assert info["filename"] == "survey.zip"
        assert info["feature_count"] == 1
        assert info["status"] == "COMPLETED"

    def test_file_not_found_returns_404(self, client):
        resp = client.get("/api/files/nonexistent_id/")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_list_files_endpoint(self, client):
        poly_coords = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly_coords], shapefile.POLYGON)

        client.post(
            "/api/files/",
            files={"file": ("list_test.zip", buf, "application/zip")},
        )

        resp = client.get("/api/files/?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["files"]) >= 1

    def test_export_geojson_endpoint(self, client):
        poly_coords = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly_coords], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("export_test.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        geo_resp = client.get(f"/api/files/{file_id}/geojson/")
        assert geo_resp.status_code == 200
        fc = geo_resp.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 1
        assert fc["features"][0]["geometry"]["type"] == "Polygon"
        assert "_measurement_value" in fc["features"][0]["properties"]

    def test_delete_file_endpoint(self, client):
        poly_coords = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly_coords], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("delete_me.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        del_resp = client.delete(f"/api/files/{file_id}/")
        assert del_resp.status_code == 204

        # Verify it no longer exists
        get_resp = client.get(f"/api/files/{file_id}/")
        assert get_resp.status_code == 404


class TestCRSHelpers:
    def test_is_geographic_crs(self):
        assert is_geographic_crs("EPSG:4326") is True
        assert is_geographic_crs("EPSG:32643") is False
        assert is_geographic_crs("EPSG:3857") is False

    def test_utm_zone_determination(self):
        # Bangalore (~77.59°E, 12.97°N) -> UTM Zone 43N -> EPSG:32643
        assert get_utm_epsg_for_coordinates(77.59, 12.97) == 32643

        # London (~-0.12°W, 51.50°N) -> UTM Zone 30N -> EPSG:32630
        assert get_utm_epsg_for_coordinates(-0.12, 51.50) == 32630

        # Sydney (~151.20°E, -33.86°S) -> UTM Zone 56S -> EPSG:32756
        assert get_utm_epsg_for_coordinates(151.20, -33.86) == 32756

    def test_polar_fallback(self):
        # Lat > 84 degrees falls back to Web Mercator EPSG:3857
        assert get_utm_epsg_for_coordinates(10.0, 85.0) == 3857
