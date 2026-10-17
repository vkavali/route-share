"""Backup email routes through browser CSRF/cookies and native bearer sessions."""
import secrets
import time
import uuid

import pytest
from cryptography.fernet import Fernet

from app import create_app
from test_phone_http import SMSFixture, signup, web_headers, bearer
from test_backup_email import Mail
from test_account_lifecycle_http import reauth


@pytest.fixture
def email_http(tmp_path):
    mail = Mail()
    config = {"TESTING": True, "DATABASE_PATH": str(tmp_path / "email-http.sqlite"),
              "SECRET_KEY": "email-http-fixture-signing", "BETA_PASSWORD": "email-http-fixture-password",
              "PHONE_AUTH_ENABLED": True, "PHONE_AUTH_PROVIDER": SMSFixture(),
              "PUBLIC_OPERATOR_NAME": "Test operator", "PUBLIC_SUPPORT_EMAIL": "support@example.test",
              "PHONE_AUTH_HMAC_KEY": "h" * 48, "PHONE_AUTH_DAILY_LIMIT": 100,
              "BACKUP_EMAIL_ENABLED": True, "BACKUP_EMAIL_PROVIDER": mail,
              "BACKUP_EMAIL_ENCRYPTION_KEY": Fernet.generate_key(), "BACKUP_EMAIL_DAILY_LIMIT": 100,
              "DEMO_PASSWORD_ENABLED": False, "VOICE_ENABLED": False}
    app = create_app(config)
    now = [time.time()]
    for extension in ("phone_auth", "backup_email", "account_lifecycle"):
        app.extensions[extension].clock = lambda: now[0]
    return app, mail, now


def enroll_http(email_http, native=False):
    app, mail, now = email_http
    client = app.test_client(use_cookies=not native)
    signed, _ = signup(client, native=native)
    headers = bearer(signed) if native else web_headers(signed.json["csrf_token"])
    # Enrollment is intentionally allowed while ordinary profile onboarding is incomplete.
    now[0] += 61
    token = reauth(client, headers, "backup_email")
    payload = {"email": "Private@Example.com", "action_token": token,
               "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    result = client.post("/api/account/backup-email/start", json=payload, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json["masked_email"] == "p•••@example.com"
    pending = client.get("/api/account/lifecycle", headers=headers)
    assert not pending.json["backup_email"]["configured"]
    verified = client.post("/api/account/backup-email/verify", json={"challenge_id": result.json["challenge_id"],
        "flow_token": payload["flow_token"], "code": mail.sent[-1][1]}, headers=headers)
    assert verified.status_code == 200, verified.json
    return client, headers, signed.json["user"]["id"]


@pytest.mark.parametrize("native", [False, True])
def test_http_complete_recovery_logs_out_old_browser_or_device(email_http, native):
    app, mail, now = email_http
    old, old_headers, user_id = enroll_http(email_http, native)
    assert old.get("/api/phone/capabilities").json["backup_email_enabled"] is True
    blocked = old.post("/api/account/recovery/email/start", json={}, headers=old_headers)
    # Incomplete onboarding blocks public recovery before its signed-in guard.
    assert blocked.status_code in {403, 409}
    new = app.test_client(use_cookies=not native)
    headers = {} if native else web_headers(new.get("/api/bootstrap").json["csrf_token"])
    prefix = "/api/mobile/account/recovery" if native else "/api/account/recovery"
    now[0] += 61
    flow = secrets.token_urlsafe(32)
    sent = new.post(prefix + "/email/start", json={"email": "private@example.com", "flow_token": flow,
        "request_id": str(uuid.uuid4())}, headers=headers)
    assert sent.status_code == 200, sent.json
    assert set(sent.json) == {"challenge_id", "expires_at", "resend_at", "message"}
    proof = new.post(prefix + "/email/verify", json={"challenge_id": sent.json["challenge_id"], "flow_token": flow,
        "code": mail.sent[-1][1]}, headers=headers)
    assert proof.status_code == 200, proof.json
    assert "user" not in proof.json and "token" not in proof.json
    payload = {"recovery_token": proof.json["recovery_token"], "flow_token": flow,
               "new_phone": "8765432109", "request_id": str(uuid.uuid4())}
    phone = new.post(prefix + "/phone/start", json=payload, headers=headers)
    assert phone.status_code == 200, phone.json
    payload.update(challenge_id=phone.json["challenge_id"], code="831947")
    verified = new.post(prefix + "/phone/verify", json=payload, headers=headers)
    assert verified.status_code == 200, verified.json
    assert verified.json["user"]["id"] == user_id and verified.json["user"]["phone"] == "+918765432109"
    assert "token" in verified.json if native else "csrf_token" in verified.json
    assert verified.headers["Cache-Control"] == "no-store"
    assert old.get("/api/account/lifecycle", headers=old_headers).status_code == 401
    new_headers = bearer(verified) if native else web_headers(verified.json["csrf_token"])
    own_status = new.get("/api/account/lifecycle", headers=new_headers)
    assert own_status.status_code == 200 and own_status.json["backup_email"]["configured"]
    assert "private@example.com" not in str(own_status.json)
    bootstrap = new.get("/api/bootstrap", headers=new_headers).json
    assert "private@example.com" not in str(bootstrap) and "address_key" not in str(bootstrap)


def test_http_csrf_and_mobile_cookie_origin_boundaries(email_http):
    app, mail, _ = email_http
    client = app.test_client()
    body = {"email": "unknown@example.com", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    assert client.post("/api/account/recovery/email/start", json=body).status_code == 403
    assert client.post("/api/mobile/account/recovery/email/start", json=body, headers={"Origin": "https://evil.test"}).status_code == 403
    client.get("/api/bootstrap")
    assert client.post("/api/mobile/account/recovery/email/start", json=body).status_code == 403
    assert not mail.sent
    for action in ("start", "verify", "remove"):
        assert client.post("/api/account/backup-email/" + action, json={}, headers=web_headers(client.get("/api/bootstrap").json["csrf_token"])).status_code == 401


def test_http_remove_requires_fresh_phone_proof(email_http):
    client, headers, _ = enroll_http(email_http)
    assert client.post("/api/account/backup-email/remove", json={}, headers=headers).status_code == 400
    email_http[2][0] += 61
    proof = reauth(client, headers, "backup_email")
    removed = client.post("/api/account/backup-email/remove", json={"action_token": proof}, headers=headers)
    assert removed.status_code == 200 and not removed.json["backup_email"]["configured"]
    assert client.post("/api/account/backup-email/remove", json={"action_token": proof}, headers=headers).status_code == 400
