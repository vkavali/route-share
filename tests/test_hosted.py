from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app import ACCOUNT_NAMES, _persistent_secret, create_app
from app.mobile_auth import MobileAuthError, MobileAuthenticator
from app.store import Store


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


@pytest.mark.parametrize("aliases", [None, [], " ", ",", "https://seatpal.example.test,",
    "https://seatpal.example.test,,https://www.example.test", "http://seatpal.example.test",
    "https://*.example.test", "https://seatpal.example.test/", "https://seatpal.example.test/path",
    "https://seatpal.example.test?x=1", "https://seatpal.example.test#fragment",
    "https://user@seatpal.example.test", "https://seatpal.example.test:443",
    "https://SeatPal.example.test", "https://bad host.test", "https://bad..test",
    "https://bad%2ehost.test", "https://bad\\host.test", "https://bad\nhost.test"])
def test_hosted_rejects_invalid_origin_alias_configuration(tmp_path, aliases):
    with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
        create_app(hosted_config(tmp_path, PUBLIC_ORIGIN_ALIASES=aliases))


def test_hosted_alias_environment_and_exact_host_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN_ALIASES", "https://seatpal.example.test, https://www.seatpal.example.test")
    app = create_app(hosted_config(tmp_path))
    client = app.test_client()
    for host in (HOST, "seatpal.example.test", "www.seatpal.example.test"):
        assert client.get("/welcome", base_url=f"https://{host}").status_code == 200
        assert client.get("/welcome", base_url=f"http://{host}").status_code == 400
    for host in ("unknown.example.test", "seatpal.example.test.evil.test", "seatpal.example.test:444"):
        assert client.get("/api/bootstrap", base_url=f"https://{host}",
                          headers={"X-Forwarded-Host": "seatpal.example.test"}).status_code == 400
    assert client.get("/api/health", base_url="http://healthcheck.railway.app").status_code == 200
    assert client.get("/api/bootstrap", base_url="https://healthcheck.railway.app").status_code == 400


@pytest.mark.parametrize("host", [HOST, "seatpal.example.test", "www.seatpal.example.test"])
def test_hosted_each_alias_requires_its_own_origin_and_csrf(tmp_path, host):
    app = create_app(hosted_config(tmp_path,
        PUBLIC_ORIGIN_ALIASES="https://seatpal.example.test,https://www.seatpal.example.test"))
    client = app.test_client()
    origin = f"https://{host}"
    token = client.get("/api/bootstrap", base_url=origin).json["csrf_token"]
    payload = {"account": "driver", "password": PASSWORDS["driver"]}
    other_origin = ORIGIN if host != HOST else "https://seatpal.example.test"
    cross = client.post("/api/login", base_url=origin, json=payload,
                        headers={"Origin": other_origin, "X-CSRF-Token": token})
    assert cross.status_code == 403
    missing = client.post("/api/login", base_url=origin, json=payload, headers={"Origin": origin})
    assert missing.status_code == 403
    spoof = client.post("/api/login", base_url=origin, json=payload,
                        headers={"Origin": other_origin, "X-Forwarded-Host": other_origin[8:],
                                 "X-CSRF-Token": token})
    assert spoof.status_code == 403
    good = client.post("/api/login", base_url=origin, json=payload,
                       headers={"Origin": origin, "X-CSRF-Token": token, "Sec-Fetch-Site": "same-origin"})
    assert good.status_code == 200
    cookie = good.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "Domain=" not in cookie
    assert client.get("/api/bootstrap", base_url=other_origin).json["user"] is None


def test_original_native_origin_remains_usable_as_alias(tmp_path):
    app = create_app(hosted_config(tmp_path, PUBLIC_ORIGIN="https://seatpal.example.test",
                                   PUBLIC_ORIGIN_ALIASES=ORIGIN))
    client = app.test_client()
    response = client.post("/api/mobile/login", base_url=ORIGIN,
                           json={"account": "passenger", "password": PASSWORDS["passenger"]})
    assert response.status_code == 200 and "Set-Cookie" not in response.headers
    headers = {"Authorization": "Bearer " + response.json["token"]}
    assert client.get("/api/bootstrap", base_url=ORIGIN, headers=headers).json["user"]["id"] == "passenger"
    assert client.post("/api/mobile/logout", base_url=ORIGIN, headers=headers, json={}).status_code == 200


