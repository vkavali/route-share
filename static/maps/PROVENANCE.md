# Official India boundary data provenance

## Source

- Government portal page: https://nwdp.nwic.gov.in/hi/dataset/state-boundary
- Resource metadata page: https://nwdp.nwic.gov.in/hi/dataset/state-boundary/resource/f039e721-132c-4a24-9e5e-07af03064b4d
- Direct public download: https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_nwic_geojson.zip
- Resource title: `state_NWIC_GeoJSON.zip` (State Boundary)
- NWIC lists the data-producing agency as Survey of India (SOI), states that it covers all states and Union Territories, and shows the resource format as GeoJSON, last updated 1 May 2025, license text `Other (Open)`. The dataset page separately shows an update timestamp of 1 October 2026. These are portal metadata dates, not a guaranteed survey epoch.
- Survey of India portal FAQ states Administrative Boundary Database is available through Quick Access without login: https://onlinemaps.surveyofindia.gov.in/FAQs.aspx (FAQ 7). This artifact was obtained from the NWIC government-hosted public resource above, whose metadata names SOI as producer.
- Retrieved 15 October 2026. HTTP `Last-Modified`: 23 June 2026.

## Retained source files

- ZIP: `work/india-boundaries/state_nwic_geojson.zip`
  - SHA-256: `A932EA29E7AFD0FEA1E1068F3BEEEADB760E6B2BAAE9783F5822BBEFD4224EBD`
  - Downloaded as a public HTTP GET; response was HTTP 200, `Content-Type: application/zip`, 20,809,092 bytes.
- Extracted source: `work/india-boundaries/state_NWIC.GeoJSON`
  - SHA-256: `2CE4F8884A624F544623C76EA7002D7D12B8C673DB9EE6F3CE568F1366CF4010`
  - 36 source features, each a MultiPolygon; properties include `state_name`, `stcode`, `src_agency`.
  - Source CRS member is `urn:ogc:def:crs:EPSG::7755` (WGS 84 / India NSF LCC). Projected source bounds: `[2818369.5466, 2177948.4534, 5679118.5430, 5444563.2357]` metres.

## Conversion and output

- Output paths: `static/maps/india-soi-boundaries.geojson` and deterministic gzip sidecar `static/maps/india-soi-boundaries.geojson.gz`.
- Conversion script: `work/india-boundaries/build_final_soi_boundaries.py`; 25 m shared-coverage input is retained at `work/india-boundaries/state_NWIC_display_25m.GeoJSON`.
- Runtime used: Python 3.11.9, Shapely 2.1.2, pyproj 3.7.2 / PROJ 9.5.1. pyproj is installed only under `work/india-boundaries/python-deps` from official PyPI; no system packages were changed.
- The source projected coordinates are converted to longitude/latitude with `pyproj.Transformer.from_crs(7755, 4326, always_xy=True)` using the PROJ EPSG database. As an independent implementation check, a hand-coded inverse using the EPSG:7755 parameters was compared at 100 deterministic source vertices spread across all state/UTs plus the projection origin (101 points): maximum horizontal difference was 4.714e-9 m; both map the origin to (80°, 24°).
- One Andhra Pradesh source geometry has a ring self-intersection. `shapely.make_valid` produces a valid polygon with projected area change approximately 0.00019 m². The raw source remains unchanged; repair is identified on the output feature in `geometry_repair`.
- A dissolved national outline is derived from the 36 state/UT polygons; the output carries it as `kind: national`, while administrative areas are `kind: state`. This is a derived display outline, not separate source international-border data.
- Output is a 37-feature EPSG:4326 GeoJSON FeatureCollection: one `kind: national` feature and 36 `kind: state` features. Each has a normalized English `name` and interior `label_point` as `[longitude, latitude]`; state points use a representative point of the state's largest polygon component. The national label point uses a representative point of the largest component of the dissolved outline. These points are derived label placements, not source attributes.
- The display geometry uses Shapely shared-coverage simplification with 25 m tolerance in the source CRS. All 390 state/UT polygon components and all 29 holes are retained; shared coverage and every output geometry validate after reprojection and six-decimal coordinate rounding. Vertex count falls from 923,291 to 474,109. An STRtree nearest-segment comparison of every original source vertex against simplified boundary segments measured a maximum one-way vertex displacement of 49.217326 m. This is a vertex-to-line statistic, not a continuous Hausdorff bound.
- In EPSG:7755 projected area units, summed source area is 3,183,573,331,644.33 m² and summed display area is 3,183,573,179,295.86 m² (net change −152,348.47 m², −0.000004785%); the sum of absolute per-state area changes is 600,488.95 m². These figures are for display generalization review, not legal boundary accuracy.
- Coordinates are rounded to 6 decimal places, whose worst-case rounding displacement at India's latitude is under 0.11 m. Output bbox is `[68.177512, 6.755953, 97.412897, 37.088342]`, including west/south islands, northeast/east extent, and northern Ladakh extent.
- Final GeoJSON is 12,667,351 bytes, SHA-256 `7893914FC8D0E5ED23EDB8C3FDE25554ABB7AFA01A04F9EFBC86433857DCBC27`. Its deterministic `.geojson.gz` sidecar (gzip `mtime=0`, level 9) is 4,185,374 bytes, SHA-256 `4D3FAEEB33C6DD3A20F7E8A55F7DC0289E63EC7F31F3711CC0BCE6E5713DE1E6`; decompression was verified byte-for-byte against the GeoJSON.

## Limits

These generalized assets are for SeatPal map display. The national outline is derived from the SOI-attributed state/UT polygons; this dataset does not supply a separate international-boundary layer or determine legal boundaries.
