"""Isolated MSG91 Web SDK auth tests. No live provider calls or SMS."""
import hashlib
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from app import create_app
from app.sms_provider import MSG91WebSDKVerifier


class SDKFixture:
    ready = True

    def __init__(self):
        self.tokens = {}
        self.calls = []

    def public_config(self, phone):
        return {"widget_id": "fixture-widget", "token_auth": "public-fixture-token",
                "identifier": phone[1:]}

    def verify_access_token(self, token):
        self.calls.append(token)
        return self.tokens.get(token)


@pytest.fixture
def setup(tmp_path):
    provider = SDKFixture()
    config = {"TESTING": True, "DATABASE_PATH": str(tmp_path / "phone-sdk.sqlite"),
              "SECRET_KEY": "sdk-fixture-signing-key-only", "BETA_PASSWORD": "sdk-fixture-password",
              "PHONE_AUTH_ENABLED": True, "PHONE_AUTH_SDK_ENABLED": True,
              "PHONE_AUTH_SDK_PROVIDER": provider,
              "PUBLIC_OPERATOR_NAME": "Test operator", "PUBLIC_SUPPORT_EMAIL": "support@example.test",
              "PHONE_AUTH_HMAC_KEY": "s" * 48, "PHONE_AUTH_DAILY_LIMIT": 100,
              "DEMO_PASSWORD_ENABLED": False, "VOICE_ENABLED": False}
    app = create_app(config)
    now = [time.time()]
    app.extensions["phone_auth"].clock = lambda: now[0]
    return app, provider, now


def headers(client):
    return {"Origin": "http://localhost", "X-CSRF-Token": client.get("/api/bootstrap").json["csrf_token"],
            "Sec-Fetch-Site": "same-origin"}