def test_alias_request_keeps_canonical_trip_share_origin(tmp_path, monkeypatch):
    app = create_app(hosted_config(tmp_path, PUBLIC_ORIGIN_ALIASES="https://seatpal.example.test"))
    client = app.test_client()
    alias = "https://seatpal.example.test"
    csrf_token = client.get("/api/bootstrap", base_url=alias).json["csrf_token"]
    login = client.post("/api/login", base_url=alias,
                        json={"account": "driver", "password": PASSWORDS["driver"]},
                        headers={"Origin": alias, "X-CSRF-Token": csrf_token})
    assert login.status_code == 200
    csrf_token = client.get("/api/bootstrap", base_url=alias).json["csrf_token"]
    # Isolate HTTP URL construction, not the already-covered trusted-trip service.
    monkeypatch.setattr(app.extensions["trusted_contact_service"], "create_snapshot_link",
                        lambda user, body: {"token": "synthetic-fragment-only"})
    response = client.post("/api/create_trip_link", base_url=alias, json={},
                           headers={"Origin": alias, "X-CSRF-Token": csrf_token})
    assert response.status_code == 200
    assert response.json["url"] == ORIGIN + "/trip-share#synthetic-fragment-only"


def test_unchanged_seed_password_preserves_hash_and_existing_sessions_after_restart(tmp_path):
    config = hosted_config(tmp_path)
    first = create_app(config)
    web = first.test_client()
    token = csrf(web)
    signed_in = web.post("/api/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                         headers=hosted_headers(Origin=ORIGIN, **{"X-CSRF-Token": token}),
                         environ_overrides=https_env())
    assert signed_in.status_code == 200
    web_cookie = web.get_cookie("session", domain=HOST)
    native = web.post("/api/mobile/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                      headers=hosted_headers(), environ_overrides=https_env())
    assert native.status_code == 200
    with first.extensions["beta_store"].read() as tx:
        original = tx.get("users", "driver")
    restarted = create_app(config)
    with restarted.extensions["beta_store"].read() as tx:
        after = tx.get("users", "driver")
    assert after["password_hash"] == original["password_hash"]
    assert after.get("auth_epoch", 0) == original.get("auth_epoch", 0)

    restored_web = restarted.test_client()
    restored_web.set_cookie("session", web_cookie.value, domain=HOST)
    assert restored_web.get("/api/state", headers=hosted_headers(), environ_overrides=https_env()).status_code == 200
    assert restarted.test_client().get("/api/state", headers=hosted_headers(Authorization=f"Bearer {native.json['token']}"),
                                      environ_overrides=https_env()).status_code == 200


def test_password_rotation_invalidates_old_web_and_mobile_sessions(tmp_path):
    config = hosted_config(tmp_path)
    first = create_app(config)
    web = first.test_client()
    token = csrf(web)
    signed_in = web.post("/api/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                         headers=hosted_headers(Origin=ORIGIN, **{"X-CSRF-Token": token}),
                         environ_overrides=https_env())
    assert signed_in.status_code == 200
    web_cookie = web.get_cookie("session", domain=HOST)
    native = web.post("/api/mobile/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                      headers=hosted_headers(), environ_overrides=https_env())
    assert native.status_code == 200
    with first.extensions["beta_store"].read() as tx:
        original_epoch = tx.get("users", "driver").get("auth_epoch", 0)

    rotated = {**PASSWORDS, "driver": "Driver-Rotated-Secure-Passphrase-2026-Z"}
    second = create_app(hosted_config(tmp_path, BETA_ACCOUNT_PASSWORDS=rotated))
    with second.extensions["beta_store"].read() as tx:
        current = tx.get("users", "driver")
        assert current["auth_epoch"] == original_epoch + 1
        assert not any(row.get("user_id") == "driver" for row in tx.list("web_sessions") + tx.list("mobile_sessions"))
    stale_web = second.test_client()
    stale_web.set_cookie("session", web_cookie.value, domain=HOST)
    assert stale_web.get("/api/state", headers=hosted_headers(), environ_overrides=https_env()).status_code == 401
    stale_mobile = second.test_client()
    assert stale_mobile.get("/api/state", headers=hosted_headers(Authorization=f"Bearer {native.json['token']}"),
                            environ_overrides=https_env()).status_code == 401
    assert check_password_hash(current["password_hash"], rotated["driver"])


def test_password_rate_limit_is_persistent_hmac_scoped_across_instances_and_restart(tmp_path):
    config = hosted_config(tmp_path)
    first = create_app(config)
    second = create_app(config)
    ip = "198.51.100.77"
    auths = [first.extensions["mobile_auth"], second.extensions["mobile_auth"]]

    def attempt(index):
        try:
            auths[index % 2].verify_credentials(list(ACCOUNT_NAMES)[index % len(ACCOUNT_NAMES)], "incorrect", ip)
            return "checked"
        except Exception as exc:
            if getattr(exc, "status", None) == 429:
                return "limited"
            raise

    outcomes = [attempt(index) for index in range(20)]
    assert outcomes.count("checked") == 10
    assert outcomes.count("limited") == 10

    restarted = create_app(config)
    client = restarted.test_client()
    response = client.post("/api/mobile/login", json={"account": "driver", "password": PASSWORDS["driver"]},
                           headers=hosted_headers(), environ_overrides=https_env(ip))
    assert response.status_code == 429
    with restarted.extensions["beta_store"].read() as tx:
        limiter_rows = tx.list("password_login_attempts")
    assert limiter_rows
    assert ip not in json.dumps(limiter_rows)
    assert all(row["id"] != ip and not any(account in json.dumps(row) for account in ACCOUNT_NAMES) for row in limiter_rows)


def test_password_rate_limiter_is_atomic_across_concurrent_authenticator_instances(tmp_path):
    database = tmp_path / "concurrent-limiter.sqlite3"
    store = Store(database)
    now = [1_800_000_000.0]
    key = "shared-rate-limit-test-key"
    auths = [
        MobileAuthenticator(store, clock=lambda: now[0], rate_limit_key=key),
        MobileAuthenticator(store, clock=lambda: now[0], rate_limit_key=key),
    ]
    workers = 12
    ip = "198.51.100.77"

    def attempt(index):
        try:
            auths[index % 2]._rate_limit(ip)
            return "allowed"
        except MobileAuthError as exc:
            if exc.status == 429:
                return "limited"
            raise

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(attempt, range(20)))
    assert outcomes.count("allowed") == 10
    assert outcomes.count("limited") == 10

    third = MobileAuthenticator(Store(database), clock=lambda: now[0], rate_limit_key=key)
    with pytest.raises(MobileAuthError) as still_limited:
        third._rate_limit(ip)
    assert still_limited.value.status == 429

    now[0] += 61
    third._rate_limit(ip)


def test_password_login_scope_cap_rejects_new_ips_and_expired_scopes_are_cleaned(tmp_path, monkeypatch):
    from app import mobile_auth

    monkeypatch.setattr(mobile_auth, "MAX_PASSWORD_LOGIN_SCOPES", 2)
    app = create_app(hosted_config(tmp_path))
    auth = app.extensions["mobile_auth"]
    now = [1_800_000_000.0]
    auth.clock = lambda: now[0]
    assert auth.verify_credentials("driver", "incorrect", "198.51.100.1") is None
    assert auth.verify_credentials("driver", "incorrect", "198.51.100.2") is None
    with pytest.raises(MobileAuthError) as limited:
        auth.verify_credentials("driver", "incorrect", "198.51.100.3")
    assert limited.value.status == 429
    now[0] += 61
    assert auth.verify_credentials("driver", "incorrect", "198.51.100.3") is None
    with app.extensions["beta_store"].read() as tx:
        rows = tx.list("password_login_attempts")
    assert len(rows) == 1


def test_mobile_password_rotation_between_verification_and_issue_does_not_create_session(tmp_path, monkeypatch):
    app = create_app(hosted_config(tmp_path))
    auth = app.extensions["mobile_auth"]
    store = app.extensions["beta_store"]
    verify = auth.verify_credentials

    def rotate_after_check(account, password, ip):
        user = verify(account, password, ip)
        with store.transaction() as tx:
            current = tx.get("users", account)
            current["password_hash"] = generate_password_hash("Replacement-password-for-race-test-2026")
            current["auth_epoch"] = current.get("auth_epoch", 0) + 1
            tx.put("users", account, current)
        return user

    monkeypatch.setattr(auth, "verify_credentials", rotate_after_check)
    with pytest.raises(MobileAuthError) as rejected:
        auth.login("driver", PASSWORDS["driver"], "203.0.113.8")
    assert rejected.value.status == 401
    with store.read() as tx:
        assert not any(row.get("user_id") == "driver" for row in tx.list("mobile_sessions"))
