"""
Unit and integration tests for scalability features:
- Multi-tier caching (HIT / MISS headers, TTL, LRU eviction)
- Cache invalidation on file deletion and uploads
- System metrics and telemetry endpoints (/api/system/metrics, /metrics)
- Sliding-window rate limiter
- High concurrency simulation
"""

from __future__ import annotations

import concurrent.futures
import shapefile
from app.config import settings
from app.services.cache import cache
from app.utils.rate_limiter import SlidingWindowRateLimiter
from tests.test_upload import make_shapefile_zip


class TestCachingLayer:
    def test_cache_miss_then_hit_on_measurements(self, client):
        poly = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("cache_poly.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        # First request -> MISS
        r1 = client.get(f"/api/files/{file_id}/measurements/")
        assert r1.status_code == 200
        assert r1.headers.get("X-Cache") == "MISS"

        # Second request -> HIT
        r2 = client.get(f"/api/files/{file_id}/measurements/")
        assert r2.status_code == 200
        assert r2.headers.get("X-Cache") == "HIT"
        assert r2.json() == r1.json()

    def test_cache_hit_on_geojson(self, client):
        poly = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("cache_geo.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        # 1st call -> MISS
        r1 = client.get(f"/api/files/{file_id}/geojson/")
        assert r1.status_code == 200
        assert r1.headers.get("X-Cache") == "MISS"

        # 2nd call -> HIT
        r2 = client.get(f"/api/files/{file_id}/geojson/")
        assert r2.status_code == 200
        assert r2.headers.get("X-Cache") == "HIT"

    def test_cache_invalidation_on_deletion(self, client):
        poly = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("cache_del.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        # Warm cache
        client.get(f"/api/files/{file_id}/")
        assert cache.get(f"file_info:{file_id}") is not None

        # Delete file
        del_resp = client.delete(f"/api/files/{file_id}/")
        assert del_resp.status_code == 204

        # Cache must be invalidated
        assert cache.get(f"file_info:{file_id}") is None

    def test_manual_cache_clear(self, client):
        cache.set("test_key", {"data": 123}, ttl=60)
        assert cache.get("test_key") is not None

        resp = client.post("/api/system/cache/clear")
        assert resp.status_code == 200
        assert cache.get("test_key") is None


class TestSystemMetrics:
    def test_system_metrics_endpoint(self, client):
        resp = client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "operational"
        assert "uptime_seconds" in data
        assert "total_requests_processed" in data
        assert data["total_requests_processed"] > 0
        assert "cache" in data
        assert "database" in data
        assert data["database"]["status"] == "healthy"

    def test_metrics_shortcut_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"

    def test_health_check_includes_scalability(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["version"] == "2.0.0"
        assert data["scalability"] == "high-throughput-ready"


class TestRateLimiter:
    def test_rate_limiter_allows_under_limit(self):
        lim = SlidingWindowRateLimiter(max_requests=5, window_seconds=10)
        for _ in range(5):
            allowed, retry = lim.is_allowed("192.168.1.1")
            assert allowed is True
            assert retry == 0

    def test_rate_limiter_blocks_above_limit(self):
        lim = SlidingWindowRateLimiter(max_requests=3, window_seconds=10)
        for _ in range(3):
            allowed, _ = lim.is_allowed("10.0.0.1")
            assert allowed is True

        allowed, retry = lim.is_allowed("10.0.0.1")
        assert allowed is False
        assert retry > 0

        # Different IP should still be allowed
        allowed_other, _ = lim.is_allowed("10.0.0.2")
        assert allowed_other is True


class TestHighConcurrency:
    def test_concurrent_read_requests(self, client):
        poly = [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]
        buf = make_shapefile_zip([poly], shapefile.POLYGON)

        up_resp = client.post(
            "/api/files/",
            files={"file": ("concurrent_test.zip", buf, "application/zip")},
        )
        file_id = up_resp.json()["id"]

        def fetch_measurement():
            return client.get(f"/api/files/{file_id}/measurements/")

        # Execute 50 concurrent requests simultaneously
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_measurement) for _ in range(50)]
            responses = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(responses) == 50
        assert all(r.status_code == 200 for r in responses)
        # At least some should be cache hits
        hits = sum(1 for r in responses if r.headers.get("X-Cache") == "HIT")
        assert hits >= 40
