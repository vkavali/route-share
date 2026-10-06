from __future__ import annotations

import json

import pytest
from werkzeug.security import check_password_hash

from app import ACCOUNT_NAMES, _persistent_secret, create_app


ORIGIN = "https://beta.example.test"
HOST = "beta.example.test"
PASSWORDS = {
    "driver": "Driver-Secure-Passphrase-2026-A",
    "passenger": "Passenger-Secure-Passphrase-2026-B",
    "passenger2": "Second-Passenger-Passphrase-2026-C",
    "admin": "Admin-Secure-Passphrase-2026-D",
}


def hosted_config(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "HOSTED_MODE": True,
        "PUBLIC_ORIGIN": ORIGIN,
        "BETA_ACCOUNT_PASSWORDS": PASSWORDS,
        "SECRET_KEY": "hosted-test-signing-key",
        "DATABASE_PATH": str(tmp_path / "hosted.sqlite3"),
    }
    config.update(overrides)
    return config


def https_env(ip="203.0.113.9"):
    return {"wsgi.url_scheme": "https", "REMOTE_ADDR": ip}


def hosted_headers(**extra):
    return {"Host": HOST, **extra}


def csrf(client):
    response = client.get("/api/bootstrap", headers=hosted_headers(), environ_overrides=https_env())
    assert response.status_code == 200
    return response.json["csrf_token"]


def test_hosted_startup_requires_canonical_origin_and_distinct_strong_passwords(tmp_path):
    with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
        create_app(hosted_config(tmp_path, PUBLIC_ORIGIN=None))
    with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
        create_app(hosted_config(tmp_path, PUBLIC_ORIGIN="https://beta.example.test/path"))
    with pytest.raises(ValueError, match="exactly"):
        create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS={"driver": "x" * 30}))
    weak = {**PASSWORDS, "admin": "short"}
    with pytest.raises(ValueError, match="24 characters"):
        create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS=weak))
    oversized = {**PASSWORDS, "admin": "x" * 1025}
    with pytest.raises(ValueError, match="1024 characters"):
        create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS=oversized))
    duplicate = {**PASSWORDS, "admin": PASSWORDS["driver"]}
    with pytest.raises(ValueError, match="distinct"):
        create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS=duplicate))
    local_default = {**PASSWORDS, "admin": "local-beta-only"}
    with pytest.raises(ValueError, match="local default"):
        create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS=local_default))


def test_hosted_environment_opt_in_reads_password_mapping_as_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_SHARE_HOSTED", "1")
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("BETA_ACCOUNT_PASSWORDS", json.dumps(PASSWORDS))
    app = create_app({"TESTING": True, "DATABASE_PATH": str(tmp_path / "environment.sqlite3"),
                      "SECRET_KEY": "hosted-env-test-key"})
    assert app.config["HOSTED_MODE"] is True
    assert app.test_client().get("/api/health", headers={"Host": HOST},
                                 environ_overrides={"wsgi.url_scheme": "http"}).json["mode"] == "hosted_beta"


def test_hosted_credentials_are_seeded_separately_and_local_default_is_rejected(tmp_path):
    app = create_app(hosted_config(tmp_path))
    store = app.extensions["beta_store"]
    with store.read() as tx:
        users = {row["id"]: row for row in tx.list("users")}
    assert set(users) == set(ACCOUNT_NAMES)
    assert all(row["development"] for row in users.values())
    assert all(check_password_hash(users[name]["password_hash"], password) for name, password in PASSWORDS.items())
    assert len({row["password_hash"] for row in users.values()}) == len(PASSWORDS)

    client = app.test_client()
    token = csrf(client)
    response = client.post("/api/login", json={"account": "driver", "password": "local-beta-only"},
                           headers=hosted_headers(Origin=ORIGIN, **{"X-CSRF-Token": token}),
                           environ_overrides=https_env())
    assert response.status_code == 401


