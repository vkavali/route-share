"""Explicit, cached India place lookup. Public Nominatim is not autocomplete."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import threading
import time
from collections import OrderedDict
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class GeocodingError(Exception):
    """The upstream place search could not provide a usable response."""


# Cache hits never wait for network I/O. The separate upstream lock serializes
# search AND reverse, including requests made by different geocoder instances.
_lock = threading.Lock()
_upstream_lock = threading.Lock()
_cache: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
_last_started = 0.0
_CACHE_TTL = 24 * 60 * 60
_CACHE_MAX = 256
_MIN_INTERVAL = 1.0
_QUEUE_TIMEOUT = 10
_UNAVAILABLE = "Place search is temporarily unavailable. Check your connection and try again."
# Exact city alias only: the Telugu query was live-verified to miss the city.
# Keep label language independent; never rewrite longer landmark/address queries.
_CITY_ALIASES = {"హైదరాబాద్": "Hyderabad"}


def _fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read(1_000_000)


def _text(value, limit=1000):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _place(row):
    """Public place shape; bbox is [south, north, west, east], NOT GeoJSON order."""
    if not isinstance(row, dict):
        return None
    try:
        lat, lon = float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    details = row.get("address")
    if isinstance(details, dict) and details.get("country_code", "in") != "in":
        return None
    address = _text(row.get("display_name"))
    name = _text(row.get("name"), 240) or address[:240]
    if not name:
        return None
    kind = _text(row.get("addresstype") or row.get("type"), 80)
    osm_type, osm_id = row.get("osm_type"), str(row.get("osm_id", ""))
    if osm_type in {"node", "way", "relation"} and osm_id.isdecimal():
        identity = f"osm:{osm_type}:{osm_id}"
    else:
        # Deterministic fallback, never use transient Nominatim database place_id.
        identity = "place:" + hashlib.sha256(f"{lat}:{lon}:{name}:{kind}".encode()).hexdigest()[:24]
    bbox = None
    raw_bbox = row.get("boundingbox")
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            south, north, west, east = map(float, raw_bbox)
            if all(math.isfinite(v) for v in (south, north, west, east)) and -90 <= south <= north <= 90 and -180 <= west <= east <= 180:
                bbox = [south, north, west, east]
        except (TypeError, ValueError, OverflowError):
            pass
    return {"label": name[:120], "lat": lat, "lon": lon, "id": identity,
            "name": name, "address": address or name, "kind": kind, "bbox": bbox}


class NominatimGeocoder:
    """One-process provider schedule, bounded cache and explicit search/reverse."""

    def __init__(self, base_url="https://nominatim.openstreetmap.org/search", *, fetcher=None, clock=None, sleeper=None):
        self.base_url = base_url.rstrip("?")
        parts = urlsplit(self.base_url)
        self.reverse_url = urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/", 1)[0] + "/reverse", "", ""))
        self.fetcher = fetcher or _fetch
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep

    def _cached(self, key):
        with _lock:
            cached = _cache.get(key)
            if cached and self.clock() - cached[0] < _CACHE_TTL:
                _cache.move_to_end(key)
                return True, deepcopy(cached[1])
            if cached:
                del _cache[key]
        return False, None

    def _request(self, endpoint, params, language, parse):
        global _last_started
        key = (endpoint, tuple(params.items()), language)
        found, cached = self._cached(key)
        if found:
            return cached
        if not _upstream_lock.acquire(timeout=_QUEUE_TIMEOUT):
            raise GeocodingError(_UNAVAILABLE)
        try:
            # A matching in-flight request may have filled the cache while we
            # queued. Recheck to coalesce it without a second provider request.
            found, cached = self._cached(key)
            if found:
                return cached
            wait = _MIN_INTERVAL - (self.clock() - _last_started)
            if wait > 0:
                self.sleeper(wait)
            _last_started = self.clock()
            headers = {"User-Agent": "RouteShareLocalPrototype/0.1", "Accept-Language": language}
            try:
                payload = self.fetcher(f"{endpoint}?{urlencode(params)}", headers, 8)
                rows = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
                value = parse(rows)
            except (URLError, TimeoutError, OSError, ValueError, TypeError, UnicodeError) as exc:
                raise GeocodingError(_UNAVAILABLE) from exc
            with _lock:
                _cache[key] = (self.clock(), deepcopy(value))
                _cache.move_to_end(key)
                while len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
            return value
        finally:
            _upstream_lock.release()

    def search(self, query: str, language: str) -> list[dict]:
        normalized = " ".join(query.casefold().split())
        query = _CITY_ALIASES.get(normalized, normalized)

        def parse(rows):
            if not isinstance(rows, list):
                raise ValueError("Unexpected search response")
            places, seen = [], set()
            for row in rows[:6]:
                place = _place(row)
                if place and place["id"] not in seen:
                    seen.add(place["id"])
                    places.append(place)
            return places

        return self._request(self.base_url, {"q": query, "format": "jsonv2", "countrycodes": "in", "limit": 6, "addressdetails": 1}, language, parse)

    def reverse(self, lat: float, lon: float, language: str) -> dict | None:
        """Return a nearby OSM object's address; NEVER move the selected point."""
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")

        def parse(row):
            if not isinstance(row, dict):
                raise ValueError("Unexpected reverse response")
            if row.get("error") == "Unable to geocode":
                return None
            if "error" in row:
                raise ValueError("Reverse provider error")
            if not isinstance(row.get("address"), dict):
                raise ValueError("Missing reverse address")
            if row["address"].get("country_code") != "in":
                return None
            place = _place(row)
            if place is None:
                raise ValueError("Invalid reverse place")
            return place

        # Six decimals (~0.11m) coalesce insignificant coordinate string noise.
        return self._request(self.reverse_url, {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "addressdetails": 1, "zoom": 18}, language, parse)


def clear_geocode_cache_for_tests() -> None:
    global _last_started
    with _upstream_lock, _lock:
        _cache.clear()
        _last_started = 0.0
