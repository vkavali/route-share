from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.location_policy import sharing_window


PASSWORD = "correct-horse-battery"
ORIGIN_HEADERS = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}


def scheduled_booking(*, boarded_at=None, ended_reason=None):
    pickup = datetime(2032, 5, 4, 12, tzinfo=timezone.utc)
    dropoff = pickup + timedelta(hours=2)
    booking = {
        "id": "booking",
        "driver_id": "driver",
        "passenger_id": "passenger",
        "status": "accepted",
        "match": {"pickup_at": pickup.isoformat(), "dropoff_at": dropoff.isoformat()},
    }
    if boarded_at:
        booking["boarded_at"] = boarded_at
    if ended_reason:
        booking["live_location_ended_reason"] = ended_reason
    trip = {"id": "trip", "status": "published", "departure": (pickup - timedelta(hours=1)).isoformat()}
    return booking, trip, pickup, dropoff


def test_driver_and_passenger_get_distinct_pickup_windows():
    booking, trip, pickup, _dropoff = scheduled_booking()
    driver_before = sharing_window(booking, trip, "driver", pickup - timedelta(minutes=30, seconds=1))
    driver_open = sharing_window(booking, trip, "driver", pickup - timedelta(minutes=30))
    passenger_before = sharing_window(booking, trip, "passenger", pickup - timedelta(minutes=15, seconds=1))
    passenger_open = sharing_window(booking, trip, "passenger", pickup - timedelta(minutes=15))

    assert driver_before["start_allowed"] is False
    assert driver_open["start_allowed"] is True
    assert passenger_before["start_allowed"] is False
    assert passenger_open["start_allowed"] is True
    assert driver_open["available_from"] != passenger_open["available_from"]
    assert driver_open["recipient_id"] == "passenger"
    assert passenger_open["recipient_id"] == "driver"


def test_started_trip_can_open_driver_window_early_without_opening_passenger_window():
    booking, trip, pickup, _dropoff = scheduled_booking()
    trip.update(status="started", started_at=(pickup - timedelta(hours=1)).isoformat())
    driver = sharing_window(booking, trip, "driver", pickup - timedelta(minutes=40))
    passenger = sharing_window(booking, trip, "passenger", pickup - timedelta(minutes=40))
    assert driver["start_allowed"] is True
    assert driver["available_from"] == trip["started_at"]
    assert passenger["start_allowed"] is False


def test_passenger_consent_phase_changes_after_boarding_and_terminal_or_expired_windows_close():
    booking, trip, pickup, dropoff = scheduled_booking()
    before = sharing_window(booking, trip, "passenger", pickup)
    booking["boarded_at"] = pickup.isoformat()
    onboard = sharing_window(booking, trip, "passenger", pickup)
    assert before["consent_phase"] == "pickup"
    assert onboard["consent_phase"] == "onboard"
    assert onboard["start_allowed"] is True
    assert onboard["hard_expires_at"] == (dropoff + timedelta(hours=2)).isoformat()

    at_hard_expiry = sharing_window(booking, trip, "passenger", dropoff + timedelta(hours=2))
    assert at_hard_expiry["expired"] is True and at_hard_expiry["start_allowed"] is False
    ended = sharing_window({**booking, "live_location_ended_reason": "arrival"}, trip, "driver", pickup)
    assert ended["start_allowed"] is False

    long_trip = {**trip, "departure": (pickup - timedelta(hours=30)).isoformat()}
    hard_cap = sharing_window(booking, long_trip, "driver", pickup + timedelta(hours=10))
    assert hard_cap["hard_expires_at"] == (datetime.fromisoformat(long_trip["departure"]) + timedelta(hours=24)).isoformat()


def _new_app(path):
    return create_app({"TESTING": True, "SECRET_KEY": "location-policy-test-key",
                       "DATABASE_PATH": str(path), "BETA_PASSWORD": PASSWORD})


def _login(client, account):
    bootstrap = client.get("/api/bootstrap").json
    result = client.post("/api/login", json={"account": account, "password": PASSWORD},
                         headers={**ORIGIN_HEADERS, "X-CSRF-Token": bootstrap["csrf_token"]})
    assert result.status_code == 200


def _post(client, action, **payload):
    csrf = client.get("/api/bootstrap").json["csrf_token"]
    return client.post(f"/api/{action}", json=payload,
                       headers={**ORIGIN_HEADERS, "X-CSRF-Token": csrf})


def _seed_live_booking(app):
    now = datetime.now(timezone.utc)
    pickup_at = now + timedelta(minutes=5)
    dropoff_at = now + timedelta(hours=2)
    pickup = {"label": "Pickup", "lat": 17.01, "lon": 78.01}
    dropoff = {"label": "Dropoff", "lat": 17.1, "lon": 78.1}
    trip = {
        "id": "trip-policy", "driver_id": "driver", "driver_name": "Development driver",
        "status": "published", "departure": now.isoformat(), "seats": 2, "version": 1,
        "origin": {"label": "Origin", "lat": 17, "lon": 78},
        "destination": {"label": "Destination", "lat": 17.2, "lon": 78.2},
        "route": {"provider": "fixture", "duration_s": 7200,
                  "coordinates": [[78, 17], [78.01, 17.01], [78.1, 17.1], [78.2, 17.2]]},
    }
    booking = {
        "id": "booking-policy", "trip_id": trip["id"], "driver_id": "driver", "passenger_id": "passenger",
        "driver_name": "Development driver", "passenger_name": "Development passenger", "status": "accepted",
        "seats": 1, "start_m": 1000, "end_m": 15000, "pickup": pickup, "dropoff": dropoff,
        "match": {"pickup": pickup, "dropoff": dropoff, "routed_pickup": pickup,
                  "routed_dropoff": dropoff, "pickup_at": pickup_at.isoformat(),
                  "dropoff_at": dropoff_at.isoformat()},
    }
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)
    return booking, trip, pickup_at, dropoff_at


