"""Authenticated HTTP integration with synthetic worker output; no trip mutations."""
import io
import threading
import time
from uuid import uuid4

import pytest

from app import create_app, voice


class Worker:
    def __init__(self, path):
        self.closed = False
        self.path = path
    def alive(self): return not self.closed
    def close(self): self.closed = True
    def transcribe(self, path, language, identity, cancelled, deadline):
        assert path.read_bytes() == b"synthetic-audio"
        return {"request_id": identity, "text": "Hyderabad to Vijayawada", "duration_ms": 2000}


@pytest.fixture
def app(tmp_path):
    paths = {}
    for language in ("en", "te"):
        path = tmp_path / language
        path.mkdir()
        for name in ("model.bin", "config.json", "tokenizer.json"):
            (path / name).write_bytes(b"fixture")
        paths["VOICE_MODEL_PATH_" + language.upper()] = str(path)
    application = create_app({"TESTING": True, "SECRET_KEY": "voice-http-fixture", "DATABASE_PATH": str(tmp_path / "fixture.sqlite3"), "BETA_PASSWORD": "fixture-password", "VOICE_ENABLED": True, **paths})
    service = application.extensions["voice_service"]
    service._factory = Worker
    service._check_runtime = False
    yield application
    service.close()


def login(app, account="passenger"):
    response = app.test_client().post("/api/mobile/login", json={"account": account, "password": "fixture-password"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["token"]}


def upload(client, headers, identity=None, data=b"synthetic-audio", language="te", form_id=None):
    identity = identity or str(uuid4())
    return client.post("/api/voice/transcribe", headers={**headers, "X-Voice-Request-ID": identity}, data={
        "audio": (io.BytesIO(data), "recording.m4a"), "language": language, "request_id": form_id or identity,
    })


def test_auth_before_body_and_staff_denied(app, monkeypatch):
    client = app.test_client()
    def forbidden(*args, **kwargs): pytest.fail("unauthorized body was read")
    monkeypatch.setattr("app.parse_upload", forbidden)
    assert client.get("/api/voice/capabilities").status_code == 401
    assert upload(client, {}, data=b"x" * (voice.MAX_MULTIPART_BYTES + 1)).status_code == 401
    assert client.post("/api/voice/cancel", json={"request_id": str(uuid4())}).status_code == 401
    headers = login(app, "admin")
    assert client.get("/api/voice/capabilities", headers=headers).status_code == 403
    assert upload(client, headers).status_code == 403
    assert client.post("/api/voice/cancel", headers=headers, json={"request_id": str(uuid4())}).status_code == 403


def test_configured_languages_and_success_do_not_modify_bookings(app):
    client, headers = app.test_client(), login(app)
    service = app.extensions["voice_service"]
    caps = client.get("/api/voice/capabilities", headers=headers).json
    assert {key: caps[key] for key in ("available", "languages", "max_seconds", "max_bytes")} == {"available": True, "languages": ["en", "te"], "max_seconds": 45, "max_bytes": 2097152}
    assert caps["daily_remaining"] == 100 and caps["reset_at"].endswith("T00:00:00Z")
    store = app.extensions["beta_store"]
    with store.read() as tx:
        before = [tx.list(name) for name in ("trips", "bookings", "previews", "matches")]
    for _ in range(2):
        response = upload(client, headers)
        assert response.status_code == 200 and response.json["text"] == "Hyderabad to Vijayawada"
        assert response.json["language"] == "te" and response.json["duration_ms"] == 2000
        assert response.headers["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in response.headers
        assert not list(service._root.iterdir())
    with store.read() as tx:
        assert [tx.list(name) for name in ("trips", "bookings", "previews", "matches")] == before
    del service.model_paths["te"]
    assert client.get("/api/voice/capabilities", headers=headers).json["languages"] == ["en"]
    assert upload(client, headers).json["code"] == "VOICE_UNAVAILABLE"


def test_header_form_identity_and_limits(app):
    client, headers = app.test_client(), login(app)
    assert client.post("/api/voice/transcribe", headers=headers, data={}).json["code"] == "VOICE_INVALID_AUDIO"
    assert upload(client, headers, form_id=str(uuid4())).status_code == 400
    oversized = upload(client, headers, data=b"x" * (voice.MAX_BYTES + 1))
    assert oversized.status_code == 413 and oversized.json["code"] == "VOICE_INVALID_AUDIO"
    assert client.post("/api/voice/cancel", headers=headers, json={"request_id": str(uuid4()), "padding": "x" * 17000}).status_code == 413
    assert client.post("/api/search", headers=headers, json={"padding": "x" * 17000}).status_code == 413
    assert app.config["MAX_CONTENT_LENGTH"] == 16384


def test_web_origin_and_csrf_still_required(app):
    client = app.test_client()
    csrf = client.get("/api/bootstrap").json["csrf_token"]
    headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
    assert client.post("/api/login", headers=headers, json={"account": "passenger", "password": "fixture-password"}).status_code == 200
    assert upload(client, {}).status_code == 403
    assert upload(client, {**headers, "Origin": "https://unrelated.invalid"}).status_code == 403
    assert upload(client, headers).status_code == 200
    assert client.post("/api/voice/cancel", json={"request_id": str(uuid4())}).status_code == 403


def test_cancel_precedes_upload_and_owner_scope(app):
    client, alice, bob = app.test_client(), login(app), login(app, "passenger2")
    identity = str(uuid4())
    assert client.post("/api/voice/cancel", headers=alice, json={"request_id": identity}).status_code == 200
    assert upload(client, alice, identity).json["code"] == "VOICE_CANCELLED"
    assert upload(client, bob, identity).status_code == 200


@pytest.mark.parametrize("action", ["cancel", "logout"])
def test_same_token_cancel_or_logout_does_not_block_long_job(app, action):
    service, headers = app.extensions["voice_service"], login(app)
    started, released = threading.Event(), threading.Event()
    identity, responses = str(uuid4()), []
    class Blocking(Worker):
        def close(self):
            super().close()
            released.set()
        def transcribe(self, path, language, identity, cancelled, deadline):
            started.set()
            assert released.wait(3)
            # Simulate a child returning text concurrently with cancellation.
            return {"request_id": identity, "text": "must not escape", "duration_ms": 1000}
    service._factory = Blocking
    thread = threading.Thread(target=lambda: responses.append(upload(app.test_client(), headers, identity)))
    thread.start()
    assert started.wait(1)
    before = time.monotonic()
    client = app.test_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/voice/capabilities", headers=headers).status_code == 200
    if action == "cancel":
        result = client.post("/api/voice/cancel", headers=headers, json={"request_id": identity})
    else:
        result = client.post("/api/mobile/logout", headers=headers, json={})
    assert result.status_code == 200 and time.monotonic() - before < 1
    thread.join(1)
    assert not thread.is_alive()
    assert responses[0].status_code == 409 and responses[0].json["code"] == "VOICE_CANCELLED"
    assert "text" not in responses[0].json
    assert not list(service._root.iterdir())
    if action == "logout":
        assert client.get("/api/voice/capabilities", headers=headers).status_code == 401


def test_revalidates_revoked_token_before_returning_text(app):
    service, headers = app.extensions["voice_service"], login(app)
    auth = app.extensions["mobile_auth"]
    class Revoking(Worker):
        def transcribe(self, path, language, identity, cancelled, deadline):
            auth.revoke(auth.token_hash(headers["Authorization"].split(" ")[1]))
            return {"request_id": identity, "text": "must not escape", "duration_ms": 1000}
    service._factory = Revoking
    response = upload(app.test_client(), headers)
    assert response.status_code == 401 and "text" not in response.json


def test_busy_and_rate_limit_reject_before_reading_body(app, monkeypatch):
    service, headers = app.extensions["voice_service"], login(app)
    with service.reserve("passenger2"):
        monkeypatch.setattr("app.parse_upload", lambda *args: pytest.fail("busy body was read"))
        assert upload(app.test_client(), headers).status_code == 429


def test_voice_disabled_never_advertises_languages(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "disabled", "DATABASE_PATH": str(tmp_path / "db"), "BETA_PASSWORD": "fixture-password", "VOICE_ENABLED": False})
    try:
        response = app.test_client().get("/api/voice/capabilities", headers=login(app))
        assert response.json["available"] is False and response.json["languages"] == []
    finally:
        app.extensions["voice_service"].close()


@pytest.fixture
def real_server(app):
    from werkzeug.serving import make_server, WSGIRequestHandler
    class Quiet(WSGIRequestHandler):
        def log(self, *args, **kwargs): pass
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    thread.join(2)
    server.server_close()


def http(port, method, path, headers=None, body=None):
    import http.client
    import json
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    headers = dict(headers or {})
    if body is not None:
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("action", ["cancel", "logout", "timeout"])
def test_real_slow_upload_does_not_block_health_cancel_or_logout(app, real_server, action, monkeypatch):
    import socket
    import json
    port, headers = real_server, login(app)
    identity = str(uuid4())
    if action == "timeout":
        monkeypatch.setattr(voice, "UPLOAD_SECONDS", .2)
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    prefix = (f"POST /api/voice/transcribe HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
              f"Authorization: {headers['Authorization']}\r\nX-Voice-Request-ID: {identity}\r\n"
              "Content-Type: multipart/form-data; boundary=fixture\r\nContent-Length: 10000\r\nConnection: close\r\n\r\n")
    try:
        sock.sendall(prefix.encode())  # Deliberately send no body bytes.
        service = app.extensions["voice_service"]
        for _ in range(100):
            if service._active and service._active.abort_upload:
                break
            time.sleep(.005)
        assert service._active and service._active.identity == identity
        before = time.monotonic()
        assert http(port, "GET", "/api/health")[0] == 200
        assert http(port, "GET", "/api/voice/capabilities", headers)[0] == 200
        if action == "cancel":
            assert http(port, "POST", "/api/voice/cancel", headers, {"request_id": identity})[0] == 200
        elif action == "logout":
            assert http(port, "POST", "/api/mobile/logout", headers, {})[0] == 200
        assert time.monotonic() - before < 1
        response = bytearray()
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            response.extend(chunk)
        assert (b"504" if action == "timeout" else b"409") in response.split(b"\r\n", 1)[0]
        assert (b"VOICE_TIMEOUT" if action == "timeout" else b"VOICE_CANCELLED") in response
        assert service._active is None and service._worker is None
        assert not list(service._root.iterdir())
    finally:
        sock.close()
    # An unrelated request after the timer cannot have its connection shut down.
    assert http(port, "GET", "/api/health")[0] == 200


@pytest.mark.parametrize("code,status", [("VOICE_NO_SPEECH", 422), ("VOICE_INVALID_AUDIO", 400), ("VOICE_TIMEOUT", 504), ("VOICE_UNAVAILABLE", 503)])
def test_transcription_errors_have_stable_codes_and_no_text(app, code, status):
    class Failing(Worker):
        def transcribe(self, *args): raise voice.VoiceError(code)
    service = app.extensions["voice_service"]
    service._factory = Failing
    result = upload(app.test_client(), login(app))
    assert result.status_code == status and result.json["code"] == code
    assert "text" not in result.json and not list(service._root.iterdir())


def test_binary_multipart_boundaries_do_not_reject_valid_sized_audio(app):
    class Binary(Worker):
        def transcribe(self, path, language, identity, cancelled, deadline):
            assert path.stat().st_size == voice.MAX_BYTES
            return {"request_id": identity, "text": "fixture only", "duration_ms": 2000}
    app.extensions["voice_service"]._factory = Binary
    # Binary PCM may end a parser read on CR/LF. Leave room for a parser chunk
    # plus an incomplete multipart boundary rather than rejecting it as a field.
    result = upload(app.test_client(), login(app), data=b"\r" * voice.MAX_BYTES)
    assert result.status_code == 200


def test_http_quota_capability_error_and_restart(app):
    headers, client = login(app), app.test_client()
    service = app.extensions["voice_service"]
    service._quota.limit = 1
    app.config["VOICE_DAILY_LIMIT"] = 1
    assert upload(client, headers).status_code == 200
    caps = client.get("/api/voice/capabilities", headers=headers).json
    assert caps["daily_remaining"] == 0 and caps["reset_at"].endswith("T00:00:00Z")
    rejected = upload(client, headers)
    assert rejected.status_code == 429
    assert rejected.json["code"] == "VOICE_DAILY_LIMIT" and rejected.json["daily_remaining"] == 0
    assert rejected.json["reset_at"] == caps["reset_at"]
    service.close()
    recreated = create_app(dict(app.config))
    recreated.extensions["voice_service"]._check_runtime = False
    try:
        caps = recreated.test_client().get("/api/voice/capabilities", headers=headers).json
        assert caps["daily_remaining"] == 0
        assert upload(recreated.test_client(), headers).json["code"] == "VOICE_DAILY_LIMIT"
    finally:
        recreated.extensions["voice_service"].close()


def test_denied_requests_and_caps_do_not_consume_daily_quota(app):
    client, member, staff = app.test_client(), login(app), login(app, "admin")
    assert upload(client, {}).status_code == 401
    assert upload(client, staff).status_code == 403
    assert upload(client, member, data=b"x" * (voice.MAX_MULTIPART_BYTES + 1)).status_code == 413
    for _ in range(2):
        assert client.get("/api/voice/capabilities", headers=member).json["daily_remaining"] == 100
    # A malformed body is an admitted attempt and is conservatively counted.
    assert upload(client, member, form_id=str(uuid4())).status_code == 400
    assert client.get("/api/voice/capabilities", headers=member).json["daily_remaining"] == 99


def test_same_token_logout_is_not_blocked_by_quota_transaction_wait(app, monkeypatch):
    service, headers = app.extensions["voice_service"], login(app)
    entered, released = threading.Event(), threading.Event()
    consume = service._quota.consume
    def slow_quota():
        entered.set()
        assert released.wait(2)
        consume()
    monkeypatch.setattr(service._quota, "consume", slow_quota)
    responses = []
    thread = threading.Thread(target=lambda: responses.append(upload(app.test_client(), headers)))
    thread.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert app.test_client().post("/api/mobile/logout", headers=headers, json={}).status_code == 200
        assert time.monotonic() - started < 1
    finally:
        released.set()
        thread.join(2)
    assert not thread.is_alive() and responses[0].status_code == 409
    assert service.capabilities()["daily_remaining"] == 99 and service._active is None
