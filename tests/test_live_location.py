from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app import live_location as live_location_module
from app.live_location import LiveLocationStore


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True, "SECRET_KEY": "live-location-test-key",
        "DATABASE_PATH": str(tmp_path / "beta.sqlite3"), "BETA_PASSWORD": "correct-horse-battery",
    })
    store = application.extensions["beta_store"]
    now = datetime.now(timezone.utc)
    pickup_at = now + timedelta(minutes=5)
    dropoff_at = now + timedelta(hours=2)
    pickup = {"label": "Pickup", "lat": 17.01, "lon": 78.01}
    dropoff = {"label": "Dropoff", "lat": 17.1, "lon": 78.1}
    trip = {
        "id": "trip-live", "driver_id": "driver", "status": "published",
        "version": 1, "origin": {"label": "Origin", "lat": 17, "lon": 78},
        "destination": {"label": "Destination", "lat": 17.2, "lon": 78.2}, "seats": 3,
        "departure": now.isoformat(),
        "route": {"provider": "fixture route", "coordinates": [[78.0, 17.0], [78.01, 17.01], [78.05, 17.05], [78.1, 17.1], [78.2, 17.2]]},
    }
    booking = {
        "id": "booking-live", "trip_id": "trip-live", "driver_id": "driver", "passenger_id": "passenger",
        "driver_name": "Development driver", "passenger_name": "Development passenger", "status": "accepted",
        "start_m": 1000, "end_m": 15000, "seats": 1,
        "pickup": pickup, "dropoff": dropoff, "match": {"routed_pickup": pickup, "routed_dropoff": dropoff,
                                                              "pickup_at": pickup_at.isoformat(),
                                                              "dropoff_at": dropoff_at.isoformat()},
    }
    with store.transaction() as tx:
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)
        tx.put("bookings", "booking-pending", {**booking, "id": "booking-pending", "status": "pending"})
        tx.put("trips", "trip-completed", {**trip, "id": "trip-completed", "status": "completed"})
        tx.put("bookings", "booking-completed", {**booking, "id": "booking-completed", "trip_id": "trip-completed"})
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def origin_headers():
    return {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}


def login(client, account):
    token = client.get("/api/bootstrap").json["csrf_token"]
    response = client.post("/api/login", json={"account": account, "password": "correct-horse-battery"},
                           headers={**origin_headers(), "X-CSRF-Token": token})
    assert response.status_code == 200


def post(client, path, payload):
    token = client.get("/api/bootstrap").json["csrf_token"]
    return client.post(path, json=payload, headers={**origin_headers(), "X-CSRF-Token": token})


def test_live_location_is_private_participant_only_and_returns_segment_route(app):
    driver, passenger, admin, outsider = (app.test_client() for _ in range(4))
    login(driver, "driver")
    login(passenger, "passenger")
    login(admin, "admin")
    login(outsider, "passenger2")

    initial = driver.get("/api/live_location?booking_id=booking-live")
    assert initial.status_code == 200
    assert initial.json["sharing_allowed"] is True
    assert initial.json["viewer_sharing"] is False
    assert initial.json["viewer_sharing_id"] is None
    assert initial.json["locations"] == []

    start = post(driver, "/api/start_sharing", {"booking_id": "booking-live"})
    assert start.status_code == 200
    sharing_id = start.json["sharing_id"]
    own_state = driver.get("/api/live_location?booking_id=booking-live")
    assert own_state.json["sharing_allowed"] is True
    assert own_state.json["viewer_sharing"] is True
    assert own_state.json["viewer_sharing_id"] == sharing_id
    update = post(driver, "/api/share_location", {
        "booking_id": "booking-live", "sharing_id": sharing_id,
        "lat": 17.02, "lon": 78.02, "accuracy": 20,
    })
    assert update.status_code == 200 and update.json["sharing_allowed"] is True

    state = passenger.get("/api/live_location?booking_id=booking-live")
    assert state.status_code == 200
    assert state.json["viewer_id"] == "passenger"
    assert state.json["sharing_allowed"] is True
    assert state.json["viewer_sharing"] is False
    assert state.json["viewer_sharing_id"] is None
    assert sharing_id not in str(state.json)
    assert state.json["locations"] == [{
        "user_id": "driver", "name": "Development driver", "lat": 17.02, "lon": 78.02,
        "accuracy": 20.0, "updated_at": state.json["locations"][0]["updated_at"],
    }]
    assert state.json["route"]["coordinates"] == [[78.01, 17.01], [78.05, 17.05], [78.1, 17.1]]
    assert state.json["route"]["provider"] == "fixture route"
    assert outsider.get("/api/live_location?booking_id=booking-live").status_code == 403
    assert admin.get("/api/live_location?booking_id=booking-live").status_code == 403

    # The durable booking document contains only lifecycle metadata, never GPS.
    with app.extensions["beta_store"].read() as tx:
        persisted = tx.get("bookings", "booking-live")
    assert "lat" not in persisted and "lon" not in persisted and "locations" not in persisted


