from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError

import pytest

from app import routing
from app.routing import (
    MAX_RESPONSE_BYTES,
    OSRMProvider,
    RoutingBudgetExceeded,
    RoutingError,
    routing_budget,
    routing_checkpoint,
)


POINTS = [{"lat": 17.0, "lon": 78.0}, {"lat": 17.1, "lon": 78.1}]


def payload():
    return {
        "code": "Ok",
        "routes": [{
            "geometry": {"coordinates": [[78.0, 17.0], [78.1, 17.1]]},
            "distance": 1234,
            "duration": 900,
            "legs": [{"distance": 1234, "duration": 900}],
        }],
        "waypoints": [
            {"distance": 2, "location": [78.0, 17.0]},
            {"distance": 3, "location": [78.1, 17.1]},
        ],
    }


class FakeResponse:
    def __init__(self, body: bytes, on_read=None):
        self.body = body
        self.on_read = on_read
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        self.read_size = size
        if self.on_read:
            self.on_read()
        return self.body if size < 0 else self.body[:size]


def fake_open(monkeypatch, fn):
    monkeypatch.setattr(routing, "urlopen", fn)


def test_call_budget_counts_only_upstream_misses_and_cache_hits_still_check_deadline(monkeypatch):
    calls = []

    def open_route(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider(timeout=8)
    with routing_budget(seconds=30, max_calls=1) as budget:
        result = provider.route(POINTS)
        assert result["distance_m"] == 1234
        assert budget.calls == 1
        assert provider.route(POINTS)["calculation_id"] == result["calculation_id"]
        assert budget.calls == 1
        with pytest.raises(RoutingBudgetExceeded, match="call budget"):
            provider.route([POINTS[0], {"lat": 17.2, "lon": 78.2}])
    assert len(calls) == 1
    assert calls[0][0].get_header("User-agent") == OSRMProvider.user_agent
    assert routing_checkpoint() is None


def test_deadline_sets_remaining_timeout_and_checks_after_response(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(routing.time, "monotonic", lambda: now[0])
    timeouts = []

    def open_route(_request, timeout):
        timeouts.append(timeout)
        return FakeResponse(json.dumps(payload()).encode(), on_read=lambda: now.__setitem__(0, now[0] + 4))

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider(timeout=8)
    with routing_budget(seconds=3, max_calls=2):
        with pytest.raises(RoutingBudgetExceeded, match="time budget"):
            provider.route(POINTS)
    assert timeouts == [3]
    assert provider.cache == {}


def test_budget_timeout_is_minimum_of_provider_timeout_and_remaining(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(routing.time, "monotonic", lambda: now[0])
    timeouts = []

    def open_route(_request, timeout):
        timeouts.append(timeout)
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider(timeout=2)
    with routing_budget(seconds=10, max_calls=1):
        provider.route(POINTS)
    assert timeouts == [2]


def test_cache_is_lru_bounded_and_expires_by_ttl(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(routing.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(routing, "ROUTE_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(routing, "ROUTE_CACHE_TTL_SECONDS", 5)
    calls = []

    def open_route(_request, timeout):
        calls.append(1)
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider()
    points = [
        POINTS,
        [POINTS[0], {"lat": 17.2, "lon": 78.2}],
        [POINTS[0], {"lat": 17.3, "lon": 78.3}],
    ]
    for pair in points:
        provider.route(pair)
    assert len(provider.cache) == 2
    provider.route(points[1])  # Refresh the least-recently-used entry.
    provider.route(points[0])
    assert len(calls) == 4  # The original least-recently-used key was evicted.
    now[0] += 6
    provider.route(points[1])
    assert len(calls) == 5  # Expired entries are fetched again.
    assert len(provider.cache) == 1
    assert provider._cache_bytes == sum(entry[2] for entry in provider.cache.values())


def test_cache_obeys_serialized_byte_budget_and_skips_single_oversized_entry(monkeypatch):
    calls = []

    def open_route(_request, timeout):
        calls.append(1)
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider()
    first = provider.route(POINTS)
    first_key = first["calculation_id"]
    first_size = provider.cache[first_key][2]
    monkeypatch.setattr(routing, "ROUTE_CACHE_MAX_BYTES", first_size * 2 - 1)
    second_points = [POINTS[0], {"lat": 17.2, "lon": 78.2}]
    second = provider.route(second_points)
    second_key = second["calculation_id"]
    assert first_key not in provider.cache
    assert second_key in provider.cache
    assert provider._cache_bytes == provider.cache[second_key][2] <= routing.ROUTE_CACHE_MAX_BYTES

    monkeypatch.setattr(routing, "ROUTE_CACHE_MAX_BYTES", first_size - 1)
    other = OSRMProvider()
    other.route([POINTS[0], {"lat": 17.3, "lon": 78.3}])
    assert other.cache == {}
    assert other._cache_bytes == 0
    assert len(calls) == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["routes"][0].update(distance=-1),
        lambda data: data["routes"][0].update(duration=float("nan")),
        lambda data: data["routes"][0]["legs"][0].update(duration=True),
        lambda data: data["routes"][0]["legs"][0].update(distance=-1),
        lambda data: data["routes"][0]["legs"][0].update(distance=float("inf")),
        lambda data: data["routes"][0]["legs"][0].update(distance=True),
        lambda data: data["routes"][0]["geometry"]["coordinates"][1].__setitem__(0, 181),
        lambda data: data["routes"][0]["geometry"]["coordinates"][1].__setitem__(1, float("inf")),
        lambda data: data["waypoints"][0].update(distance=-1),
        lambda data: data["waypoints"][0].update(distance=501),
        lambda data: data["waypoints"][0].update(location=[78, 91]),
        lambda data: data["waypoints"][0].update(location=[78]),
    ],
    ids=["negative-distance", "nan-duration", "boolean-leg-duration", "negative-leg-distance",
         "infinite-leg-distance", "boolean-leg-distance", "longitude-range", "infinite-latitude",
         "negative-snap", "snap-over-limit", "waypoint-latitude", "malformed-waypoint"],
)
def test_malformed_numeric_geometry_and_waypoints_fail_without_caching(monkeypatch, mutate):
    data = payload()
    mutate(data)
    fake_open(monkeypatch, lambda *_args, **_kwargs: FakeResponse(json.dumps(data).encode()))
    provider = OSRMProvider()
    with pytest.raises(RoutingError):
        provider.route(POINTS)
    assert provider.cache == {}
    assert provider._cache_bytes == 0


def test_concurrent_contexts_have_independent_call_budgets(monkeypatch):
    calls = []
    call_lock = threading.Lock()
    first_done = threading.Barrier(2)

    def open_route(request, timeout):
        with call_lock:
            calls.append(request.full_url)
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider()

    def work(index):
        first = [POINTS[0], {"lat": 17.1 + index / 10, "lon": 78.1}]
        second = [POINTS[0], {"lat": 17.2 + index / 10, "lon": 78.2}]
        with routing_budget(seconds=30, max_calls=1):
            provider.route(first)
            first_done.wait(timeout=5)
            with pytest.raises(RoutingBudgetExceeded, match="call budget"):
                provider.route(second)
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(work, (1, 2))) == [True, True]
    assert len(calls) == 2


def test_failed_malformed_and_oversized_responses_are_not_cached(monkeypatch):
    calls = []

    def open_route(_request, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise URLError("offline")
        if len(calls) == 2:
            return FakeResponse(b"not-json")
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider()
    for _ in range(2):
        with pytest.raises(RoutingError):
            provider.route(POINTS)
        assert provider.cache == {}
    assert provider.route(POINTS)["distance_m"] == 1234
    assert len(calls) == 3

    oversized = FakeResponse(b" " * (MAX_RESPONSE_BYTES + 1))
    fake_open(monkeypatch, lambda *_args, **_kwargs: oversized)
    other = OSRMProvider()
    with pytest.raises(RoutingError, match="oversized"):
        other.route(POINTS)
    assert oversized.read_size == MAX_RESPONSE_BYTES + 1
    assert other.cache == {}


def test_cache_returns_defensive_copies_and_rejects_invalid_input_points(monkeypatch):
    calls = []

    def open_route(_request, timeout):
        calls.append(1)
        return FakeResponse(json.dumps(payload()).encode())

    fake_open(monkeypatch, open_route)
    provider = OSRMProvider()
    first = provider.route(POINTS)
    first["coordinates"][0][0] = -999
    assert provider.route(POINTS)["coordinates"][0] == [78.0, 17.0]
    assert len(calls) == 1

    for bad_points in ([], [POINTS[0]], [{"lat": float("inf"), "lon": 78}, POINTS[1]],
                       [{"lat": 17, "lon": 10**10000}, POINTS[1]]):
        with pytest.raises(RoutingError):
            provider.route(bad_points)
