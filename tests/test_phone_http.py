"""Real Flask cookie/bearer boundaries; isolated provider, no network or SMS."""
import json
import secrets
import time
import uuid

import pytest

from datetime import datetime, timedelta, timezone

from app import create_app


class SMSFixture:
    ready = True

    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, phone, *, challenge_id, expires_in):
        self.sent.append((phone, challenge_id))
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        return "fixture-handle-" + challenge_id

    def verify(self, handle, code):
        return handle.startswith("fixture-handle-") and code == "831947"


@pytest.fixture
def setup(tmp_path):
    provider = SMSFixture()
    config = {"TESTING": True, "DATABASE_PATH": str(tmp_path / "phone-http.sqlite"),
              "SECRET_KEY": "http-fixture-signing-key-only", "BETA_PASSWORD": "http-fixture-password",
              "PHONE_AUTH_ENABLED": True, "PHONE_AUTH_PROVIDER": provider,
              "PUBLIC_OPERATOR_NAME": "Test operator", "PUBLIC_SUPPORT_EMAIL": "support@example.test",
              "PHONE_AUTH_HMAC_KEY": "h" * 48, "PHONE_AUTH_DAILY_LIMIT": 100,
              "DEMO_PASSWORD_ENABLED": False, "VOICE_ENABLED": False}
    app = create_app(config)
    now = [time.time()]
    app.extensions["phone_auth"].clock = lambda: now[0]
    return app, provider, now, config


def web_headers(token):
    return {"Origin": "http://localhost", "X-CSRF-Token": token, "Sec-Fetch-Site": "same-origin"}


