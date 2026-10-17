#!/usr/bin/env python3
"""Bounded local HTTP capacity and recovery check using synthetic accounts only.

This is a development harness, not a production load test. It starts a threaded
loopback WSGI server, injects a deterministic routing fixture and isolated OTP
provider, then writes only to a temporary SQLite database under --scratch-dir.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402
from werkzeug.serving import WSGIRequestHandler, make_server  # noqa: E402

from app import create_app  # noqa: E402
from app.auth import issue_web_session_in  # noqa: E402
from app.store import Store  # noqa: E402
from scripts.backup_store import BackupError, backup, restore  # noqa: E402


class IsolatedOtpProvider:
    ready = True

    def send(self, phone, *, challenge_id, expires_in):
        del phone, expires_in
        return "isolated-test-" + challenge_id

    def verify(self, handle, code):
        return handle.startswith("isolated-test-") and code == "194628"


class FixtureRouter:
    """Deterministic straight-line route; never contacts a routing service."""

    def route(self, points):
        coordinates = [[point["lon"], point["lat"]] for point in points]
        legs = [math.dist(a, b) * 111_000 for a, b in zip(coordinates, coordinates[1:])]
        length = sum(legs)
        direct = max(math.dist(coordinates[0], coordinates[-1]) * 111_000, 1.0)
        duration = 3600 * length / direct
        return {
            "coordinates": coordinates,
            "distance_m": length,
            "duration_s": duration,
            "leg_durations_s": [3600 * leg / direct for leg in legs],
            "waypoints": [{"location": coord, "distance": 0} for coord in coordinates],
            "provider": "FIXTURE ONLY - production capacity check",
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }


class EightSlotGate:
    """Approximate the app's one-worker/eight-request-slot bound locally."""

    def __init__(self, application, slots=8):
        self.application = application
        self.semaphore = threading.BoundedSemaphore(slots)

    def __call__(self, environ, start_response):
        self.semaphore.acquire()
        try:
            yield from self.application(environ, start_response)
        finally:
            self.semaphore.release()


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, *_args, **_kwargs):
        pass

    def log_error(self, *_args, **_kwargs):
        pass


