import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-signing-key",
        "DATABASE_PATH": str(tmp_path / "beta.sqlite3"),
        "BETA_PASSWORD": "correct-horse-battery",
    })


@pytest.fixture
def client(app):
    return app.test_client()


def same_origin(client):
    return {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}


def csrf(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    return response.json["csrf_token"]


def login(client, account="driver"):
    token = csrf(client)
    return client.post(
        "/api/login",
        json={"account": account, "password": "correct-horse-battery"},
        headers={**same_origin(client), "X-CSRF-Token": token},
    )


def test_bootstrap_and_login_never_expose_password_hash(client):
    initial = client.get("/api/bootstrap").json
    assert initial["user"] is None
    assert initial["flags"]["public_registration_enabled"] is False
    assert initial["flags"]["paid_rides_enabled"] is False
    assert "password" not in str(initial).lower()

    response = client.post(
        "/api/login",
        json={"account": "driver", "password": "correct-horse-battery"},
        headers={**same_origin(client), "X-CSRF-Token": initial["csrf_token"]},
    )
    assert response.status_code == 200
    assert response.json["user"]["development"] is True
    assert "password_hash" not in str(response.json)
    assert client.get("/api/bootstrap").json["user"]["id"] == "driver"


def test_posts_require_csrf_and_same_origin_even_for_login(client):
    assert client.post("/api/login", json={"account": "driver", "password": "x"}).status_code == 403
    token = csrf(client)
    cross_site = client.post(
        "/api/login",
        json={"account": "driver", "password": "correct-horse-battery"},
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": token},
    )
    assert cross_site.status_code == 403
    no_token = client.post("/api/logout", json={}, headers=same_origin(client))
    assert no_token.status_code == 403


def test_bad_hosts_and_non_json_requests_are_rejected(client):
    response = client.get("/api/bootstrap", headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert response.json["error"]
    token = csrf(client)
    response = client.post(
        "/api/login", data="{}", content_type="text/plain",
        headers={**same_origin(client), "X-CSRF-Token": token},
    )
    assert response.status_code == 415


def test_login_rejects_nonstandard_json_numbers(client):
    token = csrf(client)
    response = client.post(
        "/api/login", data='{"account":"driver","password":NaN}',
        content_type="application/json",
        headers={**same_origin(client), "X-CSRF-Token": token},
    )
    assert response.status_code == 400


def test_state_requires_login_and_operations_requires_admin(client):
    assert client.get("/api/state").status_code == 401
    assert login(client).status_code == 200
    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json["user"]["id"] == "driver"
    assert client.get("/api/operations").status_code == 403

    client.post(
        "/api/logout", json={},
        headers={**same_origin(client), "X-CSRF-Token": csrf(client)},
    )
    assert login(client, "admin").status_code == 200
    operations = client.get("/api/operations")
    assert operations.status_code == 200
    assert "password_hash" not in str(operations.json)


def test_action_payload_is_bounded_and_errors_are_json(client):
    assert login(client).status_code == 200
    token = csrf(client)
    missing = client.post(
        "/api/publish", json={},
        headers={**same_origin(client), "X-CSRF-Token": token},
    )
    assert missing.status_code == 400
    assert missing.json["error"]
    large = client.post(
        "/api/preview", data="x" * (16 * 1024 + 1), content_type="application/json",
        headers={**same_origin(client), "X-CSRF-Token": token},
    )
    assert large.status_code == 413
    assert large.json["error"]


def test_responses_are_not_cached_and_use_security_headers(client):
    response = client.get("/api/bootstrap")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    directives = {
        directive.split()[0]: directive.split()[1:]
        for directive in response.headers["Content-Security-Policy"].split(";")
        if directive.strip()
    }
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["script-src"] == ["'self'"]
    assert directives["connect-src"] == ["'self'", "https://tiles.openfreemap.org"]
    assert directives["worker-src"] == ["'self'", "blob:"]
