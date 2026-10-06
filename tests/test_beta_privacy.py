from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.community import CommunityService


@pytest.fixture
def community(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "beta-privacy-test-key",
        "BETA_PASSWORD": "test-only-password",
        "DATABASE_PATH": str(tmp_path / "beta-privacy.sqlite3"),
    })
    store = app.extensions["beta_store"]
    now = datetime.now(timezone.utc)
    origin = {"label": "Start", "lat": 17.0, "lon": 78.0}
    destination = {"label": "End", "lat": 17.2, "lon": 78.2}
    trip = {
        "id": "privacy-trip", "driver_id": "driver", "status": "started",
        "departure": (now - timedelta(minutes=5)).isoformat(), "max_detour_minutes": 0,
        "route": {"duration_s": 3600}, "current_route": {"duration_s": 3600},
    }
    booking = {
        "id": "privacy-booking", "trip_id": trip["id"], "status": "accepted",
        "driver_id": "driver", "passenger_id": "passenger",
        "match": {"dropoff_at": (now + timedelta(minutes=30)).isoformat()},
    }
    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver.update(
            phone="+919876543210", share_phone=False,
            identity_document="private document", approval_status="pending",
            sensitive_review_notes="private staff note",
        )
        tx.put("users", "driver", driver)
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)
    return store, CommunityService(store), booking, trip


def test_public_rating_average_waits_for_three_persisted_ratings_and_allowlists_fields(community):
    store, service, _booking, _trip = community
    with store.transaction() as tx:
        for index, stars in enumerate((5, 3, True), start=1):
            tx.put("ratings", f"rating-{index}", {
                "id": f"rating-{index}", "subject_id": "driver", "author_id": f"passenger-{index}",
                "stars": stars,
            })

    summary = service.public_summary("driver")
    assert summary["rating_count"] == 2
    assert summary["rating_average"] is None
    assert set(summary) == {
        "id", "name", "development", "verification", "rating_average", "rating_count", "completed_trip_count",
    }
    assert not {"phone", "share_phone", "identity_document", "approval_status", "sensitive_review_notes"} & set(summary)
    assert "+919876543210" not in str(summary)

    with store.transaction() as tx:
        tx.put("ratings", "rating-4", {
            "id": "rating-4", "subject_id": "driver", "author_id": "passenger-4", "stars": 4,
        })
    summary = service.public_summary("driver")
    assert summary["rating_count"] == 3
    assert summary["rating_average"] == 4


def test_contact_available_is_boolean_and_obeys_consent_active_status_and_blocks(community):
    store, service, booking, trip = community
    assert service.contact_available(booking, trip, "passenger") is False
    assert service.contact_available(booking, trip, "passenger2") is False

    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver["share_phone"] = True
        tx.put("users", "driver", driver)
    assert service.contact_available(booking, trip, "passenger") is True

    # The method re-reads authoritative records, not caller-provided snapshots.
    with store.transaction() as tx:
        current = tx.get("bookings", booking["id"])
        current["live_location_ended_reason"] = "arrival"
        tx.put("bookings", booking["id"], current)
    assert service.contact_available(booking, trip, "passenger") is False

    with store.transaction() as tx:
        current = tx.get("bookings", booking["id"])
        current.pop("live_location_ended_reason")
        tx.put("bookings", booking["id"], current)
        tx.put("blocks", "driver:passenger", {"id": "driver:passenger"})
    assert service.contact_available(booking, trip, "passenger") is False

    with store.transaction() as tx:
        tx.delete("blocks", "driver:passenger")
        current_trip = tx.get("trips", trip["id"])
        current_trip["status"] = "completed"
        tx.put("trips", trip["id"], current_trip)
    assert service.contact_available(booking, trip, "passenger") is False

    with store.transaction() as tx:
        current_trip = tx.get("trips", trip["id"])
        current_trip["status"] = "started"
        tx.put("trips", trip["id"], current_trip)
        current = tx.get("bookings", booking["id"])
        current["match"]["dropoff_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        tx.put("bookings", booking["id"], current)
    assert service.contact_available(booking, trip, "passenger") is False