def begin(client, *, native=False, phone="9876543210", csrf=None):
    if not native and csrf is None:
        csrf = client.get("/api/bootstrap").json["csrf_token"]
    payload = {"phone": phone, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    prefix = "/api/mobile/phone" if native else "/api/phone"
    response = client.post(prefix + "/start", json=payload, headers={} if native else web_headers(csrf))
    assert response.status_code == 200, response.json
    return response.json, payload, csrf


def proof(challenge, payload):
    return {"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"], "code": "831947",
            "consent": {"terms_version": "2026-10-11", "privacy_version": "2026-10-11",
                        "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}


def signup(client, *, native=False, phone="9876543210"):
    challenge, payload, csrf = begin(client, native=native, phone=phone)
    response = client.post("/api/mobile/phone/verify" if native else "/api/phone/verify",
                           json=proof(challenge, payload), headers={} if native else web_headers(csrf))
    assert response.status_code == 200, response.json
    return response, csrf


def bearer(response):
    return {"Authorization": "Bearer " + response.json["token"]}


def test_web_real_signup_profile_empty_account_and_signin_same_identity(setup, caplog):
    app, provider, now, config = setup
    client = app.test_client()
    response, old_csrf = signup(client)
    result = response.json
    user_id = result["user"]["id"]
    assert result["onboarding_required"] is True and result["user"]["phone_verified"] is True
    assert result["user"]["development"] is False and result["user"]["role"] == "member"
    assert result["user"]["driver_approved"] is False and result["user"]["access"]["can_drive"] is False
    assert result["csrf_token"] != old_csrf and "token" not in result
    assert "HttpOnly" in response.headers["Set-Cookie"] and "SameSite=Strict" in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "no-store"
    before = client.get("/api/bootstrap").json
    assert before["user"]["onboarding_required"] is True
    assert client.post("/api/phone/profile", json={"name": "New rider"}, headers=web_headers(old_csrf)).status_code == 403
    new_csrf = result["csrf_token"]
    completed = client.post("/api/phone/profile", json={"name": "New rider"}, headers=web_headers(new_csrf))
    assert completed.status_code == 200 and completed.json["onboarding_required"] is False
    state = client.get("/api/state")
    assert state.status_code == 200
    assert all(state.json[key] == [] for key in ("trips", "bookings", "requests", "ratings", "safety_reports", "blocks"))
    assert client.get("/api/operations").status_code == 403
    assert client.post("/api/preview", json={
        "origin": {"label": "Kondapur", "lat": 17.460, "lon": 78.357},
        "destination": {"label": "Vijayawada", "lat": 16.506, "lon": 80.648},
        "departure": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "seats": 2, "max_detour_minutes": 10,
    }, headers=web_headers(new_csrf)).status_code == 403
    assert client.post("/api/phone/start", json={}, headers=web_headers(new_csrf)).json["code"] == "sign_out_required"
    changed = client.post("/api/update_profile", json={"name": "New rider", "phone": "+918765432109", "share_phone": False}, headers=web_headers(new_csrf))
    assert changed.status_code == 400 and changed.json["code"] == "verified_phone_readonly"
    assert client.post("/api/logout", json={}, headers=web_headers(new_csrf)).status_code == 200
    assert client.get("/api/state").status_code == 401
    now[0] += 61
    response, _ = signup(client)
    assert response.json["user"]["id"] == user_id and response.json["onboarding_required"] is False
    assert len(provider.sent) == 2
    with app.extensions["beta_store"].read() as tx:
        saved = tx.get("users", user_id)
        assert saved["phone_consent"]["terms_accepted"] is True
        assert saved["phone_consent"]["privacy_accepted"] is True
        private = json.dumps(tx.list("phone_challenges") + tx.list("phone_send_requests"))
        assert "831947" not in private
    assert "831947" not in caplog.text and "9876543210" not in caplog.text
    # Restart preserves the real account and its signed web session.
    recreated = create_app(config)
    restored = recreated.test_client()
    restored.set_cookie("session", client.get_cookie("session").value)
    assert restored.get("/api/bootstrap").json["user"]["id"] == user_id


def test_native_signup_and_onboarding_gate_all_member_apis(setup):
    app, _, _, _ = setup
    client = app.test_client(use_cookies=False)
    response, _ = signup(client, native=True)
    headers = bearer(response)
    assert "Set-Cookie" not in response.headers and "csrf_token" not in response.json
    assert client.get("/api/bootstrap", headers=headers).json["csrf_token"] is None
    for path in ("/api/state", "/api/profile", "/api/reviews", "/api/payments", "/api/driver_application", "/api/places?q=Hyderabad"):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 403 and denied.json["code"] == "onboarding_required", (path, denied.json)
    for path in ("/api/search", "/api/driver_application", "/api/update_profile", "/api/report_safety"):
        denied = client.post(path, json={}, headers=headers)
        assert denied.status_code == 403 and denied.json["code"] == "onboarding_required"
    assert client.post("/api/phone/profile", json={"name": "Native rider"}, headers=headers).status_code == 200
    state = client.get("/api/state", headers=headers)
    assert state.status_code == 200 and state.json["bookings"] == []
    assert client.post("/api/mobile/phone/start", json={}, headers=headers).json["code"] == "sign_out_required"
    assert client.post("/api/mobile/logout", json={}, headers=headers).status_code == 200
    assert client.get("/api/state", headers=headers).status_code == 401


def test_web_origin_csrf_and_native_cookie_origin_guards(setup):
    app, provider, _, _ = setup
    browser = app.test_client()
    csrf = browser.get("/api/bootstrap").json["csrf_token"]
    payload = {"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    for headers in ({}, {"Origin": "http://localhost"},
                    {**web_headers(csrf), "Origin": "https://evil.example"},
                    {**web_headers(csrf), "Sec-Fetch-Site": "cross-site"}):
        assert browser.post("/api/phone/start", json=payload, headers=headers).status_code == 403
    assert browser.post("/api/mobile/phone/start", json=payload).status_code == 403
    native = app.test_client(use_cookies=False)
    for headers in ({"Origin": "http://localhost"}, {"Origin": "https://evil.example"}, {"Cookie": "session=forged"}):
        assert native.post("/api/mobile/phone/start", json=payload, headers=headers).status_code == 403
    assert provider.sent == []


@pytest.mark.parametrize("field", ["terms_accepted", "privacy_accepted", "adult_attested"])
@pytest.mark.parametrize("value", [False, "true", None])
def test_http_requires_explicit_consent(setup, field, value):
    app, _, _, _ = setup
    client = app.test_client(use_cookies=False)
    challenge, payload, _ = begin(client, native=True)
    body = proof(challenge, payload)
    body["consent"][field] = value
    response = client.post("/api/mobile/phone/verify", json=body)
    assert response.status_code == 400 and response.json["code"] == "consent_required"
    with app.extensions["beta_store"].read() as tx:
        assert len(tx.list("users")) == 4 and not tx.list("mobile_sessions")


@pytest.mark.parametrize("restriction", [{"account_status": "suspended"}, {"disabled": True}])
def test_both_session_transports_recheck_current_status(setup, restriction):
    app, _, _, _ = setup
    web, native = app.test_client(), app.test_client(use_cookies=False)
    web_response, _ = signup(web)
    native_response, _ = signup(native, native=True, phone="8765432109")
    web.post("/api/phone/profile", json={"name": "Web rider"}, headers=web_headers(web_response.json["csrf_token"]))
    native.post("/api/phone/profile", json={"name": "Native rider"}, headers=bearer(native_response))
    with app.extensions["beta_store"].transaction() as tx:
        for response in (web_response, native_response):
            user = tx.get("users", response.json["user"]["id"])
            user.update(restriction)
            tx.put("users", user["id"], user)
    assert web.get("/api/state").status_code == 401
    assert web.get("/api/bootstrap").json["user"] is None
    assert native.get("/api/state", headers=bearer(native_response)).status_code == 401


def test_no_account_enumeration_or_private_identity_in_api_projections(setup):
    app, _, now, _ = setup
    first = app.test_client(use_cookies=False)
    response, _ = signup(first, native=True)
    headers = bearer(response)
    first.post("/api/phone/profile", json={"name": "Private person"}, headers=headers)
    now[0] += 61
    unauth = app.test_client(use_cookies=False)
    old, _, _ = begin(unauth, native=True)
    fresh, _, _ = begin(unauth, native=True, phone="8765432109")
    assert set(old) == set(fresh) == {"challenge_id", "expires_at", "resend_at", "masked_phone"}
    for path in ("/api/bootstrap", "/api/state", "/api/profile"):
        body = json.dumps(first.get(path, headers=headers).json)
        assert all(marker not in body for marker in ("auth_phone", "phone_consent", "phone_identities", "flow_hash", "provider_handle"))
    staff = app.test_client(use_cookies=False)
    login = staff.post("/api/mobile/login", json={"account": "admin", "password": "http-fixture-password"})
    assert login.status_code == 200
    ops = staff.get("/api/operations", headers=bearer(login))
    assert ops.status_code == 200
    body = json.dumps(ops.json)
    assert "+919876543210" not in body and "phone_consent" not in body and "auth_phone" not in body
    denied = staff.post("/api/mobile/login", json={"account": "passenger", "password": "http-fixture-password"})
    assert denied.status_code == 401


@pytest.mark.parametrize("override", [{"PHONE_AUTH_PROVIDER": None}, {"PUBLIC_OPERATOR_NAME": ""},
    {"PUBLIC_SUPPORT_EMAIL": ""}, {"PHONE_AUTH_ENABLED": False}, {"PHONE_AUTH_DAILY_LIMIT": None},
    {"PHONE_AUTH_HMAC_KEY": "too-short"}, {"TESTING": False}])
def test_runtime_configuration_gate_never_falls_back_to_demo_otp(setup, override):
    _, provider, _, config = setup
    app = create_app({**config, **override})
    client = app.test_client(use_cookies=False)
    capabilities = client.get("/api/phone/capabilities")
    assert capabilities.status_code == 200 and capabilities.json["enabled"] is False
    assert client.get("/api/bootstrap").json["flags"]["public_registration_enabled"] is False
    failed = client.post("/api/mobile/phone/start", json={"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())})
    assert failed.status_code == 503 and failed.json["code"] == "phone_auth_unavailable"
    assert provider.sent == []


def test_policy_urls_escape_operator_and_delivery_errors_do_not_leak(setup, caplog):
    _, provider, _, config = setup
    app = create_app({**config, "PUBLIC_OPERATOR_NAME": "<script>alert('operator')</script>"})
    client = app.test_client(use_cookies=False)
    capabilities = client.get("/api/phone/capabilities").json
    for key in ("terms_url", "privacy_url"):
        response = client.get(capabilities[key])
        assert response.status_code == 200
        assert "<script>alert" not in response.text and "&lt;script&gt;" in response.text
        assert "support@example.test" in response.text
        assert "Version " + capabilities[key.replace("_url", "_version")] in response.text
    provider.fail = True
    failed = client.post("/api/mobile/phone/start", json={"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())})
    assert failed.status_code == 503
    assert "PRIVATE_PROVIDER_ERROR" not in failed.text + caplog.text
    assert "9876543210" not in failed.text + caplog.text
    assert "831947" not in failed.text + caplog.text


def test_wrong_code_bad_json_stale_account_and_privilege_injection(setup):
    app, _, _, _ = setup
    client = app.test_client(use_cookies=False)
    challenge, payload, _ = begin(client, native=True)
    body = proof(challenge, payload)
    body.update(role="staff", driver_approved=True, staff_capabilities=["staff.manage"], development=True)
    body["code"] = "000000"
    denied = client.post("/api/mobile/phone/verify", json=body)
    assert denied.status_code == 400 and denied.json["code"] == "phone_auth_invalid_code"
    assert "token" not in denied.json and "user" not in denied.json
    malformed = client.post("/api/mobile/phone/verify", json=[])
    assert malformed.status_code == 400
    body["code"] = "831947"
    accepted = client.post("/api/mobile/phone/verify", json=body)
    assert accepted.status_code == 200 and accepted.json["user"]["role"] == "member"
    assert accepted.json["user"]["access"]["staff_capabilities"] == []
    headers = {**bearer(accepted), "X-Expected-User-ID": "different-account"}
    stale = client.post("/api/phone/profile", json={"name": "Wrong tab"}, headers=headers)
    assert stale.status_code == 409 and stale.json["code"] == "account_changed"


def test_current_policy_reconsent_requires_new_signin_even_after_completed_profile(setup):
    app, _, _, _ = setup
    client = app.test_client(use_cookies=False)
    response, _ = signup(client, native=True)
    headers = bearer(response)
    assert client.post("/api/phone/profile", json={"name": "Reader"}, headers=headers).status_code == 200
    app.extensions["phone_auth"].terms_version = "next-policy"
    bootstrap = client.get("/api/bootstrap", headers=headers)
    assert bootstrap.status_code == 200 and bootstrap.json["user"]["onboarding_required"] is True
    assert client.get("/api/state", headers=headers).json["code"] == "onboarding_required"
    blocked = client.post("/api/phone/profile", json={"name": "Reader"}, headers=headers)
    assert blocked.status_code == 400 and blocked.json["code"] == "consent_required"
    assert client.post("/api/mobile/logout", json={}, headers=headers).status_code == 200


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("stale_field", ["terms_version", "privacy_version"])
def test_previous_policy_consent_cannot_create_session(setup, native, stale_field):
    app, _, _, _ = setup
    client = app.test_client()
    challenge, payload, csrf = begin(client, native=native)
    body = proof(challenge, payload)
    body["consent"][stale_field] = "2026-10-08"
    response = client.post("/api/mobile/phone/verify" if native else "/api/phone/verify",
                           json=body, headers={} if native else web_headers(csrf))
    assert response.status_code == 400 and response.json["code"] == "consent_required"
    assert "user" not in response.json and "token" not in response.json
    assert client.get("/api/bootstrap").json["user"] is None
