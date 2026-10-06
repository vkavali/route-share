"""Manual, cached Nominatim place search for the local beta."""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GeocodingError(Exception):
    """The upstream place search could not provide a usable response."""


_lock = threading.Lock()
_cache: OrderedDict[tuple[str, str, str], tuple[float, list[dict]]] = OrderedDict()
_last_started = 0.0
_CACHE_TTL = 24 * 60 * 60
_CACHE_MAX = 256
_MIN_INTERVAL = 1.0


def _fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read(1_000_000)


class NominatimGeocoder:
    """A process-wide serialized/rate-limited client for manual searches."""

    def __init__(self, base_url="https://nominatim.openstreetmap.org/search", *, fetcher=None, clock=None, sleeper=None):
        self.base_url = base_url.rstrip("?")
        self.fetcher = fetcher or _fetch
        self.clock = clock or time.time
        self.sleeper = sleeper or time.sleep

    def search(self, query: str, language: str) -> list[dict]:
        global _last_started
        key = (self.base_url, " ".join(query.casefold().split()), language)
        with _lock:
            now = self.clock()
            cached = _cache.get(key)
            if cached and now - cached[0] < _CACHE_TTL:
                _cache.move_to_end(key)
                return [dict(place) for place in cached[1]]
            if cached:
                del _cache[key]
            wait = _MIN_INTERVAL - (now - _last_started)
            if wait > 0:
                self.sleeper(wait)
            params = urlencode({"q": query, "format": "jsonv2", "countrycodes": "in", "limit": 6})
            url = f"{self.base_url}?{params}"
            headers = {"User-Agent": "RouteShareLocalPrototype/0.1", "Accept-Language": language}
            _last_started = self.clock()
            try:
                payload = self.fetcher(url, headers, 8)
                rows = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
                if not isinstance(rows, list):
                    raise ValueError("Unexpected response")
                places = []
                for row in rows[:6]:
                    if not isinstance(row, dict):
                        continue
                    try:
                        lat, lon = float(row["lat"]), float(row["lon"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    label = str(row.get("name") or row.get("display_name") or "").strip()
                    if label and -90 <= lat <= 90 and -180 <= lon <= 180:
                        places.append({"label": label[:240], "lat": lat, "lon": lon})
            except (URLError, TimeoutError, OSError, ValueError, TypeError, UnicodeError) as exc:
                raise GeocodingError("Place search is temporarily unavailable. Check your connection and try again.") from exc
            _cache[key] = (self.clock(), places)
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
            return [dict(place) for place in places]


def clear_geocode_cache_for_tests() -> None:
    global _last_started
    with _lock:
        _cache.clear()
        _last_started = 0.0