def test_old_passenger_lease_is_revoked_at_boarding_and_new_consent_uses_onboard_phase(tmp_path):
    app = _new_app(tmp_path / "board.sqlite3")
    booking, _trip, _pickup_at, _dropoff_at = _seed_live_booking(app)
    driver, passenger = app.test_client(), app.test_client()
    _login(driver, "driver")
    _login(passenger, "passenger")

    started = _post(passenger, "start_sharing", booking_id=booking["id"])
    assert started.status_code == 200
    old_id = started.json["sharing_id"]
    sample = _post(passenger, "share_location", booking_id=booking["id"], sharing_id=old_id,
                   lat=17.02, lon=78.02, accuracy=20)
    assert sample.status_code == 200
    assert sample.json["expires_after_seconds"] == 120

    trip = driver.post("/api/start_trip", json={"trip_id": "trip-policy"},
                       headers={**ORIGIN_HEADERS, "X-CSRF-Token": driver.get("/api/bootstrap").json["csrf_token"]})
    assert trip.status_code == 200
    boarded = _post(passenger, "board_segment", booking_id=booking["id"])
    assert boarded.status_code == 200
    assert boarded.json["booking"]["boarded_by"] == "passenger"

    snapshot = passenger.get(f"/api/live_location?booking_id={booking['id']}")
    assert snapshot.status_code == 200
    assert snapshot.json["consent_phase"] == "onboard"
    assert snapshot.json["viewer_sharing"] is False
    assert snapshot.json["locations"] == []

    stale = _post(passenger, "share_location", booking_id=booking["id"], sharing_id=old_id,
                  lat=17.03, lon=78.03, accuracy=20)
    assert stale.status_code == 409 and stale.json["code"] == "sharing_expired"
    opted_in = _post(passenger, "start_sharing", booking_id=booking["id"])
    assert opted_in.status_code == 200
    assert opted_in.json["consent_phase"] == "onboard"
    assert opted_in.json["sharing_id"] != old_id

    with app.extensions["beta_store"].read() as tx:
        persisted = tx.get("bookings", booking["id"])
    assert persisted["boarded_by"] == "passenger" and persisted["boarded_at"]
    assert not any(key in persisted for key in ("lat", "lon", "locations"))


def test_permission_migration_revocations_survive_app_restart_and_mobile_user_has_access(tmp_path):
    path = tmp_path / "migration.sqlite3"
    config = {"TESTING": True, "SECRET_KEY": "migration-test-key", "DATABASE_PATH": str(path),
              "BETA_PASSWORD": PASSWORD}
    first = create_app(config)
    store = first.extensions["beta_store"]
    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver["driver_approved"] = False
        tx.put("users", "driver", driver)
        admin = tx.get("users", "admin")
        admin["staff_capabilities"] = ["verify.review"]
        tx.put("users", "admin", admin)
    restarted = create_app(config)
    with restarted.extensions["beta_store"].read() as tx:
        driver = tx.get("users", "driver")
        admin = tx.get("users", "admin")
    assert driver["permission_schema"] == admin["permission_schema"] == 1
    assert driver["driver_approved"] is False
    assert admin["staff_capabilities"] == ["verify.review"]

    native = restarted.test_client()
    mobile = native.post("/api/mobile/login", json={"account": "driver", "password": PASSWORD})
    assert mobile.status_code == 200
    assert mobile.json["user"]["access"]["can_drive"] is False
    assert mobile.json["user"]["access"]["is_staff"] is False


def test_member_and_staff_permissions_are_enforced_at_api_boundary(tmp_path):
    app = _new_app(tmp_path / "api-permissions.sqlite3")
    member, staff = app.test_client(), app.test_client()
    _login(member, "passenger")
    _login(staff, "admin")

    member_state = member.get("/api/state").json
    staff_state = staff.get("/api/state").json
    assert member_state["access"]["is_staff"] is False
    assert member_state["access"]["can_drive"] is False
    assert staff_state["access"]["is_staff"] is True
    assert staff_state["access"]["can_drive"] is False
    assert member.get("/api/operations").status_code == 403
    assert staff.get("/api/operations").status_code == 200

    response = staff.post("/api/start_trip", json={"trip_id": "missing"},
                          headers={**ORIGIN_HEADERS, "X-CSRF-Token": staff.get("/api/bootstrap").json["csrf_token"]})
    assert response.status_code == 403

    # Removing one explicit staff capability immediately revokes the route gate.
    with app.extensions["beta_store"].transaction() as tx:
        record = tx.get("users", "admin")
        record["staff_capabilities"] = ["verify.review"]
        tx.put("users", "admin", record)
    assert staff.get("/api/operations").status_code == 403