def test_pending_or_terminal_booking_cannot_start_sharing(client):
    login(client, "driver")
    pending = post(client, "/api/start_sharing", {"booking_id": "booking-pending"})
    assert pending.status_code == 409
    completed = post(client, "/api/start_sharing", {"booking_id": "booking-completed"})
    assert completed.status_code == 409
    assert client.get("/api/live_location?booking_id=booking-pending").status_code == 409


def test_state_includes_only_participant_bounded_routes_for_eligible_bookings(app):
    driver, passenger, outsider = (app.test_client() for _ in range(3))
    login(driver, "driver")
    login(passenger, "passenger")
    login(outsider, "passenger2")

    driver_state = driver.get("/api/state").json
    rows = {booking["id"]: booking for booking in driver_state["bookings"]}
    assert rows["booking-live"]["route"]["coordinates"] == [
        [78.01, 17.01], [78.05, 17.05], [78.1, 17.1],
    ]
    assert rows["booking-live"]["route"]["provider"] == "fixture route"
    assert "route" not in rows["booking-pending"]
    # The completed journey remains readable to its participant, using only
    # that booking's segment from the persisted route.
    assert rows["booking-completed"]["route"]["coordinates"] == [
        [78.01, 17.01], [78.05, 17.05], [78.1, 17.1],
    ]

    passenger_rows = {booking["id"]: booking for booking in passenger.get("/api/state").json["bookings"]}
    assert passenger_rows["booking-live"]["route"] == rows["booking-live"]["route"]
    assert "booking-live" not in {booking["id"] for booking in outsider.get("/api/state").json["bookings"]}


def test_state_omits_route_when_committed_segment_is_missing(app):
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        trip = tx.get("trips", "trip-live")
        trip["route"] = None
        tx.put("trips", "trip-live", trip)

    client = app.test_client()
    login(client, "passenger")
    bookings = {booking["id"]: booking for booking in client.get("/api/state").json["bookings"]}
    assert "route" not in bookings["booking-live"]


def test_stop_revokes_old_token_and_ttl_removes_stale_samples(app):
    client = app.test_client()
    login(client, "driver")
    clock = [1000.0]
    app.extensions["live_location_store"].clock = lambda: clock[0]
    first = post(client, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    assert post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": first,
        "lat": 17.02, "lon": 78.02, "accuracy": 10}).status_code == 200
    # A reloaded client can recover only its own opaque stop token from the
    # authenticated snapshot, without creating a replacement lease.
    recovered = client.get("/api/live_location?booking_id=booking-live").json["viewer_sharing_id"]
    assert recovered == first
    assert post(client, "/api/stop_sharing", {"booking_id": "booking-live", "sharing_id": recovered}).status_code == 200
    late = post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": first,
        "lat": 17.03, "lon": 78.03, "accuracy": 10})
    assert late.status_code == 409 and late.json["code"] == "sharing_expired"

    second = post(client, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    assert second != first
    assert post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": second,
        "lat": 17.02, "lon": 78.02, "accuracy": 10}).status_code == 200
    clock[0] += 121
    passenger = app.test_client()
    login(passenger, "passenger")
    response = passenger.get("/api/live_location?booking_id=booking-live")
    assert response.status_code == 200
    assert response.json["locations"] == [] and response.json["sharing_allowed"] is True
    assert response.json["viewer_sharing"] is False


def test_arrival_revokes_both_participants_and_persists_only_arrival_reason(app):
    driver, passenger = app.test_client(), app.test_client()
    login(driver, "driver")
    login(passenger, "passenger")
    driver_id = post(driver, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    passenger_id = post(passenger, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    arrived = post(passenger, "/api/share_location", {
        "booking_id": "booking-live", "sharing_id": passenger_id,
        "lat": 17.1, "lon": 78.1, "accuracy": 50,
    })
    assert arrived.status_code == 200
    assert arrived.json == {"ok": True, "sharing_allowed": False, "stopped_reason": "arrival"}
    for participant in (driver, passenger):
        state = participant.get("/api/live_location?booking_id=booking-live")
        assert state.status_code == 200
        assert state.json["sharing_allowed"] is False
        assert state.json["viewer_sharing"] is False
        assert state.json["viewer_sharing_id"] is None
        assert state.json["stopped_reason"] == "arrival"
        assert state.json["locations"] == []
    restarted = post(driver, "/api/start_sharing", {"booking_id": "booking-live"})
    assert restarted.status_code == 409 and restarted.json["code"] == "arrival"
    late = post(driver, "/api/share_location", {"booking_id": "booking-live", "sharing_id": driver_id,
        "lat": 17.02, "lon": 78.02, "accuracy": 10})
    assert late.status_code == 200 and late.json["stopped_reason"] == "arrival"
    with app.extensions["beta_store"].read() as tx:
        booking = tx.get("bookings", "booking-live")
    assert booking["live_location_ended_reason"] == "arrival"
    assert "lat" not in booking and "lon" not in booking


def test_poor_accuracy_stops_only_current_lease_and_invalid_coordinates_fail_closed(client):
    login(client, "driver")
    sharing_id = post(client, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    poor = post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": sharing_id,
        "lat": 17.02, "lon": 78.02, "accuracy": 201})
    assert poor.status_code == 200 and poor.json["stopped_reason"] == "poor_accuracy"
    stale = post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": sharing_id,
        "lat": 17.02, "lon": 78.02, "accuracy": 20})
    assert stale.status_code == 409
    restarted = post(client, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    for coords in ((91, 78, 10), (17, 181, 10), (17, 78, -1)):
        invalid = post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": restarted,
            "lat": coords[0], "lon": coords[1], "accuracy": coords[2]})
        assert invalid.status_code == 400
    token = client.get("/api/bootstrap").json["csrf_token"]
    nonfinite = client.post("/api/share_location", data='{"booking_id":"booking-live","sharing_id":"' + restarted + '","lat":NaN,"lon":78,"accuracy":10}',
                            content_type="application/json", headers={**origin_headers(), "X-CSRF-Token": token})
    assert nonfinite.status_code == 400


