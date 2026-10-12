"""
High-Concurrency Load Testing Utility.

Simulates extreme traffic scenarios (from 1,000 up to 100,000+ requests)
against the Geospatial File Measurement API using asynchronous HTTP pipelining.

Usage:
    python scripts/load_test.py --requests 10000 --concurrency 100
    python scripts/load_test.py --requests 100000 --concurrency 200 --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import io
import statistics
import time
import zipfile
from typing import Counter

import httpx

# In-memory shapefile generator for mixed load testing
def _generate_test_shapefile_bytes() -> bytes:
    import shapefile
    shp_buf = io.BytesIO()
    shx_buf = io.BytesIO()
    dbf_buf = io.BytesIO()

    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shapefile.POLYGON)
    writer.field("name", "C", size=50)
    poly = [[[77.5946, 12.9716], [77.6046, 12.9716], [77.6046, 12.9816], [77.5946, 12.9816], [77.5946, 12.9716]]]
    writer.poly(poly)
    writer.record("LoadTestPoly")
    writer.close()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dataset.shp", shp_buf.getvalue())
        zf.writestr("dataset.shx", shx_buf.getvalue())
        zf.writestr("dataset.dbf", dbf_buf.getvalue())
    return zip_buf.getvalue()



async def run_worker(
    client: httpx.AsyncClient,
    queue: asyncio.Queue,
    latencies: list[float],
    status_codes: Counter,
    cache_headers: Counter,
    url_base: str,
    target_endpoints: list[str],
):
    while not queue.empty():
        try:
            req_idx = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        endpoint = target_endpoints[req_idx % len(target_endpoints)]
        start = time.perf_counter()
        try:
            resp = await client.get(f"{url_base}{endpoint}")
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)
            status_codes[resp.status_code] += 1
            x_cache = resp.headers.get("X-Cache", "NONE")
            cache_headers[x_cache] += 1
        except Exception:
            status_codes[0] += 1  # 0 indicates network error/timeout
        finally:
            queue.task_done()


async def benchmark(
    base_url: str,
    total_requests: int,
    concurrency: int,
    timeout: float,
    scenario: str,
):
    print("=" * 70)
    print("GEOSPATIAL API HIGH-SCALABILITY BENCHMARK SUITE")
    print("=" * 70)
    print(f"Target URL:        {base_url}")
    print(f"Total Requests:    {total_requests:,}")
    print(f"Concurrency:       {concurrency} concurrent workers")
    print(f"Scenario:          {scenario}")
    print("-" * 70)

    # Prepare endpoints to test
    endpoints = ["/health", "/api/system/metrics", "/api/files/"]

    # Pre-seed a file so we can benchmark measurement and GeoJSON endpoints
    async with httpx.AsyncClient(timeout=10.0) as seed_client:
        try:
            h_resp = await seed_client.get(f"{base_url}/health")
            if h_resp.status_code != 200:
                print(f"[!] Target API health check failed: {h_resp.status_code}")
                return
            print("[+] Target API is healthy and reachable.")

            # Upload a test file to generate a file_id
            zip_bytes = _generate_test_shapefile_bytes()
            up_resp = await seed_client.post(
                f"{base_url}/api/files/",
                files={"file": ("bench_file.zip", zip_bytes, "application/zip")},
            )
            if up_resp.status_code == 201:
                seeded_id = up_resp.json()["id"]
                endpoints.extend([
                    f"/api/files/{seeded_id}/",
                    f"/api/files/{seeded_id}/measurements/",
                    f"/api/files/{seeded_id}/geojson/",
                ])
                print(f"[+] Successfully seeded test file (ID: {seeded_id}) for read caching tests.")
            else:
                print(f"[!] Warning: Could not seed test file: {up_resp.text}")
        except Exception as exc:
            print(f"[!] Connection failed: {exc}")
            return

    queue: asyncio.Queue = asyncio.Queue()
    for i in range(total_requests):
        queue.put_nowait(i)

    latencies: list[float] = []
    status_codes: Counter = Counter()
    cache_headers: Counter = Counter()

    limits = httpx.Limits(
        max_connections=concurrency * 2,
        max_keepalive_connections=concurrency,
        keepalive_expiry=30.0,
    )

    print(f"\n[>] Firing {total_requests:,} requests...")
    overall_start = time.perf_counter()

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        workers = [
            asyncio.create_task(
                run_worker(
                    client,
                    queue,
                    latencies,
                    status_codes,
                    cache_headers,
                    base_url,
                    endpoints,
                )
            )
            for _ in range(concurrency)
        ]
        await queue.join()
        for w in workers:
            w.cancel()

    total_duration = time.perf_counter() - overall_start
    total_completed = len(latencies)
    rps = total_completed / total_duration if total_duration > 0 else 0

    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 70)
    print(f"Completed Requests:      {total_completed:,} / {total_requests:,}")
    print(f"Total Duration:          {total_duration:.2f} seconds")
    print(f"Throughput:              {rps:,.1f} Requests / Second (RPS)")
    print("-" * 70)

    if latencies:
        latencies.sort()
        avg_lat = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        min_lat = min(latencies)
        max_lat = max(latencies)

        print(f"Latency (Min):           {min_lat:.2f} ms")
        print(f"Latency (Average):       {avg_lat:.2f} ms")
        print(f"Latency (Median / p50):  {p50:.2f} ms")
        print(f"Latency (95th %tile):    {p95:.2f} ms")
        print(f"Latency (99th %tile):    {p99:.2f} ms")
        print(f"Latency (Max):           {max_lat:.2f} ms")

    print("-" * 70)
    print("HTTP Status Codes:")
    for code, count in sorted(status_codes.items()):
        status_name = "Network Error" if code == 0 else f"HTTP {code}"
        percent = (count / total_requests) * 100
        print(f"  {status_name:<16}: {count:,} ({percent:.1f}%)")

    print("-" * 70)
    print("Cache Efficiency:")
    for header, count in sorted(cache_headers.items()):
        percent = (count / total_completed) * 100 if total_completed > 0 else 0
        print(f"  X-Cache {header:<8}: {count:,} ({percent:.1f}%)")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Geospatial API High-Concurrency Load Tester")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base API URL")
    parser.add_argument("--requests", type=int, default=1000, help="Total requests to send (e.g. 100000)")
    parser.add_argument("--concurrency", type=int, default=50, help="Number of concurrent workers")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP request timeout in seconds")
    parser.add_argument("--scenario", default="read", choices=["read", "mixed"], help="Traffic pattern scenario")

    args = parser.parse_args()
    asyncio.run(
        benchmark(
            base_url=args.url.rstrip("/"),
            total_requests=args.requests,
            concurrency=args.concurrency,
            timeout=args.timeout,
            scenario=args.scenario,
        )
    )


if __name__ == "__main__":
    main()
