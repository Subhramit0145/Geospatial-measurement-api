# Sample Geospatial Datasets

This directory contains pre-generated datasets designed for testing and demonstrating the Geospatial Measurement API:

| File | Geometry Type | CRS | Features / Description |
| :--- | :--- | :--- | :--- |
| `urban_parcels.zip` | `Polygon` | EPSG:4326 | 3 land parcels with zoning codes (`Commercial`, `Residential`, `Public Park`). Evaluates area calculation ($m^2$) after UTM projection. |
| `metro_network.zip` | `LineString` | EPSG:4326 | 3 transit corridors (Red, Blue, Green lines). Evaluates geodesic length calculation ($m$). |
| `city_landmarks.zip` | `Point` | EPSG:4326 | 3 civic locations (City Hall, Central Station, Science Museum). Evaluates non-measurement geometry preservation. |
| `natural_reserves.kml` | `Polygon` | EPSG:4326 | 2 conservation parks formatted in Keyhole Markup Language. Evaluates XML geometry extraction and polygon area measurement. |
| `nature_trails.kml` | `LineString` | EPSG:4326 | 2 scenic recreational trails. Evaluates KML coordinate string parsing and path length measurement. |

### Regenerating Datasets
You can regenerate these datasets at any time by running:
```bash
python scripts/generate_sample_data.py
```
