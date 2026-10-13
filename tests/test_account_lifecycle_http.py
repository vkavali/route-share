"""Account lifecycle through real cookies/bearers, isolated SMS and SQLite."""
import secrets
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from test_phone_http import setup, signup, bearer, web_headers


def onboard(app, *, native=False, phone="9876543210"):
    client = app.test_client(use_cookies=not native)
    signed, _ = signup(client, native=native, phone=phone)
    headers = bearer(signed) if native else web_headers(signed.json["csrf_token"])
    response = client.post("/api/phone/profile", json={"name": "Lifecycle test member"}, headers=headers)
    assert response.status_code == 200, response.json
    return client, headers, signed.json["user"]["id"]


def reauth(client, headers, purpose):
    flow = secrets.token_urlsafe(32)
    response = client.post("/api/account/reauth/start", json={"purpose": purpose,
        "flow_token": flow, "request_id": str(uuid.uuid4())}, headers=headers)
    assert response.status_code == 200, response.json
    response = client.post("/api/account/reauth/verify", json={"challenge_id": response.json["challenge_id"],
        "flow_token": flow, "code": "831947"}, headers=headers)
    assert response.status_code == 200, response.json
    return response.json["action_token"]


@pytest.mark.parametrize("native", [False, True])
def test_customer_deletes_own_account_revokes_other_sessions_and_stops_streams(setup, native):
    app, provider, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    client, headers, uid = onboard(app, native=native)
    now[0] += 61
    second, second_headers, same_uid = onboard(app, native=not native)
    assert same_uid == uid
    state = client.get("/api/account/lifecycle", headers=headers)
    assert state.status_code == 200 and state.json["deletion_allowed"] is True
    assert state.headers["Cache-Control"] == "no-store"
    now[0] += 61
    action_token = reauth(client, headers, "delete")
    calls = []
    def after_commit(user_id):
        with app.extensions["beta_store"].read() as tx:
            assert tx.get("users", user_id)["account_status"] == "deleted"
        calls.append(user_id)
    app.extensions["voice_service"].cancel_owner = after_commit
    app.extensions["live_location_store"].stop_actor = after_commit
    response = client.post("/api/account/delete", json={"action_token": action_token,
        "confirm": True, "idempotency_key": str(uuid.uuid4())}, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["deleted"] is True and calls == [uid, uid]
    assert client.get("/api/state", headers=headers).status_code == 401
    assert second.get("/api/state", headers=second_headers).status_code == 401
    with app.extensions["beta_store"].read() as tx:
        record = tx.get("users", uid)
        assert not record.get("phone") and not record.get("auth_phone")
        assert all(s.get("user_id") != uid for s in tx.list("web_sessions") + tx.list("mobile_sessions"))


def test_web_logout_revokes_copied_cookie_and_native_recovery_rejects_browser_credentials(setup):
    app, provider, _, _ = setup
    client, headers, uid = onboard(app)
    old_cookie = client.get_cookie("session").value
    assert client.post("/api/logout", json={}, headers=headers).status_code == 200
    replay = app.test_client()
    replay.set_cookie("session", old_cookie)
    assert replay.get("/api/state").status_code == 401
    body = {"recovery_secret": secrets.token_urlsafe(32), "new_phone": "8765432109",
        "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    count = len(provider.sent)
    assert replay.post("/api/mobile/account/recovery/start", json=body).status_code == 403
    no_cookie = app.test_client(use_cookies=False)
    assert no_cookie.post("/api/mobile/account/recovery/start", json=body,
        headers={"Origin": "http://localhost"}).status_code == 403
    assert no_cookie.post("/api/account/recovery/start", json=body).status_code == 403
    assert len(provider.sent) == count


def test_reauth_is_bound_to_session_purpose_and_csrf(setup):
    app, _, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    client, headers, uid = onboard(app)
    now[0] += 61
    second, second_headers, _ = onboard(app, native=True)
    now[0] += 61
    proof = reauth(client, headers, "recovery_key")
    payload = {"action_token": proof, "recovery_secret": secrets.token_urlsafe(32), "saved": True}
    assert second.post("/api/account/recovery-key", json=payload, headers=second_headers).status_code in {400, 401, 403}
    assert client.post("/api/account/recovery-key", json=payload).status_code == 403
    deletion = client.post("/api/account/delete", json={"action_token": proof, "confirm": True,
        "idempotency_key": str(uuid.uuid4())}, headers=headers)
    assert deletion.status_code in {400, 401, 403}
    success = client.post("/api/account/recovery-key", json=payload, headers=headers)
    assert success.status_code == 200 and success.json["recovery_key_configured"] is True
    assert payload["recovery_secret"] not in success.get_data(as_text=True)
    assert client.post("/api/account/recovery-key", json=payload, headers=headers).status_code in {400, 401, 403}


@pytest.mark.parametrize("native", [False, True])
def test_lost_phone_recovery_preserves_identity_revokes_old_sessions_and_rotates_secret(setup, native):
    app, provider, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    old, old_headers, uid = onboard(app)
    now[0] += 61
    proof = reauth(old, old_headers, "recovery_key")
    secret = secrets.token_urlsafe(32)
    assert old.post("/api/account/recovery-key", json={"action_token": proof,
        "recovery_secret": secret, "saved": True}, headers=old_headers).status_code == 200
    new = app.test_client(use_cookies=not native)
    headers = {} if native else web_headers(new.get("/api/bootstrap").json["csrf_token"])
    prefix = "/api/mobile/account/recovery" if native else "/api/account/recovery"
    flow = secrets.token_urlsafe(32)
    start = new.post(prefix + "/start", json={"recovery_secret": secret, "new_phone": "8765432109",
        "flow_token": flow, "request_id": str(uuid.uuid4())}, headers=headers)
    assert start.status_code == 200, start.json
    replacement = secrets.token_urlsafe(32)
    verify = {"challenge_id": start.json["challenge_id"], "flow_token": flow, "code": "831947",
        "recovery_secret": secret, "new_recovery_secret": replacement, "saved": True}
    finished = new.post(prefix + "/verify", json=verify, headers=headers)
    assert finished.status_code == 200, finished.json
    assert finished.json["user"]["id"] == uid and finished.json["user"]["auth_epoch"] == 1
    assert finished.json["onboarding_required"] is False
    assert secret not in finished.get_data(as_text=True) and replacement not in finished.get_data(as_text=True)
    new_headers = bearer(finished) if native else web_headers(finished.json["csrf_token"])
    assert new.get("/api/state", headers=new_headers).status_code == 200
    assert old.get("/api/state", headers=old_headers).status_code == 401
    count = len(provider.sent)
    invalid = app.test_client(use_cookies=False)
    result = invalid.post("/api/mobile/account/recovery/start", json={"recovery_secret": secret,
        "new_phone": "7654321098", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())})
    assert result.status_code in {400, 409} and len(provider.sent) == count


def test_delete_rechecks_new_blocker_without_consuming_account(setup):
    app, _, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    client, headers, uid = onboard(app)
    now[0] += 61
    proof = reauth(client, headers, "delete")
    with app.extensions["beta_store"].transaction() as tx:
        tx.put("bookings", "http-blocker", {"id": "http-blocker", "driver_id": "driver",
            "passenger_id": uid, "trip_id": "fixture-trip", "status": "accepted"})
    response = client.post("/api/account/delete", json={"action_token": proof, "confirm": True,
        "idempotency_key": str(uuid.uuid4())}, headers=headers)
    assert response.status_code == 409, response.json
    assert response.json["code"] == "account_deletion_blocked"
    assert any(b.get("booking_id") == "http-blocker" for b in response.json["blockers"])
    assert client.get("/api/bootstrap").json["user"]["id"] == uid


def test_incomplete_profile_can_delete_but_demo_and_staff_cannot(setup):
    app, _, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    client = app.test_client()
    signed, _ = signup(client)
    headers = web_headers(signed.json["csrf_token"])
    assert client.get("/api/account/lifecycle").status_code == 200
    now[0] += 61
    proof = reauth(client, headers, "delete")
    assert client.post("/api/account/delete", json={"action_token": proof, "confirm": True,
        "idempotency_key": str(uuid.uuid4())}, headers=headers).status_code == 200
    staff = app.test_client(use_cookies=False)
    login = staff.post("/api/mobile/login", json={"account": "admin", "password": "http-fixture-password"})
    assert login.status_code == 200
    denied = staff.get("/api/account/lifecycle", headers=bearer(login))
    assert denied.status_code == 401 and denied.json["code"] == "account_unavailable"


@pytest.mark.parametrize("endpoint", ["start_sharing", "share_location", "stop_sharing", "live_location"])
def test_location_cannot_resume_after_epoch_changes_at_transaction_boundary(setup, monkeypatch, endpoint):
    app, _, _, _ = setup
    client, headers, uid = onboard(app)
    store = app.extensions["beta_store"]
    original = store.transaction
    @contextmanager
    def change_epoch_before_write():
        with original() as tx:
            user = tx.get("users", uid)
            user["auth_epoch"] = user.get("auth_epoch", 0) + 1
            tx.put("users", uid, user)
        with original() as tx:
            yield tx
    monkeypatch.setattr(store, "transaction", change_epoch_before_write)
    payload = {"booking_id": "fixture-booking", "sharing_id": "fixture-sharing",
               "lat": 17.44, "lon": 78.35, "accuracy": 10}
    response = client.get("/api/live_location?booking_id=fixture-booking", headers=headers) if endpoint == "live_location" else client.post("/api/" + endpoint, json=payload, headers=headers)
    assert response.status_code == 401 and response.json["code"] == "account_changed", response.json


def test_native_logout_does_not_wait_for_slow_reauth_sms_provider(setup, monkeypatch):
    app, provider, now, _ = setup
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    client, headers, _ = onboard(app, native=True)
    now[0] += 61
    entered, release = Event(), Event()
    original = provider.send
    def slow_send(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(provider, "send", slow_send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(lambda: app.test_client(use_cookies=False).post("/api/account/reauth/start",
            json={"purpose": "delete", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}, headers=headers))
        try:
            assert entered.wait(2)
            logged_out = pool.submit(lambda: client.post("/api/mobile/logout", json={}, headers=headers)).result(timeout=2)
            assert logged_out.status_code == 200
        finally:
            release.set()
        pending.result(timeout=3)
    assert client.get("/api/account/lifecycle", headers=headers).status_code == 401