def start(client, *, phone="9876543210", consent=None, request_id=None, flow=None):
    csrf = headers(client)
    flow = flow or secrets.token_urlsafe(32)
    body = {"phone": phone, "flow_token": flow, "request_id": request_id or str(uuid.uuid4()),
            "consent": ({"terms_version": "2026-10-11", "privacy_version": "2026-10-11",
                         "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}
                        if consent is None else consent)}
    response = client.post("/api/phone/sdk/start", json=body, headers=csrf)
    return response, body, csrf


def verify(client, challenge, start_body, token, csrf):
    return client.post("/api/phone/sdk/verify", json={"challenge_id": challenge["challenge_id"],
        "flow_token": start_body["flow_token"], "access_token": token}, headers=csrf)


def test_web_sdk_start_withholds_public_config_until_consent_and_start(setup):
    app, provider, _ = setup
    client = app.test_client()
    caps = client.get("/api/phone/capabilities").json
    assert caps["enabled"] is False  # native sign-in/recovery still require legacy REST
    assert caps["web_enabled"] is True and caps["recovery_enabled"] is False
    assert caps["mode"] == "msg91_web_sdk"
    assert "token_auth" not in caps and "widget_id" not in caps and "auth_key" not in caps
    denied, _, _ = start(client, consent={})
    assert denied.status_code == 400
    with app.extensions["beta_store"].read() as tx:
        assert tx.list("phone_challenges") == []
    response, body, _ = start(client)
    assert response.status_code == 200
    assert response.json["sdk"] == {"widget_id": "fixture-widget", "token_auth": "public-fixture-token",
                                    "identifier": "919876543210"}
    assert response.json["expires_at"] and response.json["resend_at"]
    assert provider.calls == []  # server reserves; only the Web SDK can send
    csp = response.headers["Content-Security-Policy"]
    assert "https://verify.msg91.com" in csp and "https://control.msg91.com" in csp
    assert "https://hcaptcha.com" in csp and "https://*.hcaptcha.com" in csp
    assert "style-src 'self' 'unsafe-inline' https://hcaptcha.com https://*.hcaptcha.com" in csp
    assert "unsafe-eval" not in csp and "https://*.msg91.com" not in csp


def test_sdk_verify_binds_provider_identifier_and_consumes_token_atomically(setup):
    app, provider, _ = setup
    client = app.test_client()
    challenge_response, body, csrf = start(client)
    token = "synthetic-sdk-access-token-1"
    provider.tokens[token] = "+919876543210"
    result = verify(client, challenge_response.json, body, token, csrf)
    assert result.status_code == 200, result.json
    user_id = result.json["user"]["id"]
    assert result.json["user"]["phone_verified"] is True
    assert result.json["user"]["development"] is False
    assert result.json["onboarding_required"] is True
    assert "token_auth" not in result.json and "auth_key" not in result.json
    with app.extensions["beta_store"].read() as tx:
        uses = tx.list("phone_sdk_token_uses")
        assert len(uses) == 1 and uses[0]["id"] == hashlib.sha256(token.encode()).hexdigest()
        challenge = tx.get("phone_challenges", challenge_response.json["challenge_id"])
        assert challenge["state"] == "consumed" and challenge.get("provider_handle") is None
        identity = tx.get("phone_identities", app.extensions["phone_auth"]._digest("phone", "+919876543210"))
        assert identity["user_id"] == user_id


def test_wrong_or_replayed_access_token_never_creates_another_account(setup):
    app, provider, _ = setup
    client = app.test_client()
    first, body, csrf = start(client)
    shared = "synthetic-replay-token"
    provider.tokens[shared] = "+919876543210"
    created = verify(client, first.json, body, shared, csrf)
    assert created.status_code == 200
    client.post("/api/logout", headers=headers(client))
    # The same browser request key must not resurrect a consumed challenge.
    with pytest.raises(Exception) as stale:
        app.extensions["phone_auth"].sdk_start(body, "127.0.0.1", csrf["X-CSRF-Token"])
    assert getattr(stale.value, "status", None) == 409
    _, _, now = setup
    now[0] += 61
    second, body2, csrf2 = start(client)
    assert second.status_code == 200
    replay = verify(client, second.json, body2, shared, csrf2)
    assert replay.status_code == 400
    wrong, wrong_body, wrong_csrf = start(client, phone="8765432109")
    provider.tokens["wrong-phone-token"] = "+919876543210"
    mismatch = verify(client, wrong.json, wrong_body, "wrong-phone-token", wrong_csrf)
    assert mismatch.status_code == 400
    with app.extensions["beta_store"].read() as tx:
        assert len([row for row in tx.list("users") if row.get("auth_method") == "phone"]) == 1
        assert len(tx.list("phone_sdk_token_uses")) == 1


def test_sdk_expiry_ip_flow_and_resend_rotation(setup):
    app, provider, now = setup
    client = app.test_client()
    first, body, csrf = start(client)
    start_before = first.json["challenge_id"]
    resend_id = str(uuid.uuid4())
    early = client.post("/api/phone/sdk/resend", json={"challenge_id": start_before,
        "flow_token": body["flow_token"], "request_id": resend_id}, headers=csrf)
    assert early.status_code == 429
    now[0] += 61
    rotated = client.post("/api/phone/sdk/resend", json={"challenge_id": start_before,
        "flow_token": body["flow_token"], "request_id": resend_id}, headers=csrf)
    assert rotated.status_code == 200 and rotated.json["challenge_id"] != start_before
    assert rotated.json["sdk"]["identifier"] == "919876543210"
    token = "synthetic-expired-token"
    provider.tokens[token] = "+919876543210"
    now[0] += 301
    expired = verify(client, rotated.json, body, token, csrf)
    assert expired.status_code == 410
    with app.extensions["beta_store"].read() as tx:
        assert tx.list("phone_identities") == [] and tx.list("phone_sdk_token_uses") == []


def test_sdk_gate_requires_explicit_contract_and_abuse_controls():
    base = dict(widget_id="id", token_auth="public-token", auth_key="server-key")
    assert not MSG91WebSDKVerifier(**base).ready
    assert not MSG91WebSDKVerifier(**base, contract_verified=True).ready
    assert not MSG91WebSDKVerifier(**base, abuse_controls_confirmed=True).ready
    assert MSG91WebSDKVerifier(**base, contract_verified=True, abuse_controls_confirmed=True).ready


def test_official_server_verifier_uses_api_host_auth_header_and_token_only_body():
    class Response:
        status = 200

        def read(self, _limit):
            return b'{"type":"success","message":"919876543210"}'

    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.msg91.com" and timeout == 10
            self.request_args = None

        def request(self, method, path, *, body, headers):
            self.request_args = (method, path, body, headers)

        def getresponse(self):
            assert self.request_args[0:2] == ("POST", "/api/v5/widget/verifyAccessToken")
            assert self.request_args[2] == b'{"access-token": "opaque-access-token"}'
            assert self.request_args[3]["authkey"] == "server-auth-fixture"
            return Response()

        def close(self):
            pass

    verifier = MSG91WebSDKVerifier(widget_id="widget", token_auth="public",
        auth_key="server-auth-fixture", contract_verified=True, abuse_controls_confirmed=True)
    with patch("app.sms_provider.http.client.HTTPSConnection", Connection):
        assert verifier.verify_access_token("opaque-access-token") == "+919876543210"


def test_sdk_challenge_is_bound_to_the_starting_browser_session(setup):
    app, provider, _ = setup
    first = app.test_client()
    challenge, body, _ = start(first)
    other = app.test_client()
    other_headers = headers(other)
    provider.tokens["browser-bound-token"] = "+919876543210"
    denied = verify(other, challenge.json, body, "browser-bound-token", other_headers)
    assert denied.status_code == 400
    assert first.post("/api/phone/sdk/verify", json={"challenge_id": challenge.json["challenge_id"],
        "flow_token": body["flow_token"], "access_token": "browser-bound-token"},
        headers=headers(first)).status_code == 200


def test_sdk_provider_failure_and_missing_operator_fail_closed(setup, tmp_path):
    app, provider, _ = setup
    client = app.test_client()
    challenge, body, csrf = start(client)
    provider.tokens["bad-id-token"] = "+918765432109"
    denied = verify(client, challenge.json, body, "bad-id-token", csrf)
    assert denied.status_code == 400
    caps = app.extensions["phone_auth"].capabilities()
    assert caps["enabled"] is False and caps["recovery_enabled"] is False
    assert caps["web_enabled"] is True

    no_operator = create_app({"TESTING": True, "DATABASE_PATH": str(tmp_path / "missing-operator.sqlite"),
        "SECRET_KEY": "sdk-missing-operator-fixture", "BETA_PASSWORD": "sdk-fixture-password",
        "PHONE_AUTH_ENABLED": True, "PHONE_AUTH_SDK_ENABLED": True,
        "PHONE_AUTH_SDK_PROVIDER": SDKFixture(), "PHONE_AUTH_HMAC_KEY": "s" * 48,
        "PHONE_AUTH_DAILY_LIMIT": 100, "DEMO_PASSWORD_ENABLED": False})
    caps = no_operator.extensions["phone_auth"].capabilities()
    assert caps["enabled"] is False and caps["web_enabled"] is False
    assert caps["recovery_enabled"] is False
    no_operator_client = no_operator.test_client()
    response = no_operator_client.post("/api/phone/sdk/start", json={}, headers=headers(no_operator_client))
    assert response.status_code == 503


def test_concurrent_sdk_verification_only_one_request_can_consume_challenge(setup):
    app, provider, _ = setup
    service = app.extensions["phone_auth"]
    flow = secrets.token_urlsafe(32)
    body = {"phone": "9876543210", "flow_token": flow, "request_id": str(uuid.uuid4()),
            "consent": {"terms_version": "2026-10-11", "privacy_version": "2026-10-11",
                        "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}
    session_binding = "browser-session-fixture-binding"
    challenge = service.sdk_start(body, "127.0.0.1", session_binding)
    token = "concurrent-sdk-token"
    provider.tokens[token] = "+919876543210"
    entered, release = threading.Event(), threading.Event()
    original = provider.verify_access_token

    def blocked(value):
        entered.set()
        assert release.wait(3)
        return original(value)

    provider.verify_access_token = blocked
    verify_body = {"challenge_id": challenge["challenge_id"], "flow_token": flow, "access_token": token}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.sdk_verify, verify_body, "127.0.0.1", session_binding)
        assert entered.wait(2)
        with pytest.raises(Exception) as exc:
            service.sdk_verify(verify_body, "127.0.0.1", session_binding)
        assert getattr(exc.value, "status", None) == 409
        release.set()
        result = pending.result(timeout=3)
    assert result["user"]["phone_verified"] is True
    with app.extensions["beta_store"].read() as tx:
        assert len(tx.list("phone_sdk_token_uses")) == 1
        assert len([row for row in tx.list("users") if row.get("auth_method") == "phone"]) == 1
