"""Real phone members cannot be paired with seeded development identities."""
from datetime import datetime, timedelta, timezone
import secrets
import uuid

import pytest

from app.domain import DomainError
from app.permissions import can_drive, can_request
from app.phone_auth import PhoneAuthService
from test_phone_auth import Provider
from test_lifecycle import (make_service, act, publish, search, booking_for,
                            KONDAPUR, VIJAYAWADA, SURYAPET, NANDIGAMA)


def synthetic_identity_review():
    """Persisted, bounded review fixture; the actual review HTTP path has separate tests."""
    reviewed = datetime.now(timezone.utc)
    return {"kind": "human_document_review", "source": "identity_application",
            "application_id": "synthetic-isolation-review", "reviewed_at": reviewed.isoformat(),
            "expires_at": (reviewed + timedelta(days=30)).isoformat()}


def phone_member(store):
    auth = PhoneAuthService(store, provider=Provider(), hmac_key="x" * 48, global_daily_limit=100)
    payload = {"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    challenge = auth.start(payload, "127.0.0.1")
    result = auth.verify({"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"],
        "code": "194628", "consent": {"terms_version": auth.terms_version, "privacy_version": auth.privacy_version,
        "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}, "127.0.0.1")
    profile = auth.profile(result["user"]["id"], {"name": "Actual phone member"})["user"]
    with store.transaction() as tx:
        user = tx.get("users", profile["id"])
        user["identity_approval"] = synthetic_identity_review()
        tx.put("users", user["id"], user)
    assert can_request(user)
    return user


def reviewed_real_driver(store, user_id):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    with store.transaction() as tx:
        user = tx.get("users", user_id)
        user.update(development=False, driver_approved=True,
                    auth_method="phone", auth_phone="+918765432109", phone_verified=True,
                    identity_approval=synthetic_identity_review(),
                    verification=dict.fromkeys(("identity", "dl", "rc", "insurance", "selfie"), "verified"),
                    driver_approval={"kind": "reviewed", "expires_at": future,
                                     "document_expiries": dict.fromkeys(("dl", "rc", "insurance"), future)})
        tx.put("users", user_id, user)
    return user


def test_new_phone_account_sees_no_fixture_and_cannot_request_injected_match(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA)
    actual = phone_member(store)
    found = search(service, actual, SURYAPET, NANDIGAMA, trip["departure"])
    assert found["matches"] == [] and found["request"]["evaluations"] == []
    assert found["request"]["development"] is False
    # Even an internally corrupted/stale match pointing into the opposite pool
    # cannot pass the transaction boundary. No client can mint such records.
    fixture_result = search(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])
    match = fixture_result["matches"][0]
    with store.transaction() as tx:
        request = tx.get("requests", match["request_id"])
        request["passenger_id"] = actual["id"]
        tx.put("requests", request["id"], request)
    with pytest.raises(DomainError) as denied:
        act(service, "request", actual, match_id=match["id"])
    assert denied.value.status == 409
    assert str(denied.value) == "This ride is no longer available."
    with store.read() as tx:
        assert tx.list("bookings") == []


def test_stale_pending_cannot_be_accepted_across_pools(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA)
    _, pending = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])
    with store.transaction() as tx:
        passenger = tx.get("users", "passenger")
        passenger.update(development=False, auth_method="phone", phone_verified=True,
                         auth_phone="+919876543210", identity_approval=synthetic_identity_review())
        assert can_request(passenger)
        tx.put("users", passenger["id"], passenger)
    with pytest.raises(DomainError) as denied:
        act(service, "accept", users["driver"], booking_id=pending["id"])
    assert denied.value.status == 409
    assert str(denied.value) == "This ride is no longer available."
    with store.read() as tx:
        assert tx.get("bookings", pending["id"])["status"] == "pending"


def test_two_real_members_can_publish_search_request_accept_without_fixture_labels(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver = reviewed_real_driver(store, "driver")
    actual = phone_member(store)
    _, trip = publish(service, driver, KONDAPUR, VIJAYAWADA)
    assert trip["development"] is False
    found, pending = booking_for(service, actual, SURYAPET, NANDIGAMA, trip["departure"])
    assert found["request"]["development"] is False and pending["development"] is False
    assert act(service, "accept", driver, booking_id=pending["id"])["booking"]["status"] == "accepted"
    report = act(service, "report_safety", actual, booking_id=pending["id"], category="other",
                 details="Synthetic regression safety report, not a real complaint.", idempotency_key="fixture-report-real-member")["report"]
    assert report["development"] is False
    assert act(service, "operations", users["admin"])["metrics"]["development_data_only"] is False
    with store.read() as tx:
        assert all(event["development"] is False for event in tx.list("events"))
    # The reverse direction is isolated too: a demo passenger cannot discover it.
    assert search(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])["matches"] == []


@pytest.mark.parametrize("restriction", [{"account_status": "suspended"}, {"disabled": True}])
def test_disabled_driver_not_available_to_other_members(tmp_path, restriction):
    service, store, users, _ = make_service(tmp_path)
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA)
    original = search(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])
    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver.update(restriction)
        tx.put("users", driver["id"], driver)
    assert can_drive(driver) is False
    assert search(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])["matches"] == []
    with pytest.raises(DomainError) as denied:
        act(service, "request", users["passenger"], match_id=original["matches"][0]["id"])
    assert denied.value.status == 409


def test_search_refilters_pool_after_slow_provider(tmp_path, monkeypatch):
    service, store, users, _ = make_service(tmp_path)
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA)
    route = service.router.route
    def change_pool(points):
        result = route(points)
        reviewed_real_driver(store, "driver")
        return result
    monkeypatch.setattr(service.router, "route", change_pool)
    assert search(service, users["passenger"], SURYAPET, NANDIGAMA, trip["departure"])["matches"] == []
