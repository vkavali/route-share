from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True, "SECRET_KEY": "native-auth-test-key",
        "DATABASE_PATH": str(tmp_path / "beta.sqlite3"), "BETA_PASSWORD": "correct-horse-battery",
    })
    store = application.extensions["beta_store"]
    now = datetime.now(timezone.utc)
    pickup_at = now + timedelta(minutes=5)
    dropoff_at = now + timedelta(hours=2)
    pickup = {"label": "Pickup", "lat": 17.01, "lon": 78.01}
    dropoff = {"label": "Dropoff", "lat": 17.1, "lon": 78.1}
    trip = {
        "id": "trip-mobile", "driver_id": "driver", "driver_name": "Development driver", "status": "published",
        "version": 1, "origin": {"label": "Origin", "lat": 17, "lon": 78},
        "departure": now.isoformat(),
        "destination": {"label": "Destination", "lat": 17.2, "lon": 78.2}, "seats": 3,
        "route": {"provider": "fixture", "coordinates": [[78.0, 17.0], [78.01, 17.01], [78.1, 17.1], [78.2, 17.2]], "distance_m": 30000},
    }
    booking = {
        "id": "booking-mobile", "trip_id": trip["id"], "driver_id": "driver", "passenger_id": "passenger",
        "driver_name": "Development driver", "passenger_name": "Development passenger", "status": "accepted",
        "pickup": pickup, "dropoff": dropoff, "seats": 1, "start_m": 1000, "end_m": 20000,
        "match": {"routed_pickup": pickup, "routed_dropoff": dropoff,
                  "pickup_at": pickup_at.isoformat(), "dropoff_at": dropoff_at.isoformat()},
    }
    with store.transaction() as tx:
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def mobile_login(client, account="passenger", password="correct-horse-battery", ip="127.0.0.1"):
    return client.post("/api/mobile/login", json={"account": account, "password": password}, environ_overrides={"REMOTE_ADDR": ip})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def web_login(client, account="passenger"):
    bootstrap = client.get("/api/bootstrap").json
    return client.post("/api/login", json={"account": account, "password": "correct-horse-battery"}, headers={
        "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": bootstrap["csrf_token"],
    })


def mobile_post(client, path, token, body):
    return client.post(path, json=body, headers=bearer(token))


def test_mobile_login_returns_opaque_token_without_web_cookie_and_stores_only_hash(app, client):
    response = mobile_login(client)
    assert response.status_code == 200
    result = response.json
    assert result["token"] and result["expires_at"]
    assert result["user"]["id"] == "passenger"
    assert result["user"]["access"] == {"is_staff": False, "can_drive": False, "staff_capabilities": []}
    assert "password_hash" not in str(result)
    assert "Set-Cookie" not in response.headers
    with app.extensions["beta_store"].read() as tx:
        sessions = tx.list("mobile_sessions")
    assert len(sessions) == 1
    assert sessions[0]["id"] != result["token"]
    assert sessions[0]["id"] == app.extensions["mobile_auth"].token_hash(result["token"])
    assert result["token"] not in str(sessions)


def test_bearer_and_web_clients_share_service_permissions_without_session_override(app):
    mobile, web = app.test_client(), app.test_client()
    native = mobile_login(mobile).json
    assert web_login(web).status_code == 200
    native_state = mobile.get("/api/state", headers=bearer(native["token"]))
    web_state = web.get("/api/state")
    assert native_state.status_code == web_state.status_code == 200
    assert native_state.json["user"]["id"] == web_state.json["user"]["id"] == "passenger"
    assert native_state.json["bookings"] == web_state.json["bookings"]

    # Native bootstrap returns the authenticated safe user without minting or
    # setting a browser CSRF session cookie.
    bootstrap = mobile.get("/api/bootstrap", headers=bearer(native["token"]))
    assert bootstrap.json["user"]["id"] == "passenger"
    assert bootstrap.json["csrf_token"] is None
    assert "Set-Cookie" not in bootstrap.headers
    assert "password_hash" not in str(bootstrap.json)

    # An invalid bearer credential takes precedence over an otherwise valid cookie.
    assert web.get("/api/state", headers={"Authorization": "Bearer invalid-token"}).status_code == 401
    assert mobile.get("/api/operations", headers=bearer(native["token"])).status_code == 403