class HttpSession:
    def __init__(self, origin, cookie="", csrf="", account_id=None):
        self.origin, self.cookie, self.csrf = origin, cookie, csrf
        self.account_id = account_id
        self.app = None
        self.diagnostics = []

    def _cookie_facts(self):
        facts = {"cookie_present": bool(self.cookie), "account_id": self.account_id,
                 "supplied_csrf_present": bool(self.csrf), "signature_valid": False,
                 "signature_error": None, "decoded_account_matches": False,
                 "cookie_csrf_present": False, "cookie_csrf_matches": False,
                 "signature_age_valid": None, "signature_age_error": None,
                 "signed_at_unix": None, "cookie_age_seconds": None}
        if not self.cookie or self.app is None:
            return facts
        value = self.cookie.partition("=")[2]
        serializer = self.app.session_interface.get_signing_serializer(self.app)
        try:
            decoded = serializer.loads(value)
            facts["signature_valid"] = True
            facts["decoded_account_matches"] = decoded.get("account") == self.account_id
            token = decoded.get("csrf_token")
            facts["cookie_csrf_present"] = bool(token)
            facts["cookie_csrf_matches"] = bool(token and self.csrf and secrets.compare_digest(str(token), self.csrf))
        except Exception as exc:
            facts["signature_error"] = type(exc).__name__
        try:
            serializer.loads(value, max_age=self.app.permanent_session_lifetime.total_seconds())
            facts["signature_age_valid"] = True
        except Exception as exc:
            facts["signature_age_valid"] = False
            facts["signature_age_error"] = type(exc).__name__
        try:
            _payload, signed_at = serializer.make_signer().unsign(value, return_timestamp=True)
            signed_at_unix = signed_at.timestamp()
            facts["signed_at_unix"] = round(signed_at_unix, 3)
            facts["cookie_age_seconds"] = round(time.time() - signed_at_unix, 3)
        except Exception:
            pass
        return facts

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", int(self.origin.rsplit(":", 1)[1]), timeout=20)
        headers = {"Host": self.origin.split("//", 1)[1], "Connection": "close"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"))
            headers.update({"Content-Type": "application/json", "Origin": self.origin,
                            "X-CSRF-Token": self.csrf})
        started = time.perf_counter()
        cookie_before = self.cookie
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            elapsed = time.perf_counter() - started
            set_cookie = response.getheader("Set-Cookie")
            try:
                parsed = json.loads(raw) if raw else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed = None
            if response.status in {401, 403}:
                facts = self._cookie_facts()
                error_payload = parsed if isinstance(parsed, dict) else {}
                self.diagnostics.append({"method": method, "path": path, "status": response.status,
                                         "error": str(error_payload.get("error", ""))[:160],
                                         "code": str(error_payload.get("code", ""))[:80],
                                         "response_set_cookie": bool(set_cookie),
                                         "response_cookie_changed": bool(set_cookie and set_cookie.split(";", 1)[0] != cookie_before),
                                         **facts})
            if set_cookie:
                self.cookie = set_cookie.split(";", 1)[0]
            return response.status, parsed, elapsed
        finally:
            connection.close()


def _seed_synthetic_users(store, count, password):
    password_hash = generate_password_hash(password)
    defaults = {"phone": "", "share_phone": False,
                "verification": {key: "not_checked" for key in
                                 ("phone", "identity", "dl", "rc", "insurance", "selfie")}}
    with store.transaction() as tx:
        for number in range(count):
            identity = f"capacity-user-{number:03d}"
            tx.put("users", identity, {"id": identity, "name": f"Synthetic User {number:03d}",
                   **defaults, "role": "member", "development": True, "account_status": "active",
                   "auth_epoch": 0, "password_hash": password_hash, "driver_approved": False,
                   "driver_approval": None, "staff_capabilities": []})
    return [f"capacity-user-{number:03d}" for number in range(count)]


def _session_for_user(app, origin, account):
    """Mint an isolated signed web session; HTTP work still traverses WSGI."""
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with app.extensions["beta_store"].transaction() as tx:
        user = tx.get("users", account)
        if not user:
            raise RuntimeError(f"synthetic account missing: {account}")
        issue_web_session_in(tx, user, session_id)
    serializer = app.session_interface.get_signing_serializer(app)
    cookie_value = serializer.dumps({"account": account, "auth_epoch": user.get("auth_epoch", 0),
                                     "auth_session_id": session_id, "csrf_token": csrf, "_permanent": True})
    cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
    session = HttpSession(origin, f"{cookie_name}={cookie_value}", csrf, account_id=account)
    session.app = app
    return session


def _signup_probe(app, origin):
    session = HttpSession(origin)
    session.app = app
    status, bootstrap, _ = session.request("GET", "/api/bootstrap")
    if status != 200 or not bootstrap["phone_auth"]["enabled"]:
        raise RuntimeError("isolated phone signup did not advertise the injected test provider")
    session.csrf = bootstrap["csrf_token"]
    flow = secrets.token_urlsafe(32)
    start_payload = {"phone": "9876543210", "flow_token": flow, "request_id": str(uuid.uuid4())}
    status, challenge, _ = session.request("POST", "/api/phone/start", start_payload)
    if status != 200:
        raise RuntimeError(f"isolated phone signup start failed with HTTP {status}")
    status, verified, _ = session.request("POST", "/api/phone/verify", {
        "challenge_id": challenge["challenge_id"], "flow_token": flow, "code": "194628",
        "consent": {"terms_version": bootstrap["phone_auth"]["terms_version"],
                    "privacy_version": bootstrap["phone_auth"]["privacy_version"],
                    "adult_attested": True, "terms_accepted": True, "privacy_accepted": True},
    })
    if status != 200 or not verified.get("onboarding_required"):
        raise RuntimeError(f"isolated phone signup verify failed with HTTP {status}")
    session.csrf = verified["csrf_token"]
    status, profile, _ = session.request("POST", "/api/phone/profile", {"name": "Synthetic Signup Probe"})
    if status != 200:
        raise RuntimeError(f"isolated phone profile completion failed with HTTP {status}")
    return {"http_signup": "passed", "provider": "isolated in-process OTP fixture",
            "phone": "redacted", "onboarding_completed": True,
            "auth_failures": session.diagnostics}


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return round(ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)] * 1000, 2)