def test_new_secret_file_is_private_and_existing_file_is_not_rewritten(tmp_path):
    path = tmp_path / "hosted-secret"
    secret = _persistent_secret(path)
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    assert _persistent_secret(path) == secret
    assert path.stat().st_mode & 0o777 == 0o644


def test_hosted_requires_https_exact_host_and_exact_same_origin(tmp_path):
    app = create_app(hosted_config(tmp_path))
    client = app.test_client()
    assert client.get("/api/bootstrap", headers=hosted_headers(), environ_overrides={"wsgi.url_scheme": "http"}).status_code == 400

    bad_host = client.get("/api/bootstrap", headers={"Host": "evil.example.test", "X-Forwarded-Host": HOST, "X-Forwarded-Proto": "https"})
    assert bad_host.status_code == 400

    token = csrf(client)
    cross_origin = client.post("/api/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                               headers=hosted_headers(Origin="https://evil.example.test", **{"X-CSRF-Token": token}),
                               environ_overrides=https_env())
    assert cross_origin.status_code == 403

    malformed_origin = client.post("/api/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                                   headers=hosted_headers(Origin=ORIGIN + "/path", **{"X-CSRF-Token": token}),
                                   environ_overrides=https_env())
    assert malformed_origin.status_code == 403

    good = client.post("/api/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                       headers=hosted_headers(Origin=ORIGIN, **{"X-CSRF-Token": token}),
                       environ_overrides=https_env())
    assert good.status_code == 200
    cookie = good.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "Expires=" in cookie
    assert app.permanent_session_lifetime.total_seconds() == 8 * 60 * 60
    assert good.headers["Strict-Transport-Security"].startswith("max-age=")
    assert client.get("/api/bootstrap", headers=hosted_headers(), environ_overrides=https_env()).json["mode"] == "hosted_beta"


def test_health_check_is_read_only_and_railway_host_exception_is_narrow(tmp_path):
    app = create_app(hosted_config(tmp_path))
    client = app.test_client()
    health = client.get("/api/health", headers={"Host": "healthcheck.railway.app"}, environ_overrides={"wsgi.url_scheme": "http"})
    assert health.status_code == 200
    assert health.json == {"status": "ok", "mode": "hosted_beta"}
    assert "users" not in health.json and "count" not in health.json

    assert client.get("/api/bootstrap", headers={"Host": "healthcheck.railway.app"}, environ_overrides=https_env()).status_code == 400
    assert client.post("/api/health", headers={"Host": "healthcheck.railway.app"}, environ_overrides=https_env()).status_code == 400
    assert client.get("/api/health", headers={"Host": "evil.example.test"}, environ_overrides=https_env()).status_code == 400
    configured_host_health = client.get("/api/health", headers=hosted_headers(), environ_overrides={"wsgi.url_scheme": "http"})
    assert configured_host_health.status_code == 200


def test_web_login_uses_shared_per_ip_rate_limit_across_accounts_and_mobile(tmp_path):
    app = create_app(hosted_config(tmp_path))
    client = app.test_client()
    token = csrf(client)
    headers = hosted_headers(Origin=ORIGIN, **{"X-CSRF-Token": token})
    ip = "198.51.100.42"
    for index in range(10):
        account = list(ACCOUNT_NAMES)[index % len(ACCOUNT_NAMES)]
        response = client.post("/api/login", json={"account": account, "password": "incorrect"},
                               headers=headers, environ_overrides=https_env(ip))
        assert response.status_code == 401
    limited_web = client.post("/api/login", json={"account": "driver", "password": "incorrect"},
                               headers=headers, environ_overrides=https_env(ip))
    assert limited_web.status_code == 429
    assert limited_web.json["code"] == "rate_limited"

    mobile = client.post("/api/mobile/login", json={"account": "passenger", "password": PASSWORDS["passenger"]},
                         headers=hosted_headers(), environ_overrides=https_env(ip))
    assert mobile.status_code == 429