def test_bearer_posts_skip_csrf_but_web_cookie_posts_still_require_it(app):
    native, web = app.test_client(), app.test_client()
    token = mobile_login(native).json["token"]
    assert web_login(web, "driver").status_code == 200
    assert web.post("/api/start_sharing", json={"booking_id": "booking-mobile"}).status_code == 403
    started = mobile_post(native, "/api/start_sharing", token, {"booking_id": "booking-mobile"})
    assert started.status_code == 200
    updated = mobile_post(native, "/api/share_location", token, {
        "booking_id": "booking-mobile", "sharing_id": started.json["sharing_id"],
        "lat": 17.02, "lon": 78.02, "accuracy": 20,
    })
    assert updated.status_code == 200
    assert "Access-Control-Allow-Origin" not in updated.headers


def test_mobile_logout_revokes_only_that_token_and_stops_actor_location_sharing(app):
    client = app.test_client()
    first = mobile_login(client).json["token"]
    second = mobile_login(client).json["token"]
    started = mobile_post(client, "/api/start_sharing", second, {"booking_id": "booking-mobile"})
    assert started.status_code == 200
    mobile_post(client, "/api/share_location", second, {
        "booking_id": "booking-mobile", "sharing_id": started.json["sharing_id"],
        "lat": 17.02, "lon": 78.02, "accuracy": 20,
    })
    assert app.extensions["live_location_store"]._samples
    logout = mobile_post(client, "/api/mobile/logout", first, {})
    assert logout.status_code == 200
    assert client.get("/api/state", headers=bearer(first)).status_code == 401
    assert client.get("/api/state", headers=bearer(second)).status_code == 200
    assert app.extensions["live_location_store"]._samples == {}


def test_mobile_expiration_rejects_token_and_removes_session(client, app):
    now = [1_800_000_000.0]
    auth = app.extensions["mobile_auth"]
    auth.clock = lambda: now[0]
    issued = mobile_login(client).json
    assert datetime.fromisoformat(issued["expires_at"]).timestamp() == pytest.approx(now[0] + 8 * 60 * 60)
    now[0] += 8 * 60 * 60 + 1
    response = client.get("/api/state", headers=bearer(issued["token"]))
    assert response.status_code == 401
    with app.extensions["beta_store"].read() as tx:
        assert tx.list("mobile_sessions") == []


def test_mobile_operations_do_not_expose_sessions_or_token_material(client, app):
    token = mobile_login(client, account="admin").json["token"]
    response = client.get("/api/operations", headers=bearer(token))
    assert response.status_code == 200
    assert "mobile_sessions" not in response.json
    assert token not in str(response.json)
    with app.extensions["beta_store"].read() as tx:
        session_hash = tx.list("mobile_sessions")[0]["id"]
    assert session_hash not in str(response.json)


def test_mobile_login_rate_limits_ip_account_pair(client):
    for _ in range(10):
        assert mobile_login(client, password="wrong", ip="192.0.2.1").status_code == 401
    limited = mobile_login(client, password="wrong", ip="192.0.2.1")
    assert limited.status_code == 429
    assert limited.json["code"] == "rate_limited"


def test_authentication_releases_token_lock_when_session_store_read_fails(client, app, monkeypatch):
    token = mobile_login(client).json["token"]
    auth = app.extensions["mobile_auth"]
    store = app.extensions["beta_store"]
    original_read = store.read
    calls = 0

    def fail_after_initial_lookup():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected session-store failure")
        return original_read()

    monkeypatch.setattr(store, "read", fail_after_initial_lookup)
    with pytest.raises(RuntimeError, match="injected session-store failure"):
        auth.authenticate(token)

    digest = auth.token_hash(token)
    lock = auth._token_locks[int(digest[:2], 16) % len(auth._token_locks)]
    assert lock._is_owned() is False
