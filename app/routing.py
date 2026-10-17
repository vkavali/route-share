"""Replaceable road routing. Failure is never replaced by straight-line driving."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ROUTE_CACHE_MAX_ENTRIES = 256
# This caps serialized JSON payload bytes; it bounds retained data, not Python heap overhead.
ROUTE_CACHE_MAX_BYTES = 16 * 1024 * 1024
ROUTE_CACHE_TTL_SECONDS = 300


class RoutingError(Exception):
    pass


class RoutingBudgetExceeded(RoutingError):
    """The current request has exhausted its elapsed-time or upstream-call budget."""


class _RoutingBudget:
    def __init__(self, deadline: float, max_calls: int):
        self.deadline = deadline
        self.max_calls = max_calls
        self.calls = 0


_CURRENT_ROUTING_BUDGET: ContextVar[_RoutingBudget | None] = ContextVar("seatpal_routing_budget", default=None)


@contextmanager
def routing_budget(seconds: float = 12, max_calls: int = 60):
    """Install an elapsed-time and upstream-call budget for the current request context."""
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError("Routing budget seconds must be a finite positive number.")
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 0:
        raise ValueError("Routing budget max_calls must be a non-negative integer.")
    budget = _RoutingBudget(time.monotonic() + seconds, max_calls)
    token = _CURRENT_ROUTING_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_ROUTING_BUDGET.reset(token)


def routing_checkpoint(*, consume_call: bool = False) -> float | None:
    """Check the active deadline; optionally account for one real upstream call."""
    budget = _CURRENT_ROUTING_BUDGET.get()
    if budget is None:
        return None
    remaining = budget.deadline - time.monotonic()
    if remaining <= 0:
        raise RoutingBudgetExceeded("Routing time budget exceeded. Retry your calculation.")
    if consume_call:
        if budget.calls >= budget.max_calls:
            raise RoutingBudgetExceeded("Routing call budget exceeded. Retry your calculation.")
        budget.calls += 1
    return remaining


def _valid_measurement(value):
    """Validate finite, non-negative JSON measurements without bool/overflow coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value)) and value >= 0
    except (OverflowError, ValueError):
        return False


def _valid_location(location):
    if not isinstance(location, list) or len(location) != 2:
        return False
    if any(type(value) not in (int, float) for value in location):
        return False
    try:
        longitude, latitude = (float(value) for value in location)
        return (math.isfinite(longitude) and math.isfinite(latitude)
                and -180 <= longitude <= 180 and -90 <= latitude <= 90)
    except (OverflowError, ValueError):
        return False


def _read_payload(response):
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if isinstance(body, str):
        size = len(body.encode("utf-8"))
    elif isinstance(body, (bytes, bytearray)):
        size = len(body)
    else:
        raise ValueError("Invalid routing response body.")
    if size > MAX_RESPONSE_BYTES:
        raise RoutingError("Road routing returned an oversized response. Retry your calculation.")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Invalid routing response object.")
    return payload


