"""Conservative passenger-only previews from an already calculated road route.

Coordinates use GeoJSON [longitude, latitude] order. Endpoint clusters must
fit within 10 metres, be contiguous, unique and ordered. Clipping trims inward
(to the last pickup vertex and first drop-off vertex), never adding connectors.
Missing/sparse/ambiguous geometry deliberately produces no preview.
"""
from math import asin, cos, isfinite, radians, sin, sqrt

ENDPOINT_TOLERANCE_M = 10.0


def _coordinate(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    lon, lat = value
    # Check bounds first: isfinite(very_large_json_integer) can overflow.
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return (lon, lat) if isfinite(lon) and isfinite(lat) else None


def _point(value):
    return _coordinate([value.get('lon'), value.get('lat')]) if isinstance(value, dict) else None


def _distance(a, b):
    lat1, lat2 = radians(a[1]), radians(b[1])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin(radians(b[0] - a[0]) / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(min(1.0, max(0.0, h))))


def passenger_route_preview(route, pickup, dropoff):
    """Return only a safe road segment and its preview provenance, or None."""
    if not isinstance(route, dict):
        return None
    raw, provider = route.get('coordinates'), route.get('provider')
    start, end = _point(pickup), _point(dropoff)
    if (not isinstance(raw, (list, tuple)) or not 2 <= len(raw) <= 100_000
            or not isinstance(provider, str) or not provider.strip() or len(provider) > 200
            or start is None or end is None):
        return None
    coordinates = [_coordinate(vertex) for vertex in raw]
    if any(vertex is None for vertex in coordinates):
        return None

    def cluster(point):
        indices = [i for i, vertex in enumerate(coordinates)
                   if _distance(point, vertex) <= ENDPOINT_TOLERANCE_M]
        # More than one visit to the endpoint neighbourhood is ambiguous.
        if not indices or indices[-1] - indices[0] + 1 != len(indices):
            return None
        return indices[0], indices[-1]

    pickup_cluster, dropoff_cluster = cluster(start), cluster(end)
    if pickup_cluster is None or dropoff_cluster is None:
        return None
    first, last = pickup_cluster[1], dropoff_cluster[0]
    if first >= last:
        return None
    segment = coordinates[first:last + 1]
    if len(set(segment)) < 2:
        return None
    return {'coordinates': [list(vertex) for vertex in segment], 'provider': provider,
            'preview': True, 'estimated': True}