def _measure_level(origin, sessions, concurrency, iterations):
    paths = ("page", "bootstrap", "state", "search")
    timings = {path: [] for path in paths}
    statuses = {path: {} for path in paths}
    timing_lock = threading.Lock()

    def worker(session, offset):
        local = {path: [] for path in paths}
        local_status = {path: {} for path in paths}
        for iteration in range(iterations):
            kind = paths[(iteration + offset) % len(paths)]
            if kind == "page":
                method, path, payload = "GET", "/", None
            elif kind == "bootstrap":
                method, path, payload = "GET", "/api/bootstrap", None
            elif kind == "state":
                method, path, payload = "GET", "/api/state", None
            else:
                method, path, payload = "POST", "/api/search", SEARCH_PAYLOAD
            status, result, elapsed = session.request(method, path, payload)
            local[kind].append(elapsed)
            local_status[kind][status] = local_status[kind].get(status, 0) + 1
            if status != 200:
                local_status[kind]["unexpected"] = local_status[kind].get("unexpected", 0) + 1
        with timing_lock:
            for kind in paths:
                timings[kind].extend(local[kind])
                for status, count in local_status[kind].items():
                    statuses[kind][status] = statuses[kind].get(status, 0) + count

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda item: worker(*item), [(sessions[i], i) for i in range(concurrency)]))
    return {"concurrent_clients": concurrency, "iterations_per_client": iterations,
            "operations": {kind: {"samples": len(values), "p50_ms": _percentile(values, .50),
                                  "p95_ms": _percentile(values, .95), "p99_ms": _percentile(values, .99),
                                  "statuses": statuses[kind]} for kind, values in timings.items()},
            "auth_failure_diagnostics": [diagnostic for session in sessions[:concurrency]
                                         for diagnostic in session.diagnostics]}


def _booking_invariant_check(sessions, driver, concurrency):
    passengers = sessions[:concurrency]
    candidates = []
    for passenger in passengers:
        status, result, _ = passenger.request("POST", "/api/search", SEARCH_PAYLOAD)
        if status != 200 or not isinstance(result, dict) or not result.get("matches"):
            detail = result if isinstance(result, dict) else {"response": type(result).__name__}
            raise RuntimeError(f"fixture search did not produce a match (HTTP {status}: {detail!r})")
        status, requested, _ = passenger.request("POST", "/api/request", {"match_id": result["matches"][0]["id"]})
        if status != 200:
            raise RuntimeError(f"fixture seat request failed with HTTP {status}")
        candidates.append((passenger, requested["booking"]["id"]))

    def accept(item):
        _, booking_id = item
        return driver.request("POST", "/api/accept", {"booking_id": booking_id})

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        outcomes = list(pool.map(accept, candidates))
    accepted = [result["booking"]["id"] for status, result, _ in outcomes
                if status == 200 and result.get("booking", {}).get("status") == "accepted"]
    race_statuses_valid = all(
        status == 409 or (status == 200 and result.get("booking", {}).get("status") == "accepted")
        for status, result, _ in outcomes
    )
    return candidates, outcomes, accepted, race_statuses_valid


SEARCH_PAYLOAD = {
    "origin": {"label": "Synthetic pickup", "lat": 17.385, "lon": 78.49},
    "destination": {"label": "Synthetic dropoff", "lat": 17.385, "lon": 78.57},
    "window_start": "2030-01-01T09:05:00+05:30",
    "window_end": "2030-01-01T10:00:00+05:30",
    "seats": 1,
}


