"""One joined Flask journey across real signup, reviews, booking, and restart.

OTP and road routing are synthetic fixtures. Windows replaces the bounded
preview renderer because its subprocess relies on Linux resource limits; Linux
runs exercise the actual preview renderer. No live SMS or payment provider is
called, and this test does not claim bank settlement.
"""
from datetime import datetime, timedelta, timezone
import os
import pytest
from cryptography.fernet import Fernet

from app import create_app
import app.driver_verification as driver_verification
import app.identity_verification as identity_verification
from test_account_flows_http import (
    PASSWORD,
    decision as driver_decision,
    get,
    phone_actor,
    png,
    post,
    upload as upload_driver_document,
)
from test_identity_http import save_application, upload as upload_identity_document
from test_identity_http import make_reviewer
from test_lifecycle import FixtureRoadProvider, KONDAPUR, VIJAYAWADA
from test_phone_http import SMSFixture


@pytest.fixture
def system(tmp_path):
    config = {
        "TESTING": True,
        "SECRET_KEY": "joined-release-http-session-only",
        "DATABASE_PATH": str(tmp_path / "joined-release.sqlite3"),
        "BETA_PASSWORD": PASSWORD,
        "PHONE_AUTH_ENABLED": True,
        "PHONE_AUTH_PROVIDER": SMSFixture(),
        "PHONE_AUTH_HMAC_KEY": "j" * 48,
        "PHONE_AUTH_DAILY_LIMIT": 100,
        "PUBLIC_OPERATOR_NAME": "Test operator",
        "PUBLIC_SUPPORT_EMAIL": "support@example.test",
        "IDENTITY_EVIDENCE_KEY": Fernet.generate_key(),
        "DIRECT_UPI_ENABLED": False,
        "VOICE_ENABLED": False,
    }
    app = create_app(config)
    app.extensions["beta_service"].router = FixtureRoadProvider()
    return app, config


def review_identity(app, member, reviewer, phone_id):
    client, headers = member
    application = save_application(client, headers)
    application = upload_identity_document(
        client, headers, kind="identity_document", version=application["version"]
    )
    application = upload_identity_document(
        client, headers, kind="selfie", version=application["version"]
    )
    submitted = post((client, headers), "submit_identity_application",
                     {"expected_version": application["version"]}).json["application"]
    for document in submitted["documents"]:
        downloaded = get((client, headers), "identity_document?document_id=" + document["id"])
        assert downloaded.data
    reviewer_client, reviewer_headers = reviewer
    for document in submitted["documents"]:
        opened = get((reviewer_client, reviewer_headers),
                     "identity_document_preview?document_id=" + document["id"])
        assert opened.json["image_data_url"].startswith("data:image/jpeg;base64,")
    progress = get((reviewer_client, reviewer_headers),
                   "identity_review_progress?application_id=" + submitted["id"]).json
    for step in progress["steps"]:
        progress = post((reviewer_client, reviewer_headers), "identity_review_progress", {
            "application_id": submitted["id"],
            "expected_version": submitted["version"],
            "expected_revision": progress["revision"],
            "step": step["key"],
            "checks": {key: True for key in step["checks"]},
        }).json
    assert progress["ready_for_approval"]
    approved = post((reviewer_client, reviewer_headers), "review_identity_application", {
        "application_id": submitted["id"],
        "expected_version": submitted["version"],
        "decision": "approved",
        "reason": "Reviewed synthetic fixture evidence.",
        "checks": {"document_readable": True, "name_matches": True,
                    "photo_matches": True, "adult_confirmed": True},
        "idempotency_key": "joined-identity-review-" + phone_id,
    }).json["application"]
    assert approved["status"] == "approved"
    with app.extensions["beta_store"].read() as tx:
        assert tx.get("users", phone_id)["identity_approval"]["kind"] == "human_document_review"

def review_driver(app, driver, reviewer):
    current = post(driver, "driver_application", {
        "legal_name": "Synthetic reviewed driver",
        "vehicle": {"model": "Fixture Car", "plate": "TS01AB1234"},
        "adult_attested": True,
        "planned_trip_attested": True,
        "document_consent": True,
        "applicant_note": "Synthetic review fixture",
        "expected_version": 0,
    }).json["application"]
    evidence = png(8192)
    for kind in ("dl", "rc", "insurance", "selfie"):
        current = upload_driver_document(driver, current, kind, evidence)
    submitted = post(driver, "submit_driver_application",
                     {"expected_version": current["version"]}).json["application"]
    reviewer_client, reviewer_headers = reviewer
    for document in submitted["documents"]:
        assert get(driver, "driver_document?document_id=" + document["id"]).data
        get((reviewer_client, reviewer_headers),
            "driver_document_preview?document_id=" + document["id"])
    progress = get((reviewer_client, reviewer_headers),
                   "driver_review_progress?application_id=" + submitted["id"]).json
    for step in progress["steps"]:
        progress = post((reviewer_client, reviewer_headers), "driver_review_progress", {
            "application_id": submitted["id"],
            "expected_version": submitted["version"],
            "expected_revision": progress["revision"],
            "step": step["key"],
            "checks": {key: True for key in step["checks"]},
        }).json
    assert progress["ready_for_approval"]
    approved = post((reviewer_client, reviewer_headers), "review_driver_application",
                    driver_decision(submitted)).json["application"]
    assert approved["status"] == "approved"
    assert get(driver, "bootstrap").json["user"]["access"]["can_drive"] is True