class OSRMProvider:
    name = "OSRM road routing (no live traffic)"
    user_agent = "RouteShare-LocalEvaluation/0.1"

    def __init__(self, store=None, base_url=None, timeout=8):
        self.store = store
        self.base_url = (base_url or os.environ.get("ROUTING_BASE_URL", "https://router.project-osrm.org")).rstrip("/")
        self.timeout = timeout
        self.cache: OrderedDict[str, tuple[float, dict, int]] = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = threading.Lock()

    def _cache_get(self, key: str):
        now = time.monotonic()
        with self._cache_lock:
            entry = self.cache.get(key)
            if entry is None:
                return None
            inserted_at, result, serialized_bytes = entry
            if now - inserted_at >= ROUTE_CACHE_TTL_SECONDS:
                del self.cache[key]
                self._cache_bytes -= serialized_bytes
                return None
            self.cache.move_to_end(key)
            return copy.deepcopy(result)

    def _cache_set(self, key: str, result: dict) -> None:
        now = time.monotonic()
        serialized_bytes = len(json.dumps(result, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        if serialized_bytes > ROUTE_CACHE_MAX_BYTES:
            return
        with self._cache_lock:
            for old_key, (inserted_at, _, old_bytes) in list(self.cache.items()):
                if now - inserted_at >= ROUTE_CACHE_TTL_SECONDS:
                    del self.cache[old_key]
                    self._cache_bytes -= old_bytes
            previous = self.cache.pop(key, None)
            if previous is not None:
                self._cache_bytes -= previous[2]
            self.cache[key] = (now, copy.deepcopy(result), serialized_bytes)
            self._cache_bytes += serialized_bytes
            self.cache.move_to_end(key)
            while len(self.cache) > ROUTE_CACHE_MAX_ENTRIES or self._cache_bytes > ROUTE_CACHE_MAX_BYTES:
                _, (_, _, evicted_bytes) = self.cache.popitem(last=False)
                self._cache_bytes -= evicted_bytes

    def route(self, points):
        # A cache hit still consumes request time and must honor an exhausted budget.
        routing_checkpoint()
        if (not isinstance(points, (list, tuple)) or len(points) < 2
                or any(not isinstance(point, dict)
                       or not _valid_location([point.get("lon"), point.get("lat")])
                       for point in points)):
            raise RoutingError("Choose at least two valid map points to calculate a road route.")
        coords = ";".join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in points)
        key = hashlib.sha256((self.base_url + coords).encode()).hexdigest()
        cached = self._cache_get(key)
        if cached is not None:
            routing_checkpoint()
            return cached

        url = (self.base_url + "/route/v1/driving/" + coords
               + "?overview=full&geometries=geojson&steps=false&radiuses="
               + ";".join("500" for _ in points))
        try:
            remaining = routing_checkpoint(consume_call=True)
            timeout = self.timeout if remaining is None else min(self.timeout, remaining)
            request = Request(url, headers={"User-Agent": self.user_agent})
            with urlopen(request, timeout=timeout) as response:
                payload = _read_payload(response)
            routing_checkpoint()

            routes = payload.get("routes")
            if payload.get("code") != "Ok" or not isinstance(routes, list) or not routes:
                raise RoutingError("No road route found within 500 m of the selected points. Choose a reachable meeting point.")
            route = routes[0]
            waypoints = payload.get("waypoints")
            legs = route.get("legs") if isinstance(route, dict) else None
            geometry = route.get("geometry") if isinstance(route, dict) else None
            coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
            if (not isinstance(waypoints, list) or len(waypoints) != len(points)
                    or any(not isinstance(w, dict)
                           or not _valid_measurement(w.get("distance"))
                           or w["distance"] > 500 or not _valid_location(w.get("location"))
                           for w in waypoints)):
                raise RoutingError("A point is too far from a reachable road. Choose another exact point.")
            if not isinstance(legs, list) or len(legs) != len(points) - 1 or not isinstance(coordinates, list):
                raise RoutingError("Routing returned an incomplete route. Retry your calculation.")
            leg_distances = [leg.get("distance") if isinstance(leg, dict) else None for leg in legs]
            leg_durations = [leg.get("duration") if isinstance(leg, dict) else None for leg in legs]
            if (not _valid_measurement(route.get("distance"))
                    or not _valid_measurement(route.get("duration"))
                    or any(not _valid_measurement(value) for value in leg_distances)
                    or any(not _valid_measurement(value) for value in leg_durations)
                    or any(not _valid_location(location) for location in coordinates)):
                raise RoutingError("Routing returned invalid route geometry or measurements. Retry your calculation.")
            result = {
                "coordinates": coordinates,
                "distance_m": route["distance"],
                "duration_s": route["duration"],
                "leg_durations_s": leg_durations,
                "leg_distances_m": leg_distances,
                "waypoints": waypoints,
                "provider": self.name,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
                "calculation_id": key,
                "traffic": False,
                "snap_limit_m": 500,
            }
            if len(result["coordinates"]) < 2:
                raise RoutingError("Routing returned an incomplete route. Retry your calculation.")
            routing_checkpoint()
            self._cache_set(key, result)
            return result
        except RoutingError:
            raise
        except (URLError, TimeoutError, ValueError, KeyError, OSError, TypeError, IndexError, AttributeError) as exc:
            raise RoutingError("Road routing is unavailable. Nothing has been confirmed; retry shortly.") from exc
