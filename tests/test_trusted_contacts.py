"""Security and lifecycle tests for trusted-contact journey snapshots."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from app import create_app
from app.trusted_contacts import TrustedContactError, TrustedContactService
from test_lifecycle import KONDAPUR, SURYAPET, act, booking_for, future_departure, make_service, publish


UTC = timezone.utc


@pytest.fixture
def active_booking(tmp_path):
    domain, store, users, _path = make_service(tmp_path)
    departure = future_departure(days=2)
    _preview, trip = publish(domain, users["driver"], KONDAPUR, SURYAPET, departure)
    _search, booking = booking_for(domain, users["passenger"], KONDAPUR, SURYAPET, departure)
    booking = act(domain, "accept", users["driver"], booking_id=booking["id"])["booking"]
    return domain, store, users, trip, booking


def test_link_is_one_time_bearer_with_minimal_snapshot_and_hashed_storage(active_booking):
    _domain, store, users, trip, booking = active_booking
    now = datetime.now(UTC)
    service = TrustedContactService(store, "test-signing-secret", now=lambda: now)

    created = service.create_snapshot_link(users["passenger"], {
        "booking_id": booking["id"], "alias": "Family",
    })
    assert created["token"]
    assert created["link_id"]
    assert created["expires_at"] <= (now + timedelta(hours=24)).isoformat()
    assert set(created["snapshot"]) == {
        "alias", "trip_date", "trip_status", "pickup", "dropoff", "driver_name",
        "vehicle_model", "vehicle_plate", "expires_at",
    }
    assert created["snapshot"]["alias"] == "Family"
    assert created["snapshot"]["pickup"] == booking["pickup"]["label"]
    assert created["snapshot"]["dropoff"] == booking["dropoff"]["label"]
    assert created["snapshot"]["driver_name"] == trip["driver_name"]
    assert "phone" not in created["snapshot"] and "route" not in created["snapshot"]
    assert {"lat", "lon", "coordinates", "route", "phone", "chat", "passengers"}.isdisjoint(
        created["snapshot"]
    )

    with store.read() as tx:
        saved = tx.get("trusted_contact_links", created["link_id"])
    assert "token" not in saved and created["token"] not in repr(saved)
    assert set(saved) == {
        "id", "token_hash", "version", "created_at", "expires_at", "booking_id", "actor_id",
    }
    assert service.read_snapshot(created["token"]) == created["snapshot"]
    # A forwarded bearer URL is intentionally usable without a contact account.
    assert service.read_snapshot(created["token"])["alias"] == "Family"


def test_only_booking_participants_can_create_or_revoke(active_booking):
    _domain, store, users, _trip, booking = active_booking
    service = TrustedContactService(store, "secret")
    with pytest.raises(TrustedContactError) as denied:
        service.create_snapshot_link(users["other"], {"booking_id": booking["id"]})
    assert denied.value.status == 403

    created = service.create_snapshot_link(users["driver"], {"booking_id": booking["id"]})
    with pytest.raises(TrustedContactError) as denied_revoke:
        service.revoke_link(users["other"], {"link_id": created["link_id"]})
    assert denied_revoke.value.status == 404
    assert service.revoke_link(users["driver"], {"link_id": created["link_id"]})["revoked"] is True
    with pytest.raises(TrustedContactError) as unavailable:
        service.read_snapshot(created["token"])
    assert unavailable.value.status == 410


def test_signed_token_expiry_and_tampering_fail_closed(active_booking):
    _domain, store, users, _trip, booking = active_booking
    current = [datetime.now(UTC)]
    service = TrustedContactService(store, "secret", now=lambda: current[0])
    created = service.create_snapshot_link(users["passenger"], {"booking_id": booking["id"]})

    with pytest.raises(TrustedContactError) as bad_token:
        service.read_snapshot(created["token"] + "x")
    assert bad_token.value.status == 410

    current[0] = datetime.fromisoformat(created["expires_at"]) + timedelta(seconds=1)
    with pytest.raises(TrustedContactError) as expired:
        service.read_snapshot(created["token"])
    assert expired.value.status == 410


def test_expiry_is_capped_at_agreed_dropoff_not_just_twenty_four_hours(active_booking):
    _domain, store, users, _trip, booking = active_booking
    now = datetime.now(UTC)
    agreed_end = now + timedelta(minutes=17, seconds=2)
    with store.transaction() as tx:
        saved = tx.get("bookings", booking["id"])
        saved["match"]["dropoff_at"] = agreed_end.isoformat()
        tx.put("bookings", saved["id"], saved)
    service = TrustedContactService(store, "secret", now=lambda: now)

    created = service.create_snapshot_link(users["passenger"], {"booking_id": booking["id"]})
    deadline = datetime.fromisoformat(created["expires_at"])
    assert deadline <= agreed_end
    assert deadline < now + timedelta(hours=24)
    assert service.read_snapshot(created["token"])["expires_at"] == created["expires_at"]


@pytest.mark.parametrize("change", ["booking_completed", "trip_completed", "blocked"])
def test_snapshot_is_revoked_by_current_booking_trip_or_block_state(active_booking, change):
    domain, store, users, trip, booking = active_booking
    service = TrustedContactService(store, "secret")
    created = service.create_snapshot_link(users["passenger"], {"booking_id": booking["id"]})
    with store.transaction() as tx:
        if change == "booking_completed":
            row = tx.get("bookings", booking["id"])
            row["status"] = "segment_completed"
            tx.put("bookings", row["id"], row)
        elif change == "trip_completed":
            row = tx.get("trips", trip["id"])
            row["status"] = "completed"
            tx.put("trips", row["id"], row)
        else:
            row = {"id": "passenger:driver", "blocker_id": "passenger", "blocked_id": "driver"}
            tx.put("blocks", row["id"], row)

    with pytest.raises(TrustedContactError) as unavailable:
        service.read_snapshot(created["token"])
    assert unavailable.value.status == 410


@pytest.mark.parametrize("trip_status,booking_status", [
    ("published", "pending"), ("completed", "accepted"), ("cancelled", "accepted"),
])
def test_cannot_create_for_pending_or_terminal_journey(active_booking, trip_status, booking_status):
    _domain, store, users, trip, booking = active_booking
    with store.transaction() as tx:
        b = tx.get("bookings", booking["id"])
        b["status"] = booking_status
        tx.put("bookings", b["id"], b)
        t = tx.get("trips", trip["id"])
        t["status"] = trip_status
        tx.put("trips", t["id"], t)

    service = TrustedContactService(store, "secret")
    with pytest.raises(TrustedContactError) as unavailable:
        service.create_snapshot_link(users["passenger"], {"booking_id": booking["id"]})
    assert unavailable.value.status == 410


def test_anonymous_viewer_uses_csrf_endpoint_and_revocation_takes_effect(tmp_path):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "viewer-api-test-secret",
        "DATABASE_PATH": str(tmp_path / "viewer-api.sqlite3"), "BETA_PASSWORD": "viewer-test-only",
    })
    store = app.extensions["beta_store"]
    departure = datetime.now(UTC) + timedelta(hours=2)
    dropoff = departure + timedelta(hours=2)
    trip = {
        "id": "shared-trip", "driver_id": "driver", "driver_name": "Test Driver",
        "driver_vehicle": {"model": "Test car", "plate": "TEST-123"},
        "departure": departure.isoformat(), "status": "published", "route": {"duration_s": 7200},
    }
    booking = {
        "id": "shared-booking", "trip_id": trip["id"], "driver_id": "driver", "passenger_id": "passenger",
        "status": "accepted", "pickup": {"label": "LB Nagar", "lat": 17.3, "lon": 78.5},
        "dropoff": {"label": "Suryapet", "lat": 17.1, "lon": 79.6},
        "match": {"dropoff_at": dropoff.isoformat()},
    }
    with store.transaction() as tx:
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)

    actor = app.test_client()
    actor_csrf = actor.get("/api/bootstrap").json["csrf_token"]
    login = actor.post("/api/login", json={"account": "passenger", "password": "viewer-test-only"}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": actor_csrf,
    })
    assert login.status_code == 200
    created = actor.post("/api/create_trip_link", json={"booking_id": booking["id"]}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": actor_csrf,
    })
    assert created.status_code == 200
    share_url = created.json["url"]
    assert "/trip-share#" in share_url and "token=" not in share_url
    token = urlsplit(share_url).fragment
    assert token and "token" not in created.json

    outsider = app.test_client()
    outsider_csrf = outsider.get("/api/bootstrap").json["csrf_token"]
    outsider_login = outsider.post("/api/login", json={"account": "passenger2", "password": "viewer-test-only"}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": outsider_csrf,
    })
    assert outsider_login.status_code == 200
    outsider_create = outsider.post("/api/create_trip_link", json={"booking_id": booking["id"]}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": outsider_csrf,
    })
    assert outsider_create.status_code == 403

    visitor = app.test_client()
    visitor_csrf = visitor.get("/api/bootstrap").json["csrf_token"]
    assert visitor.get("/api/bootstrap").json["user"] is None
    assert visitor.post("/api/shared_trip", json={"token": token}).status_code == 403
    viewed = visitor.post("/api/shared_trip", json={"token": token}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": visitor_csrf,
    })
    assert viewed.status_code == 200
    assert viewed.json["pickup"] == "LB Nagar" and "lat" not in viewed.json

    revoked = actor.post("/api/revoke_trip_link", json={"link_id": created.json["link_id"]}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": actor_csrf,
    })
    assert revoked.status_code == 200
    after_revoke = visitor.post("/api/shared_trip", json={"token": token}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": visitor_csrf,
    })
    assert after_revoke.status_code == 410