def test_domain_actions_and_logout_purge_ephemeral_locations(app):
    client = app.test_client()
    login(client, "driver")
    store = app.extensions["live_location_store"]
    sharing_id = post(client, "/api/start_sharing", {"booking_id": "booking-live"}).json["sharing_id"]
    assert post(client, "/api/share_location", {"booking_id": "booking-live", "sharing_id": sharing_id,
        "lat": 17.02, "lon": 78.02, "accuracy": 20}).status_code == 200
    assert store._samples
    token = client.get("/api/bootstrap").json["csrf_token"]
    assert client.post("/api/logout", json={}, headers={**origin_headers(), "X-CSRF-Token": token}).status_code == 200
    assert store._samples == {}

    # Any domain dispatch triggers a lifecycle sweep; completed segments are terminal.
    login(client, "driver")
    post(client, "/api/start_sharing", {"booking_id": "booking-live"})
    with app.extensions["beta_store"].transaction() as tx:
        booking = tx.get("bookings", "booking-live")
        booking["status"] = "cancelled"
        tx.put("bookings", booking["id"], booking)
    assert post(client, "/api/cancel_trip", {"trip_id": "trip-live", "reason": "test end"}).status_code == 200
    assert store._samples == {}


def test_location_samples_expire_without_a_followup_request(monkeypatch):
    monkeypatch.setattr(live_location_module, "LOCATION_TTL_SECONDS", 0.05)
    store = LiveLocationStore()
    expired = threading.Event()
    sample_was_written = threading.Event()
    purge = store._purge_expired_locked

    def observe_purge(booking_id=None):
        purge(booking_id)
        if sample_was_written.is_set() and not store._samples.get("booking-timer"):
            expired.set()

    monkeypatch.setattr(store, "_purge_expired_locked", observe_purge)
    lease = store.start("booking-timer", "driver")
    store.update("booking-timer", "driver", lease["sharing_id"], lat=17.0, lon=78.0,
                 accuracy=10, updated_at="2030-01-01T00:00:00+00:00")
    sample_was_written.set()
    assert store._samples["booking-timer"]["driver"]["lat"] == 17.0

    assert expired.wait(timeout=1.0)
    assert store._samples == {}
    assert store._leases == {}
    assert store._expiry_timer is None


def test_renewing_a_sharing_lease_does_not_extend_an_old_location_sample(monkeypatch):
    monkeypatch.setattr(live_location_module, "LOCATION_TTL_SECONDS", 0.4)
    store = LiveLocationStore()
    expired_sample = threading.Event()
    sample_was_written = threading.Event()
    purge = store._purge_expired_locked

    def observe_purge(booking_id=None):
        purge(booking_id)
        if sample_was_written.is_set() and not store._samples.get("booking-renewal"):
            expired_sample.set()

    monkeypatch.setattr(store, "_purge_expired_locked", observe_purge)
    lease = store.start("booking-renewal", "driver")
    store.update("booking-renewal", "driver", lease["sharing_id"], lat=17.0, lon=78.0,
                 accuracy=10, updated_at="2030-01-01T00:00:00+00:00")
    sample_was_written.set()
    assert not expired_sample.wait(timeout=0.05)

    renewed = store.start("booking-renewal", "driver")
    assert renewed["sharing_id"] == lease["sharing_id"]
    assert expired_sample.wait(timeout=1.0)
    assert store._samples == {}
    # The explicit sharing lease can remain valid even though its old sample expired.
    assert "driver" in store._leases["booking-renewal"]
    assert store._expiry_timer is not None
