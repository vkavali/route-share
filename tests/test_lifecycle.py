"""Service lifecycle tests with a deterministic synthetic road provider.

The provider is an explicitly labelled fixture, not live road or traffic data.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import sqlite3

import pytest

from app.domain import CORRIDORS, DomainError, Service
from app.routing import RoutingError
from app.store import Store


class FixtureRoadProvider:
    """Synthetic direct-line estimates; never used as production routing evidence."""

    name = "FIXTURE ONLY - synthetic direct line, no road or traffic claim"

    def __init__(self):
        self.fail_search_routes = False

    @staticmethod
    def _distance(a, b):
        lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
        dlat = lat2 - lat1
        dlon = math.radians(b["lon"] - a["lon"])
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6_371_000 * 2 * math.asin(min(1, math.sqrt(h)))

    def route(self, points):
        if self.fail_search_routes and len(points) > 2:
            raise RoutingError("FIXTURE ROUTING FAILURE - no match confirmed")
        geometry = points
        # The two real corridor fixtures below keep the same named landmarks as
        # the domain geography checks. Other routes remain synthetic point paths.
        if len(points) == 2 and points[0]["label"] == "Kondapur":
            if points[-1]["label"] == "Vijayawada":
                line = CORRIDORS[0]
            elif points[-1]["label"] == "Kothakota":
                line = CORRIDORS[1]
            else:
                line = None
            if line:
                closest = min(range(len(line)), key=lambda i: self._distance(
                    {"lon": line[i][0], "lat": line[i][1]}, points[-1]))
                geometry = [points[0], *(
                    {"label": "fixture corridor point", "lon": c[0], "lat": c[1]}
                    for c in line[1:closest + 1]
                ), points[-1]]
        lengths = [self._distance(a, b) for a, b in zip(points, points[1:])]
        base = sum(lengths) / 15  # synthetic 54 km/h baseline
        extra = max(0, len(points) - 2) * 90  # synthetic stop penalty
        penalty_per_leg = extra / max(1, len(lengths))
        leg_durations = [d / 15 + penalty_per_leg for d in lengths]
        return {
            "coordinates": [[p["lon"], p["lat"]] for p in geometry],
            "distance_m": sum(self._distance(a, b) for a, b in zip(geometry, geometry[1:])),
            "duration_s": base + extra,
            "leg_durations_s": leg_durations,
            "waypoints": [{"distance": 0} for _ in points],
            "provider": self.name,
            "calculated_at": "2030-01-01T00:00:00+00:00",
            "traffic": False,
        }


KONDAPUR = {"label": "Kondapur", "lat": 17.460, "lon": 78.357}
SURYAPET = {"label": "Suryapet", "lat": 17.139, "lon": 79.620}
NANDIGAMA = {"label": "Nandigama", "lat": 16.771, "lon": 80.285}
VIJAYAWADA = {"label": "Vijayawada", "lat": 16.506, "lon": 80.648}
ADDAKAL = {"label": "Addakal", "lat": 16.491, "lon": 77.950}
KOTHakota = {"label": "Kothakota", "lat": 16.374, "lon": 77.971}


def make_service(tmp_path, router=None):
    path = tmp_path / "service.sqlite3"
    store = Store(path)
    driver_approval = {
        "kind": "development",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }
    users = {
        "driver": {"id": "driver", "name": "Fixture Driver", "role": "member", "phone": "",
                   "vehicle": {"model": "Fixture car", "plate": "TEST"},
                   "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")},
                   "development": True, "driver_approved": True, "driver_approval": driver_approval},
        "driver2": {"id": "driver2", "name": "Second Fixture Driver", "role": "member", "phone": "",
                    "vehicle": {"model": "Second fixture car", "plate": "TEST2"},
                    "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")},
                    "development": True, "driver_approved": True, "driver_approval": driver_approval},
        "passenger": {"id": "passenger", "name": "Fixture Passenger", "role": "member", "phone": "",
                      "vehicle": {}, "verification": {}, "development": True},
        "passenger2": {"id": "passenger2", "name": "Fixture Passenger Two", "role": "member", "phone": "",
                       "vehicle": {}, "verification": {}, "development": True},
        "other": {"id": "other", "name": "Unrelated User", "role": "member", "phone": "",
                  "vehicle": {}, "verification": {}, "development": True},
        "admin": {"id": "admin", "name": "Fixture Staff", "role": "staff", "phone": "",
                  "vehicle": {}, "verification": {}, "development": True,
                  "staff_capabilities": ["ops.read", "safety.act"]},
    }
    with store.transaction() as tx:
        for user in users.values():
            tx.put("users", user["id"], user)
    return Service(store, router or FixtureRoadProvider()), store, users, path


def act(service, action, user, **payload):
    return service.dispatch(action, user, payload)


def future_departure(days=4):
    return (datetime.now(timezone.utc) + timedelta(days=days)).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).replace(hour=7, minute=0, second=0, microsecond=0).isoformat()


def publish(service, driver, origin, destination, departure=None, seats=1, detour=10):
    preview = act(service, "preview", driver, origin=origin, destination=destination,
                  departure=departure or future_departure(), seats=seats,
                  max_detour_minutes=detour)["preview"]
    result = act(service, "publish", driver, preview_id=preview["id"])
    return preview, result["trip"]


def search(service, passenger, origin, destination, departure, seats=1):
    at = datetime.fromisoformat(departure)
    return act(service, "search", passenger, origin=origin, destination=destination,
               window_start=at.isoformat(), window_end=(at + timedelta(hours=8)).isoformat(), seats=seats)


def search_between(service, passenger, origin, destination, window_start, window_end):
    return act(service, "search", passenger, origin=origin, destination=destination,
               window_start=window_start, window_end=window_end, seats=1)


def booking_for(service, passenger, origin, destination, departure):
    result = search(service, passenger, origin, destination, departure)
    assert result["matches"], "fixture route should produce a route-aware match"
    booking = act(service, "request", passenger, match_id=result["matches"][0]["id"])["booking"]
    return result, booking


def test_east_then_south_complete_booking_lifecycles_and_idempotent_actions(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver, passenger = users["driver"], users["passenger"]

    # East first: Kondapur -> Vijayawada with a Suryapet -> Nandigama booking.
    east_departure = future_departure(4)
    east_preview, east_trip = publish(service, driver, KONDAPUR, VIJAYAWADA, east_departure)
    east_again = act(service, "publish", driver, preview_id=east_preview["id"])["trip"]
    assert east_again["id"] == east_trip["id"]
    east_search, east_booking = booking_for(service, passenger, SURYAPET, NANDIGAMA, east_departure)
    east_booking_again = act(service, "request", passenger,
                             match_id=east_search["matches"][0]["id"])["booking"]
    assert east_booking_again["id"] == east_booking["id"]
    accepted = act(service, "accept", driver, booking_id=east_booking["id"])["booking"]
    assert accepted["status"] == "accepted"
    accepted_again = act(service, "accept", driver, booking_id=east_booking["id"])["booking"]
    assert accepted_again["id"] == accepted["id"]
    with pytest.raises(DomainError) as not_completed:
        act(service, "rate", passenger, booking_id=east_booking["id"], stars=5)
    assert not_completed.value.status == 409
    with pytest.raises(DomainError) as unrelated:
        act(service, "rate", users["other"], booking_id=east_booking["id"], stars=5)
    assert unrelated.value.status == 403
    assert act(service, "start_trip", driver, trip_id=east_trip["id"])["trip"]["status"] == "started"
    assert act(service, "complete_segment", passenger,
               booking_id=east_booking["id"])["booking"]["status"] == "segment_completed"
    assert act(service, "complete_trip", driver, trip_id=east_trip["id"])["trip"]["status"] == "completed"
    rating = act(service, "rate", passenger, booking_id=east_booking["id"], stars=5, comment="fixture")
    assert rating["rating"]["subject_id"] == driver["id"]
    assert act(service, "rate", passenger, booking_id=east_booking["id"], stars=1)["rating"]["stars"] == 5

    # South second: an independent trip creates and completes a new booking.
    south_departure = future_departure(5)
    _, south_trip = publish(service, driver, KONDAPUR, KOTHakota, south_departure)
    south_search, south_booking = booking_for(service, users["passenger2"], ADDAKAL,
                                               KOTHakota, south_departure)
    assert south_search["metrics"]["complete"] is True
    assert act(service, "accept", driver, booking_id=south_booking["id"])["booking"]["status"] == "accepted"
    assert act(service, "start_trip", driver, trip_id=south_trip["id"])["trip"]["status"] == "started"
    assert act(service, "complete_segment", driver,
               booking_id=south_booking["id"])["booking"]["status"] == "segment_completed"
    assert act(service, "complete_trip", driver, trip_id=south_trip["id"])["trip"]["status"] == "completed"
    assert len(act(service, "state", driver)["trips"]) == 2


def test_parallel_acceptance_cannot_overbook_the_same_segment(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=1)
    _, first = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    _, second = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, departure)

    def accept(booking_id):
        try:
            return act(service, "accept", users["driver"], booking_id=booking_id)["booking"]["status"]
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(accept, (first["id"], second["id"])))
    assert outcomes.count("accepted") == 1
    assert outcomes.count(409) == 1
    state = act(service, "state", users["driver"])
    assert sum(b["status"] == "accepted" for b in state["bookings"]) == 1
    assert next(t for t in state["trips"] if t["id"] == trip["id"])["inventory"]


def test_adjacent_passengers_reuse_capacity_but_overlapping_segment_does_not(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=1)
    # Create the overlapping pending booking while capacity is available; acceptance
    # must re-evaluate it after the two adjacent bookings consume the route.
    _, overlap_booking = booking_for(service, users["other"], SURYAPET, VIJAYAWADA, departure)

    _, west_booking = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    assert act(service, "accept", users["driver"], booking_id=west_booking["id"])["booking"]["status"] == "accepted"

    # Nandigama is the first booking's exact endpoint; the second segment begins there.
    _, east_booking = booking_for(service, users["passenger2"], NANDIGAMA, VIJAYAWADA, departure)
    assert act(service, "accept", users["driver"], booking_id=east_booking["id"])["booking"]["status"] == "accepted"

    with pytest.raises(DomainError) as full:
        act(service, "accept", users["driver"], booking_id=overlap_booking["id"])
    assert full.value.status == 409
    current = act(service, "state", users["driver"])
    current_trip = next(t for t in current["trips"] if t["id"] == trip["id"])
    assert max(segment["occupied"] for segment in current_trip["inventory"]) == 1


def test_zero_baseline_does_not_report_infinite_or_fabricated_match_lift(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    result = search(service, users["passenger"], SURYAPET, VIJAYAWADA, departure)
    metrics = result["metrics"]

    assert metrics["traditional_match_count"] == 0
    assert metrics["route_aware_match_count"] == 1
    assert metrics["incremental_matches"] == 1
    assert metrics["match_lift_percentage"] is None
    assert "same time-" in metrics["baseline_definition"]


def test_provider_failure_is_a_saved_incomplete_search_not_a_success_claim(tmp_path):
    router = FixtureRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    router.fail_search_routes = True

    result = search(service, users["passenger"], SURYAPET, VIJAYAWADA, departure)
    assert result["matches"] == []
    assert result["metrics"]["complete"] is False
    assert result["metrics"]["evaluation_errors"] == 1
    assert result["metrics"]["match_lift_percentage"] is None
    with store.read() as tx:
        saved = tx.get("requests", result["request"]["id"])
        events = tx.list("events")
    assert saved["metrics"]["complete"] is False
    assert any(e["kind"] == "search_incomplete" for e in events)


def test_failed_storage_write_never_returns_a_successful_publish(tmp_path, monkeypatch):
    service, store, users, path = make_service(tmp_path)
    preview = act(service, "preview", users["driver"], origin=KONDAPUR,
                  destination=VIJAYAWADA, departure=future_departure(), seats=1,
                  max_detour_minutes=10)["preview"]

    def failed_transaction():
        raise sqlite3.OperationalError("fixture disk write failure")

    monkeypatch.setattr(store, "transaction", failed_transaction)
    with pytest.raises(sqlite3.OperationalError, match="fixture disk write failure"):
        act(service, "publish", users["driver"], preview_id=preview["id"])
    with Store(path).read() as tx:
        assert tx.list("trips") == []


def test_rating_is_not_available_until_trip_and_segment_are_complete(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, booking = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    act(service, "accept", users["driver"], booking_id=booking["id"])
    with pytest.raises(DomainError) as early:
        act(service, "rate", users["passenger"], booking_id=booking["id"], stars=4)
    assert early.value.status == 409
    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    act(service, "complete_segment", users["passenger"], booking_id=booking["id"])
    act(service, "complete_trip", users["driver"], trip_id=trip["id"])
    assert act(service, "rate", users["driver"], booking_id=booking["id"], stars=4)["rating"]["subject_id"] == users["passenger"]["id"]


def test_one_passenger_request_can_confirm_on_only_one_driver_trip(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, first_trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, second_trip = publish(service, users["driver2"], KONDAPUR, VIJAYAWADA, departure)
    result = search(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    matches = {m["trip_id"]: m for m in result["matches"]}
    assert set(matches) == {first_trip["id"], second_trip["id"]}
    first = act(service, "request", users["passenger"], match_id=matches[first_trip["id"]]["id"])["booking"]
    alternative = act(service, "request", users["passenger"], match_id=matches[second_trip["id"]]["id"])["booking"]

    confirmed = act(service, "accept", users["driver"], booking_id=first["id"])["booking"]
    assert confirmed["status"] == "accepted"
    with store.read() as tx:
        saved_alternative = tx.get("bookings", alternative["id"])
    assert saved_alternative["status"] == "cancelled"
    with pytest.raises(DomainError) as already_confirmed:
        act(service, "accept", users["driver2"], booking_id=alternative["id"])
    assert already_confirmed.value.status == 409


def test_new_stop_cannot_push_existing_passenger_outside_their_pickup_window(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)

    broad = search(service, users["passenger"], NANDIGAMA, VIJAYAWADA, departure)
    expected = datetime.fromisoformat(broad["matches"][0]["pickup_at"])
    narrow = search_between(service, users["passenger"], NANDIGAMA, VIJAYAWADA,
                            (expected - timedelta(seconds=30)).isoformat(),
                            (expected + timedelta(seconds=30)).isoformat())
    first = act(service, "request", users["passenger"], match_id=narrow["matches"][0]["id"])["booking"]
    later_booking_search = search(service, users["passenger2"], SURYAPET, NANDIGAMA, departure)
    delayed = act(service, "request", users["passenger2"],
                  match_id=later_booking_search["matches"][0]["id"])["booking"]
    act(service, "accept", users["driver"], booking_id=first["id"])
    with pytest.raises(DomainError, match="Availability changed") as outside_window:
        act(service, "accept", users["driver"], booking_id=delayed["id"])
    assert outside_window.value.status == 409
    with store.read() as tx:
        saved_first = tx.get("bookings", first["id"])
        saved_delayed = tx.get("bookings", delayed["id"])
        saved_trip = tx.get("trips", trip["id"])
    assert saved_first["status"] == "accepted"
    assert saved_delayed["status"] == "pending"
    assert saved_trip["version"] == 2


def test_cancelled_prestart_booking_releases_its_overlapping_segment(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=1)
    _, first = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    _, second = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, departure)
    act(service, "accept", users["driver"], booking_id=first["id"])
    cancelled = act(service, "cancel_booking", users["passenger"], booking_id=first["id"],
                    reason="Fixture cancellation")["booking"]
    assert cancelled["status"] == "cancelled"
    assert act(service, "accept", users["driver"], booking_id=second["id"])["booking"]["status"] == "accepted"
    state = act(service, "state", users["driver"])
    stored_trip = next(t for t in state["trips"] if t["id"] == trip["id"])
    assert max(segment["occupied"] for segment in stored_trip["inventory"]) == 1


def test_passenger_state_does_not_leak_another_drivers_route_or_geometry(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    origin = {"label": "Private Driver Origin", "lat": 16.760, "lon": 78.145}
    destination = {"label": "Private Driver Destination", "lat": 16.491, "lon": 77.950}
    _, private_trip = publish(service, users["driver2"], origin, destination, departure)

    response = act(service, "state", users["passenger"])
    serialized = repr(response)
    assert response["trips"] == []
    assert response["bookings"] == []
    assert origin["label"] not in serialized
    assert destination["label"] not in serialized
    assert private_trip["route"]["coordinates"] != []
    assert "coordinates" not in serialized


def test_repeat_passengers_count_distinct_trips_and_cancellations_require_acceptance(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    passenger = users["passenger"]

    # The same passenger completes bookings on two distinct trip ids.
    for day, driver in ((4, users["driver"]), (5, users["driver2"])):
        departure = future_departure(day)
        _, trip = publish(service, driver, KONDAPUR, VIJAYAWADA, departure)
        _, booking = booking_for(service, passenger, SURYAPET, NANDIGAMA, departure)
        act(service, "accept", driver, booking_id=booking["id"])
        act(service, "start_trip", driver, trip_id=trip["id"])
        act(service, "complete_segment", passenger, booking_id=booking["id"])
        act(service, "complete_trip", driver, trip_id=trip["id"])

    # Cancelling a pending booking as part of a trip cancellation is not a
    # cancellation of an accepted passenger reservation.
    pending_departure = future_departure(6)
    _, pending_trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, pending_departure)
    _, pending = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, pending_departure)
    act(service, "cancel_trip", users["driver"], trip_id=pending_trip["id"], reason="Fixture cancellation")
    with store.read() as tx:
        pending = tx.get("bookings", pending["id"])
    assert pending["status"] == "cancelled"
    assert "accepted_at" not in pending

    accepted_departure = future_departure(7)
    publish(service, users["driver2"], KONDAPUR, VIJAYAWADA, accepted_departure)
    _, accepted = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, accepted_departure)
    act(service, "accept", users["driver2"], booking_id=accepted["id"])
    act(service, "cancel_booking", users["passenger2"], booking_id=accepted["id"],
        reason="Fixture passenger cancellation")

    metrics = act(service, "operations", users["admin"])["metrics"]
    assert metrics["repeat_passengers"] == 1
    assert metrics["driver_cancellations"] == 0
    assert metrics["passenger_cancellations"] == 1