def run(args):
    scratch = Path(args.scratch_dir).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="seatpal-capacity-", dir=scratch))
    database = run_dir / "capacity.sqlite3"
    password = "isolated-capacity-check-only"
    otp_provider = IsolatedOtpProvider()
    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(run_dir)
    try:
        app = create_app({"TESTING": True, "HOSTED_MODE": False, "SECRET_KEY": "isolated-capacity-check-signing-key",
                          "DATABASE_PATH": str(database), "SECRET_PATH": str(run_dir / "flask-secret"),
                          "BETA_PASSWORD": password, "PHONE_AUTH_PROVIDER": otp_provider,
                          "PHONE_AUTH_ENABLED": True, "PHONE_AUTH_HMAC_KEY": "isolated-phone-auth-key-" * 3,
                          "PHONE_AUTH_DAILY_LIMIT": 100, "PUBLIC_OPERATOR_NAME": "Synthetic Capacity Test",
                          "PUBLIC_SUPPORT_EMAIL": "capacity-test@example.invalid",
                          "BACKUP_EMAIL_ENABLED": False, "VOICE_ENABLED": False, "DIRECT_UPI_ENABLED": False,
                          "IDENTITY_EVIDENCE_KEY": "isolated-identity-evidence-key"})
    finally:
        tempfile.tempdir = previous_tempdir
    app.extensions["beta_service"].router = FixtureRouter()
    store = app.extensions["beta_store"]
    signup = None
    server = make_server("127.0.0.1", 0, EightSlotGate(app), threaded=True,
                         request_handler=QuietRequestHandler)
    port = server.server_port
    origin = f"http://127.0.0.1:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        signup = _signup_probe(app, origin)
        accounts = _seed_synthetic_users(store, 100, password)
        sessions = [_session_for_user(app, origin, identity) for identity in accounts]
        driver = _session_for_user(app, origin, "driver")

        departure = (datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(days=2)).replace(
            hour=9, minute=0, second=0, microsecond=0)
        trip_preview = {"origin": {"label": "Synthetic driver start", "lat": 17.385, "lon": 78.48},
                        "destination": {"label": "Synthetic driver end", "lat": 17.385, "lon": 78.58},
                        "departure": departure.isoformat(), "seats": 1, "max_detour_minutes": 15}
        status, preview, _ = driver.request("POST", "/api/preview", trip_preview)
        if status != 200:
            raise RuntimeError(f"synthetic trip preview failed with HTTP {status}")
        status, published, _ = driver.request("POST", "/api/publish", {"preview_id": preview["preview"]["id"]})
        if status != 200:
            raise RuntimeError(f"synthetic trip publish failed with HTTP {status}")
        departure_window_start = departure + timedelta(minutes=5)
        departure_window_end = departure + timedelta(minutes=60)
        SEARCH_PAYLOAD["window_start"] = departure_window_start.isoformat()
        SEARCH_PAYLOAD["window_end"] = departure_window_end.isoformat()

        levels = []
        for concurrency in args.concurrency:
            if concurrency > len(sessions):
                raise RuntimeError("concurrency cannot exceed the 100 seeded synthetic users")
            levels.append(_measure_level(origin, sessions, concurrency, args.iterations))

        try:
            candidates, outcomes, accepted, race_statuses_valid = _booking_invariant_check(
                sessions, driver, max(args.concurrency))
        except RuntimeError as exc:
            # Preserve completed measurements when the end-to-end fixture flow
            # fails before the full recovery/invariant report can be assembled.
            partial = {
                "classification": "isolated local fixture result; not a live provider or production-capacity claim",
                "synthetic_registered_users": 100,
                "public_phone_signup_probe": signup,
                "external_services": "none; in-process OTP and deterministic routing fixtures",
                "runtime_boundary": "threaded Werkzeug loopback server with an eight-request semaphore; one process, not Gunicorn or Railway",
                "scenario": {"concurrency_levels": args.concurrency,
                             "iterations_per_client_per_level": args.iterations,
                             "paths": ["/", "/api/bootstrap", "/api/state", "/api/search"],
                             "booking_race_clients": max(args.concurrency), "fixture_trip_capacity_seats": 1},
                "levels": levels,
                "failure_stage": "booking_fixture_or_race",
                "failure": str(exc),
                "storage_recovery": {"status": "not reached"},
                "result": "FAIL",
                "limitations": ["Capacity measurements completed before the booking fixture failure; backup/restore and booking invariants were not reached.",
                                "This local result does not model Railway CPU or volume latency, TLS, third-party provider timing, or 100 simultaneous users."],
            }
            output = report_dir / f"production-capacity-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-partial.json"
            output.write_text(json.dumps(partial, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"result": "FAIL", "report": str(output), "failure_stage": partial["failure_stage"],
                              "failure": partial["failure"], "levels": levels}, indent=2))
            return 1
        with store.read() as tx:
            all_bookings = tx.list("bookings")
            accepted_for_trip = [b for b in all_bookings if b.get("trip_id") == published["trip"]["id"]
                                 and b.get("status") in {"accepted", "segment_completed"}]
            passenger_isolation = True
            for passenger, booking_id in candidates:
                status, state, _ = passenger.request("GET", "/api/state")
                allowed = {row["id"] for row in state.get("bookings", [])}
                owns_requests = all(row.get("passenger_id") == passenger.account_id
                                    for row in state.get("requests", []))
                owns_bookings = all(row.get("passenger_id") == passenger.account_id
                                    for row in state.get("bookings", []))
                own_booking = next((row for row in state.get("bookings", [])
                                    if row.get("id") == booking_id), None)
                if (status != 200 or allowed != {booking_id} or own_booking is None
                        or own_booking.get("passenger_id") != passenger.account_id
                        or not owns_requests or not owns_bookings):
                    passenger_isolation = False
                    break
            accepted_count = sum(int(b.get("seats", 0)) for b in accepted_for_trip)

        data_bytes = sum(Path(str(database) + suffix).stat().st_size
                         for suffix in ("", "-wal", "-shm") if Path(str(database) + suffix).exists())
        backup_dir, restored_path = run_dir / "backup", run_dir / "restored.sqlite3"
        recovery = {"status": "blocked", "reason": "not attempted"}
        try:
            backup_started = time.perf_counter()
            manifest = backup(database, backup_dir)
            backup_ms = round((time.perf_counter() - backup_started) * 1000, 2)
            restore_started = time.perf_counter()
            restored = restore(backup_dir, restored_path)
            restore_ms = round((time.perf_counter() - restore_started) * 1000, 2)
            recovery = {"status": "passed", "snapshot_bytes": manifest["bytes"],
                        "snapshot_ms": backup_ms, "restore_ms": restore_ms,
                        "restored_integrity": restored["integrity"],
                        "restored_document_count": restored["counts"]["documents"]}
        except (BackupError, OSError, RuntimeError) as exc:
            recovery = {"status": "blocked", "reason": str(exc)[:240]}

        unexpected = sum(count for level in levels for op in level["operations"].values()
                         for status, count in op["statuses"].items() if status == "unexpected")
        threshold_failures = [f"concurrency {level['concurrent_clients']} {name} p95 >= 2000ms"
                              for level in levels for name, op in level["operations"].items()
                              if op["p95_ms"] is None or op["p95_ms"] >= 2000]
        failed = bool(unexpected or len(accepted) != 1 or accepted_count != 1 or not race_statuses_valid
                      or not passenger_isolation
                      or recovery["status"] != "passed"
                      or threshold_failures)
        report = {
            "classification": "isolated local fixture result; not a live provider or production-capacity claim",
            "synthetic_registered_users": 100,
            "public_phone_signup_probe": signup,
            "external_services": "none; in-process OTP and deterministic routing fixtures",
            "runtime_boundary": "threaded Werkzeug loopback server with an eight-request semaphore; one process, not Gunicorn or Railway",
            "scenario": {"concurrency_levels": args.concurrency, "iterations_per_client_per_level": args.iterations,
                         "paths": ["/", "/api/bootstrap", "/api/state", "/api/search"],
                         "booking_race_clients": max(args.concurrency), "fixture_trip_capacity_seats": 1},
            "levels": levels,
            "invariants": {"booking_race_responses": {str(status): sum(1 for code, _, _ in outcomes if code == status)
                                                      for status in sorted({code for code, _, _ in outcomes})},
                           "booking_race_statuses_valid": race_statuses_valid,
                           "accepted_bookings": len(accepted), "accepted_seats_for_trip": accepted_count,
                           "oversell": accepted_count > 1, "passenger_booking_state_isolation": passenger_isolation},
            "storage_recovery": {"database_wal_shm_bytes_before_backup": data_bytes, **recovery},
            "thresholds": {"local_fixture_http_p95_ms_below": 2000, "unexpected_5xx_or_4xx": 0,
                           "one_seat_accept_race_winners": 1, "passenger_state_cross_account_leaks": 0},
            "result": "FAIL" if failed else "PASS",
            "limitations": ["Local Python/SQLite filesystem timings do not model Railway CPU, volume latency, TLS, Singapore networking or third-party routing/SMS.",
                            "100 registered synthetic accounts are distinct from 100 simultaneous users.",
                            "No payment provider or live OTP was called; manual driver review was not simulated as a human operations workflow."],
        }
        output = report_dir / f"production-capacity-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"result": report["result"], "report": str(output),
                          "synthetic_registered_users": 100, "levels": levels,
                          "invariants": report["invariants"], "storage_recovery": report["storage_recovery"],
                          "threshold_failures": threshold_failures}, indent=2))
        return 1 if failed else 0
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        app.extensions["voice_service"].close()
        shutil.rmtree(run_dir, ignore_errors=True)


def _positive_int(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-dir", type=Path, default=Path("/tmp/seatpal-production-capacity-20261016"),
                        help="POSIX directory for the disposable SQLite database and run files")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "work" / "launch-capacity-20261016",
                        help="directory for the durable JSON report")
    parser.add_argument("--concurrency", type=_positive_int, nargs="+", default=[1, 5, 10, 20])
    parser.add_argument("--iterations", type=_positive_int, default=40,
                        help="requests per client at each level, spread across four endpoints")
    args = parser.parse_args()
    if args.concurrency != sorted(set(args.concurrency)):
        parser.error("concurrency levels must be unique and increasing")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