def test_joined_public_reviewed_trip_booking_cancellation_completion_and_restart(system, monkeypatch):
    app, config = system
    if os.name == "nt":
        # Keep the HTTP review/receipt path real; the isolated preview subprocess
        # needs Linux resource limits unavailable to the Windows Python runner.
        def fixture_preview(content, content_type, page, reviewer_id, at):
            import re
            import hashlib
            reviewer = re.sub(r"[^A-Za-z0-9_.-]", "_", str(reviewer_id))[:64]
            tag = hashlib.sha256(str(reviewer_id).encode()).hexdigest()[:8]
            return {
                "image_data_url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2w==",
                "page": int(page), "page_count": 1,
                "watermark": f"SeatPal PRIVATE REVIEW | {reviewer} ({tag}) | {at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            }
        monkeypatch.setattr(identity_verification, "render_preview", fixture_preview)
        monkeypatch.setattr(driver_verification, "render_preview", fixture_preview)
    driver, driver_id = phone_actor(app, "9876543210", "Reviewed driver")
    passenger, passenger_id = phone_actor(app, "8765432109", "Reviewed passenger")
    reviewer_client, reviewer_headers, _reviewer_id = make_reviewer(app, "7654321098")
    reviewer = (reviewer_client, reviewer_headers)

    review_identity(app, driver, reviewer, driver_id)
    review_identity(app, passenger, reviewer, passenger_id)
    review_driver(app, driver, reviewer)

    departure = (datetime.now(timezone.utc) + timedelta(minutes=8)).isoformat()
    preview = post(driver, "preview", {
        "origin": KONDAPUR,
        "destination": VIJAYAWADA,
        "departure": departure,
        "seats": 1,
        "max_detour_minutes": 15,
        "seat_price_paise": 60000,
        "baggage_capacity": {"small_bags": 2, "large_suitcases": 1},
    }).json["preview"]
    trip = post(driver, "publish", {"preview_id": preview["id"]}).json["trip"]
    start = datetime.fromisoformat(departure)
    search = post(passenger, "search", {
        "origin": KONDAPUR,
        "destination": VIJAYAWADA,
        "window_start": departure,
        "window_end": (start + timedelta(hours=8)).isoformat(),
        "seats": 1,
        "baggage": {"small_bags": 1, "large_suitcases": 1},
    }).json
    match = next(row for row in search["matches"] if row["trip_id"] == trip["id"])
    assert match["price_quote"]["amount_paise"] == 60000
    assert match["baggage_remaining"] == {"small_bags": 2, "large_suitcases": 1}

    first = post(passenger, "request", {"match_id": match["id"]}).json["booking"]
    assert first["price_quote"] == match["price_quote"]
    assert first["baggage"] == {"small_bags": 1, "large_suitcases": 1}
    accepted = post(driver, "accept", {"booking_id": first["id"]}).json["booking"]
    assert accepted["status"] == "accepted"
    assert accepted["price_quote"] == first["price_quote"]
    assert get(passenger, "bootstrap").json["flags"]["paid_rides_enabled"] is False
    payment = get(passenger, "payment?booking_id=" + first["id"]).json["payment"]
    assert payment["verification"] == "manual_only"
    assert payment["upi_uri"] is None

    current_trip = next(row for row in get(driver, "state").json["trips"] if row["id"] == trip["id"])
    assert max(segment["occupied"] for segment in current_trip["inventory"]) == 1
    cancelled = post(passenger, "cancel_booking", {
        "booking_id": first["id"], "reason": "Synthetic cancellation test",
    }).json["booking"]
    assert cancelled["status"] == "cancelled"
    assert post(passenger, "cancel_booking", {
        "booking_id": first["id"], "reason": "Synthetic cancellation test",
    }).json["booking"]["status"] == "cancelled"
    current_trip = next(row for row in get(driver, "state").json["trips"] if row["id"] == trip["id"])
    assert max(segment["occupied"] for segment in current_trip["inventory"]) == 0

    retry_search = post(passenger, "search", {
        "origin": KONDAPUR, "destination": VIJAYAWADA,
        "window_start": departure,
        "window_end": (start + timedelta(hours=8)).isoformat(), "seats": 1,
        "baggage": {"small_bags": 1, "large_suitcases": 1},
    }).json
    retry_match = next(row for row in retry_search["matches"] if row["trip_id"] == trip["id"])
    second = post(passenger, "request", {"match_id": retry_match["id"]}).json["booking"]
    assert second["id"] != first["id"]
    second = post(driver, "accept", {"booking_id": second["id"]}).json["booking"]
    assert second["status"] == "accepted"
    post(driver, "start_trip", {"trip_id": trip["id"]})
    completed = post(passenger, "complete_segment", {"booking_id": second["id"]}).json["booking"]
    assert completed["status"] == "segment_completed"
    post(driver, "complete_trip", {"trip_id": trip["id"]})

    restarted = create_app(config)
    restored = restarted.test_client()
    restored.set_cookie("session", driver[0].get_cookie("session").value)
    state = restored.get("/api/state")
    assert state.status_code == 200
    saved = next(row for row in state.json["bookings"] if row["id"] == second["id"])
    assert saved["status"] == "segment_completed"
    assert saved["price_quote"] == second["price_quote"]
    assert saved["baggage"] == second["baggage"]
