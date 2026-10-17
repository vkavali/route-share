"""A checked password cannot authorize a session after credentials change."""

import pytest
from werkzeug.security import generate_password_hash

from app import create_app


@pytest.mark.parametrize("change", ["password", "epoch", "disable"])
def test_web_login_rechecks_credentials_before_issuing_session(tmp_path, monkeypatch, change):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "isolated-login-race-signing-key",
        "DATABASE_PATH": str(tmp_path / "login-race.sqlite3"),
        "BETA_PASSWORD": "original-test-password", "VOICE_ENABLED": False,
    })
    store = app.extensions["beta_store"]
    authenticator = app.extensions["mobile_auth"]
    original_verify = authenticator.verify_credentials

    def verify_then_change(*args, **kwargs):
        checked = original_verify(*args, **kwargs)
        assert checked
        with store.transaction() as tx:
            current = tx.get("users", checked["id"])
            if change == "password":
                # Check the credential itself, even if another writer omitted
                # an epoch change. Normal credential rotation changes both.
                current["password_hash"] = generate_password_hash("replacement-test-password")
            elif change == "epoch":
                current["auth_epoch"] = current.get("auth_epoch", 0) + 1
            else:
                current["account_status"] = "disabled"
            tx.put("users", current["id"], current)
        return checked

    monkeypatch.setattr(authenticator, "verify_credentials", verify_then_change)
    client = app.test_client()
    csrf = client.get("/api/bootstrap").json["csrf_token"]
    result = client.post("/api/login", json={
        "account": "passenger", "password": "original-test-password",
    }, headers={"Origin": "http://localhost", "X-CSRF-Token": csrf})
    assert result.status_code == 401
    assert result.json["code"] == "account_changed"
    assert client.get("/api/bootstrap").json["user"] is None
    with store.read() as tx:
        assert tx.list("web_sessions") == []
