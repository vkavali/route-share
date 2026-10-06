"""Deterministic matching checks using a labelled synthetic road provider."""
import pytest

from app.matching import Incompatible, available_capacity, evaluate, inventory


class FixtureRoadProvider:
    """Test fixture only; this is not a live route or traffic estimate."""

    name = "FIXTURE ONLY - synthetic line route"

    def __init__(self, stop_delay_s=120):
        self.stop_delay_s = stop_delay_s

    def route(self, points):
        deltas = [abs(b["lon"] - a["lon"]) for a, b in zip(points, points[1:])]
        total = sum(deltas) or 1
        delay = self.stop_delay_s * max(0, len(points) - 2)
        legs = [3600 * delta / total + delay / len(deltas) for delta in deltas]
        return {
            "coordinates": [[p["lon"], p["lat"]] for p in points],
            "distance_m": 111_195 * total,
            "duration_s": sum(legs),
            "leg_durations_s": legs,
            "waypoints": [],
            "provider": self.name,
            "calculated_at": "2030-01-01T00:00:00+00:00",
        }


def point(lon):
    return {"label": f"fixture {lon}", "lat": 0.0, "lon": lon}


def route(points=None, duration_s=3600):
    coordinates = [[0.0, 0.0], [1.0, 0.0]] if points is None else points
    return {
        "coordinates": coordinates,
        "distance_m": 111_195,
        "duration_s": duration_s,
        "leg_durations_s": [duration_s],
        "waypoints": [],
        "provider": "FIXTURE ONLY - synthetic line route",
        "calculated_at": "2030-01-01T00:00:00+00:00",
    }


def trip(*, seats=2, max_detour_minutes=10):
    return {
        "id": "trip-fixture",
        "origin": point(0.0),
        "destination": point(1.0),
        "departure": "2030-01-01T09:00:00+05:30",
        "seats": seats,
        "max_detour_minutes": max_detour_minutes,
        "route": route(),
    }


def request(*, origin=0.2, destination=0.8, seats=1,
            window_start="2030-01-01T09:10:00+05:30",
            window_end="2030-01-01T09:25:00+05:30"):
    return {
        "id": "request-fixture",
        "origin": point(origin),
        "destination": point(destination),
        "seats": seats,
        "window_start": window_start,
        "window_end": window_end,
    }


def test_evaluate_returns_ordered_segment_and_labels_provider_as_fixture():
    result = evaluate(trip(), request(), [], FixtureRoadProvider())

    assert result["start_m"] < result["end_m"]
    assert result["available_seats"] == 2
    assert result["proposed_route"]["provider"].startswith("FIXTURE ONLY")
    assert result["incremental_detour_minutes"] == pytest.approx(4.0)
    assert result["baseline_match"] is False


def test_reverse_segment_is_excluded():
    with pytest.raises(Incompatible, match="against the driver route"):
        evaluate(trip(), request(origin=0.8, destination=0.2), [], FixtureRoadProvider())


def test_pickup_outside_requested_time_window_is_excluded():
    with pytest.raises(Incompatible, match="miss a passenger pickup window"):
        evaluate(
            trip(),
            request(window_start="2030-01-01T09:45:00+05:30",
                    window_end="2030-01-01T10:00:00+05:30"),
            [],
            FixtureRoadProvider(),
        )


def test_cumulative_detour_over_driver_limit_is_excluded():
    with pytest.raises(Incompatible, match="cumulative detour"):
        evaluate(trip(max_detour_minutes=2), request(), [], FixtureRoadProvider(stop_delay_s=300))


def test_completed_segment_remains_occupied_and_adjacent_segment_reuses_capacity():
    driver_trip = trip(seats=1)
    completed = [{"id": "old", "status": "segment_completed", "seats": 1,
                  "start_m": 10_000, "end_m": 50_000}]

    assert available_capacity(driver_trip, completed, 20_000, 40_000) == 0
    assert available_capacity(driver_trip, completed, 50_000, 70_000) == 1
    rows = inventory(driver_trip, completed)
    assert any(s["available"] == 0 and s["from_m"] < 40_000 < s["to_m"] for s in rows)


def test_baseline_match_flag_uses_trip_endpoints():
    result = evaluate(
        trip(), request(origin=0.01, destination=0.99,
                        window_start="2030-01-01T09:00:00+05:30",
                        window_end="2030-01-01T10:00:00+05:30"),
        [], FixtureRoadProvider(),
    )
    assert result["baseline_match"] is True
