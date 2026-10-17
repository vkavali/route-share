#!/usr/bin/env python3
"""Exercise real Gunicorn HTTP sessions on a disposable synthetic SQLite DB.

The configured one-worker/eight-thread Gunicorn process receives only a
loopback bind override. The app factory fixture disables all external
providers and uses synthetic identity permissions and deterministic routing.
This does not validate Railway's hosted.py /data guards or Python 3.12 image.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
BACKUP_SCRIPT = ROOT / "scripts" / "backup_store.py"
PHONE_PREFIX = "9000000"


class JourneyFailure(RuntimeError):
    pass


class HttpSession:
    """Small stdlib cookie client; each concurrent actor owns its own jar."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.cookies: dict[str, str] = {}
        self.csrf: str | None = None
        self.user_id: str | None = None

    def clone(self) -> "HttpSession":
        other = HttpSession(self.base_url)
        other.cookies = dict(self.cookies)
        other.csrf = self.csrf
        other.user_id = self.user_id
        return other

    def call(self, method: str, path: str, payload: dict | None = None,
             timeout: float = 60) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = self.base_url
            headers["Sec-Fetch-Site"] = "same-origin"
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
            if self.user_id:
                headers["X-Expected-User-ID"] = self.user_id
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            for header in response.headers.get_all("Set-Cookie", []):
                first = header.split(";", 1)[0]
                name, sep, value = first.partition("=")
                if sep:
                    self.cookies[name] = value
            raw = response.read()
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}
            if isinstance(body, dict) and isinstance(body.get("csrf_token"), str):
                self.csrf = body["csrf_token"]
            return response.status, body if isinstance(body, dict) else {}

    def expect(self, method: str, path: str, payload: dict | None = None,
               expected: int = 200, timeout: float = 60) -> dict:
        status, body = self.call(method, path, payload, timeout)
        if status != expected:
            code = body.get("code") if isinstance(body.get("code"), str) else ""
            raise JourneyFailure(f"{method} {path} returned HTTP {status}, expected {expected} ({code})")
        return body

    def get(self, path: str) -> dict:
        return self.expect("GET", path)

    def post(self, action: str, payload: dict) -> dict:
        return self.expect("POST", "/api/" + action, payload)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise JourneyFailure(message)


def signup(base_url: str, phone: str, name: str) -> HttpSession:
    session = HttpSession(base_url)
    boot = session.get("/api/bootstrap")
    require(isinstance(boot.get("csrf_token"), str), "bootstrap omitted its CSRF token")
    flow_token = secrets_token()
    started = session.post("phone/start", {
        "phone": phone,
        "flow_token": flow_token,
        "request_id": str(uuid.uuid4()),
    })
    verify = session.post("phone/verify", {
        "challenge_id": started["challenge_id"],
        "flow_token": flow_token,
        "code": "831947",
        "consent": {
            "terms_version": "2026-10-11",
            "privacy_version": "2026-10-11",
            "terms_accepted": True,
            "privacy_accepted": True,
            "adult_attested": True,
        },
    })
    session.user_id = verify["user"]["id"]
    session.post("phone/profile", {"name": name})
    account = session.get("/api/bootstrap").get("user")
    require(isinstance(account, dict) and account.get("id") == session.user_id,
            "signup/profile did not establish a persistent HTTP session")
    return session


def secrets_token() -> str:
    # Opaque synthetic flow binding; no external credentials or secrets.
    return secrets.token_urlsafe(32)


def seed_synthetic_permissions(database: Path, user_ids: list[str], driver_id: str) -> None:
    """Enable only the synthetic actor pool; this is not an approval workflow."""
    sys.path.insert(0, str(ROOT))
    from app.store import Store  # imported after the app source path is known

    now = datetime.now(timezone.utc)
    approval = {"kind": "development", "expires_at": (now + timedelta(days=30)).isoformat()}
    with Store(database).transaction() as tx:
        for user_id in user_ids:
            record = tx.get("users", user_id)
            require(isinstance(record, dict), "synthetic signup account disappeared")
            record["development"] = True
            if user_id == driver_id:
                record["driver_approved"] = True
                record["driver_approval"] = approval
            tx.put("users", user_id, record)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def clean_child_environment(port: int, database: Path, root: Path) -> dict[str, str]:
    # Intentionally do not inherit app/provider/production environment values.
    path = os.environ.get("PATH", "/usr/bin:/bin")
    return {
        "PATH": path,
        "HOME": str(database.parent),
        "PYTHONPATH": os.pathsep.join((str(root), str(root / "tests"))),
        "PYTHONUNBUFFERED": "1",
        "PORT": str(port),
        "SEATPAL_JOURNEY_DB": str(database),
    }


class Gunicorn:
    def __init__(self, database: Path, log_path: Path):
        self.database = database
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.env = clean_child_environment(self.port, database, ROOT)
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self.log_file = None

    def start(self) -> None:
        self.log_file = self.log_path.open("ab")
        self.process = subprocess.Popen([
            sys.executable, "-m", "gunicorn",
            "--config", str(ROOT / "gunicorn.conf.py"),
            "--bind", f"127.0.0.1:{self.port}",
            "gunicorn_journey_fixture:app",
        ], cwd=ROOT, env=self.env, stdout=self.log_file, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        last_error = "not ready"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise JourneyFailure(f"Gunicorn exited during startup (code {self.process.returncode})")
            try:
                session = HttpSession(self.base_url)
                session.get("/api/bootstrap")
                return
            except Exception as error:  # startup retry only; output is kept out of evidence
                last_error = type(error).__name__
                time.sleep(0.1)
        raise JourneyFailure(f"Gunicorn did not become ready ({last_error})")

    def stop(self) -> None:
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def restart(self, database: Path | None = None) -> None:
        self.stop()
        if database is not None:
            self.database = database
            self.env = clean_child_environment(self.port, database, ROOT)
        self.start()


def verify_runtime_config() -> dict:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="seatpal-gunicorn-config-") as config_text:
        config_dir = Path(config_text)
        os.chmod(config_dir, 0o700)
        env = clean_child_environment(port, config_dir / "preflight.sqlite3", ROOT)
        command = [sys.executable, "-m", "gunicorn", "--print-config",
                   "--config", str(ROOT / "gunicorn.conf.py"),
                   "--bind", f"127.0.0.1:{port}", "gunicorn_journey_fixture:app"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise JourneyFailure("Gunicorn configuration preflight failed")
    values = {}
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() in {"workers", "worker_class", "threads", "bind"}:
            values[key.strip()] = value.strip()
    expected_bind = f"127.0.0.1:{port}"
    if values.get("workers") != "1" or values.get("threads") != "8" or "gthread" not in values.get("worker_class", ""):
        raise JourneyFailure("Gunicorn config preflight mismatch: " + json.dumps({
            "fields": values, "returncode": result.returncode,
            "stdout_excerpt": result.stdout[:500], "stderr_excerpt": result.stderr[:500],
        }, sort_keys=True))
    if expected_bind not in values.get("bind", ""):
        raise JourneyFailure("Gunicorn effective bind mismatch: " + json.dumps(values, sort_keys=True))
    return values


def publish_and_search(driver: HttpSession, passenger: HttpSession, *, departure: str,
                       seats: int = 1) -> tuple[str, str]:
    from test_lifecycle import KONDAPUR, NANDIGAMA, VIJAYAWADA

    preview = driver.post("preview", {
        "origin": KONDAPUR, "destination": VIJAYAWADA, "departure": departure,
        "seats": seats, "max_detour_minutes": 15, "seat_price_paise": 125000,
        "baggage_capacity": {"small_bags": 2, "large_suitcases": 1},
    })["preview"]
    trip = driver.post("publish", {"preview_id": preview["id"]})["trip"]
    departure_dt = datetime.fromisoformat(departure)
    found = passenger.post("search", {
        "origin": NANDIGAMA, "destination": VIJAYAWADA,
        "window_start": (departure_dt - timedelta(minutes=1)).isoformat(),
        "window_end": (departure_dt + timedelta(hours=8)).isoformat(), "seats": 1,
        "baggage": {"small_bags": 1, "large_suitcases": 0},
    })
    match = next((m for m in found.get("matches", []) if m["trip_id"] == trip["id"]), None)
    require(match is not None, "deterministic synthetic route did not produce a trip match")
    require(match.get("price_quote", {}).get("amount_paise") == 125000,
            "flat seat quote was not returned by HTTP search")
    require(match.get("baggage_capacity") == {"small_bags": 2, "large_suitcases": 1},
            "published baggage capacity did not survive HTTP search")
    booking = passenger.post("request", {"match_id": match["id"]})["booking"]
    return trip["id"], booking["id"]


def run(output_path: Path, evidence: dict) -> None:
    config = verify_runtime_config()
    evidence["effective_gunicorn"] = config
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="seatpal-gunicorn-journey-") as scratch_text:
        scratch = Path(scratch_text)
        os.chmod(scratch, 0o700)
        database = scratch / "journey.sqlite3"
        process = Gunicorn(database, scratch / "gunicorn.log")
        clients: list[HttpSession] = []
        try:
            process.start()
            evidence["steps"]["empty_start"] = {"ok": True, "database_existed_before_start": False}

            owner_phone = PHONE_PREFIX + "001"
            owner = signup(process.base_url, owner_phone, "Synthetic journey driver")
            passengers = [
                signup(process.base_url, PHONE_PREFIX + f"{i:03d}", f"Synthetic passenger {i}")
                for i in range(2, 24)
            ]
            all_ids = [owner.user_id] + [client.user_id for client in passengers]
            require(all(isinstance(user_id, str) for user_id in all_ids), "synthetic signups omitted ids")
            seed_synthetic_permissions(database, all_ids, owner.user_id)
            evidence["steps"]["http_signup"] = {
                "ok": True,
                "synthetic_phone_members_registered": len(all_ids),
                "driver_and_journey_passengers": 3,
                "distinct_last_seat_contenders": 20,
            }

            departure = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0).isoformat()
            trip_id, first_booking = publish_and_search(owner, passengers[0], departure=departure, seats=1)
            replay = owner.post("accept", {"booking_id": first_booking})
            first_accept_replay = owner.post("accept", {"booking_id": first_booking})
            require(first_accept_replay["booking"]["id"] == replay["booking"]["id"],
                    "accept replay did not return the same booking")
            owner.post("start_trip", {"trip_id": trip_id})
            passengers[0].post("board_segment", {"booking_id": first_booking})
            completed = passengers[0].post("complete_segment", {"booking_id": first_booking})
            trip_completed = owner.post("complete_trip", {"trip_id": trip_id})
            require(completed["booking"]["status"] == "segment_completed", "booking segment did not complete")
            require(trip_completed["trip"]["status"] == "completed", "trip did not complete")
            evidence["steps"]["complete_booking_and_replay"] = {
                "ok": True,
                "booking_status": completed["booking"]["status"],
                "trip_status": trip_completed["trip"]["status"],
                "accept_replay_same_booking": True,
            }

            cancel_departure = (datetime.now(timezone.utc) + timedelta(days=6)).replace(microsecond=0).isoformat()
            cancel_trip_id, cancel_booking = publish_and_search(owner, passengers[1], departure=cancel_departure)
            owner.post("accept", {"booking_id": cancel_booking})
            cancelled = passengers[1].post("cancel_booking", {
                "booking_id": cancel_booking, "reason": "Synthetic pre-start cancellation check",
            })["booking"]
            require(cancelled["status"] == "cancelled", "accepted pre-start booking did not cancel")
            state_after_cancel = owner.get("/api/state")
            cancel_trip_row = next((row for row in state_after_cancel.get("trips", [])
                                    if row.get("id") == cancel_trip_id), None)
            require(isinstance(cancel_trip_row, dict) and cancel_trip_row.get("status") == "published",
                    "pre-start passenger cancellation unexpectedly ended the trip")
            evidence["steps"]["prestart_cancellation"] = {
                "ok": True, "booking_status": cancelled["status"], "trip_remains_published": True,
            }
            from app.store import Store
            with Store(database).transaction() as tx:
                cancelled_persisted = tx.get("bookings", cancel_booking)
                cancelled_trip_persisted = tx.get("trips", cancel_trip_id)
                cancel_bookings = [row for row in tx.list("bookings") if row.get("trip_id") == cancel_trip_id]
            from app.matching import available_capacity
            require(isinstance(cancelled_persisted, dict)
                    and cancelled_persisted.get("status") == "cancelled",
                    "cancelled booking did not persist in SQLite")
            require(isinstance(cancelled_trip_persisted, dict)
                    and available_capacity(cancelled_trip_persisted, cancel_bookings,
                                           cancelled_persisted["start_m"], cancelled_persisted["end_m"]) == 1,
                    "cancellation did not restore one seat")
            evidence["steps"]["prestart_cancellation"].update({
                "cancelled_booking_persisted": True, "available_seats_after_cancel": 1,
            })

            race_departure = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat()
            race_preview = owner.post("preview", {
                "origin": {"label": "Kondapur", "lat": 17.460, "lon": 78.357},
                "destination": {"label": "Vijayawada", "lat": 16.506, "lon": 80.648},
                "departure": race_departure, "seats": 1, "max_detour_minutes": 15,
                "seat_price_paise": 125000,
                "baggage_capacity": {"small_bags": 2, "large_suitcases": 1},
            })["preview"]
            race_trip = owner.post("publish", {"preview_id": race_preview["id"]})["trip"]
            race_dt = datetime.fromisoformat(race_departure)

            def request_booking(client: HttpSession) -> str:
                from test_lifecycle import NANDIGAMA, VIJAYAWADA
                result = client.post("search", {
                    "origin": NANDIGAMA, "destination": VIJAYAWADA,
                    "window_start": (race_dt - timedelta(minutes=1)).isoformat(),
                    "window_end": (race_dt + timedelta(hours=8)).isoformat(), "seats": 1,
                })
                match = next((m for m in result.get("matches", []) if m["trip_id"] == race_trip["id"]), None)
                require(match is not None, "contender did not receive the synthetic trip match")
                return client.post("request", {"match_id": match["id"],
                    "baggage": {"small_bags": 1, "large_suitcases": 0}})["booking"]["id"]

            candidate_clients = passengers[2:]
            require(len(candidate_clients) == 20, "last-seat burst must use twenty distinct registered passengers")
            with ThreadPoolExecutor(max_workers=20) as pool:
                booking_ids = list(pool.map(request_booking, candidate_clients))
            owner_clones = [owner.clone() for _ in booking_ids]

            def accept_one(item: tuple[HttpSession, str]) -> tuple[int, dict]:
                client, booking_id = item
                return client.call("POST", "/api/accept", {"booking_id": booking_id}, timeout=90)

            with ThreadPoolExecutor(max_workers=20) as pool:
                statuses = list(pool.map(accept_one, zip(owner_clones, booking_ids)))
            status_codes = [status for status, _body in statuses]
            require(status_codes.count(200) == 1, f"last-seat HTTP contention accepted {status_codes.count(200)} bookings")
            require(status_codes.count(409) == len(status_codes) - 1,
                    f"last-seat HTTP contention returned unexpected status counts: {status_codes.count(409)} conflicts")
            accepted_booking_id = next(booking_id for booking_id, (status, _body) in zip(booking_ids, statuses)
                                       if status == 200)
            with Store(database).transaction() as tx:
                persisted_race_trip = tx.get("trips", race_trip["id"])
                persisted_race_bookings = [tx.get("bookings", booking_id) for booking_id in booking_ids]
                race_all_bookings = [row for row in tx.list("bookings") if row.get("trip_id") == race_trip["id"]]
            from app.matching import available_capacity
            accepted_rows = [row for row in persisted_race_bookings
                             if isinstance(row, dict) and row.get("status") == "accepted"]
            require(len(accepted_rows) == 1 and accepted_rows[0].get("id") == accepted_booking_id,
                    "SQLite does not contain exactly the winning accepted booking")
            require(isinstance(persisted_race_trip, dict)
                    and available_capacity(persisted_race_trip, race_all_bookings,
                                           accepted_rows[0]["start_m"], accepted_rows[0]["end_m"]) == 0,
                    "SQLite race trip inventory is not zero after the winning acceptance")
            evidence["steps"]["last_seat_contention"] = {
                "ok": True, "registered_synthetic_members": len(all_ids),
                "contenders": len(status_codes), "accepted": status_codes.count(200),
                "conflicts": status_codes.count(409), "persisted_accepted_bookings": len(accepted_rows),
                "available_seats_after_race": 0,
            }

            # Keep real sessions alive across a graceful process stop/start.
            process.stop()
            process.restart()
            boot_after_restart = owner.get("/api/bootstrap").get("user")
            state_after_restart = owner.get("/api/state")
            require(isinstance(boot_after_restart, dict) and boot_after_restart.get("id") == owner.user_id,
                    "owner cookie session did not survive Gunicorn restart")
            require(any(row.get("id") == trip_id and row.get("status") == "completed"
                        for row in state_after_restart.get("trips", [])),
                    "completed trip did not survive Gunicorn restart")
            with Store(database).transaction() as tx:
                restart_cancelled = tx.get("bookings", cancel_booking)
            require(isinstance(restart_cancelled, dict) and restart_cancelled.get("status") == "cancelled",
                    "cancelled booking did not survive Gunicorn restart")
            evidence["steps"]["process_restart_persistence"] = {
                "ok": True, "session_survived": True, "completed_trip_survived": True,
                "cancelled_booking_survived": True,
            }

            backup_dir = scratch / "backup"
            restored_db = scratch / "restored.sqlite3"
            backup_result = subprocess.run([
                sys.executable, str(BACKUP_SCRIPT), "backup", "--database", str(database),
                "--output", str(backup_dir),
            ], cwd=ROOT, env=clean_child_environment(process.port, database, ROOT),
                capture_output=True, text=True, timeout=90)
            if backup_result.returncode:
                raise JourneyFailure("isolated online SQLite backup command failed")
            restore_result = subprocess.run([
                sys.executable, str(BACKUP_SCRIPT), "restore", "--backup", str(backup_dir),
                "--destination", str(restored_db),
            ], cwd=ROOT, env=clean_child_environment(process.port, restored_db, ROOT),
                capture_output=True, text=True, timeout=90)
            if restore_result.returncode:
                raise JourneyFailure("isolated SQLite restore command failed")
            restore_payload = json.loads(restore_result.stdout)
            require(restore_payload.get("restored") is True, "restore command did not confirm completion")
            process.restart(restored_db)
            restored_state = owner.get("/api/state")
            require(any(row.get("id") == trip_id and row.get("status") == "completed"
                        for row in restored_state.get("trips", [])),
                    "completed trip did not survive isolated restore")
            require(any(row.get("id") == cancel_booking and row.get("status") == "cancelled"
                        for row in restored_state.get("bookings", [])),
                    "cancelled booking did not survive isolated restore")
            with Store(restored_db).transaction() as tx:
                restored_winner = tx.get("bookings", accepted_booking_id)
                restored_complete_booking = tx.get("bookings", first_booking)
                restored_race_trip = tx.get("trips", race_trip["id"])
                restored_complete_trip = tx.get("trips", trip_id)
                restored_cancelled = tx.get("bookings", cancel_booking)
                restored_bookings = [row for row in tx.list("bookings") if row.get("trip_id") == race_trip["id"]]
            from app.matching import available_capacity
            require(isinstance(restored_winner, dict) and restored_winner.get("status") == "accepted",
                    "winning accepted booking did not survive restore")
            require(isinstance(restored_complete_booking, dict)
                    and restored_complete_booking.get("status") == "segment_completed"
                    and restored_complete_booking.get("price_quote", {}).get("amount_paise") == 125000
                    and restored_complete_booking.get("baggage") == {"small_bags": 1, "large_suitcases": 0},
                    "completed booking quote, baggage, or status did not survive restore")
            require(isinstance(restored_race_trip, dict)
                    and available_capacity(restored_race_trip, restored_bookings,
                                           restored_winner["start_m"], restored_winner["end_m"]) == 0,
                    "race inventory did not survive restore")
            require(isinstance(restored_cancelled, dict) and restored_cancelled.get("status") == "cancelled",
                    "cancelled booking record did not survive restore")
            require(isinstance(restored_complete_trip, dict)
                    and restored_complete_trip.get("seat_price_paise") == 125000
                    and restored_complete_trip.get("baggage_capacity") == {"small_bags": 2, "large_suitcases": 1},
                    "flat quote or baggage capacity did not survive restore")
            with sqlite3.connect(restored_db) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                require(integrity == "ok", "restored SQLite integrity check failed")
                document_count = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
            evidence["steps"]["online_backup_restore"] = {
                "ok": True, "integrity": integrity,
                "restored_document_count": document_count,
                "restored_completed_trip": True,
                "restored_completed_booking": True,
                "restored_completed_booking_quote_paise": 125000,
                "restored_completed_booking_baggage": {"small_bags": 1, "large_suitcases": 0},
                "restored_cancelled_booking": True,
                "restored_winning_booking": True,
                "restored_last_seat_inventory": 0,
                "restored_flat_quote_paise": 125000,
                "restored_baggage_capacity": {"small_bags": 2, "large_suitcases": 1},
                "restore_process_http_read": True,
            }
        finally:
            process.stop()
            saved_log = output_path.with_suffix(output_path.suffix + ".gunicorn.log")
            if process.log_path.exists():
                shutil.copyfile(process.log_path, saved_log)
                os.chmod(saved_log, 0o600)
                evidence["gunicorn_log"] = str(saved_log)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="sanitized JSON evidence destination outside the repository")
    args = parser.parse_args()
    evidence = {
        "format": 1,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "scope": "synthetic HTTP journey through actual Gunicorn process; no hosted provider or financial settlement",
        "steps": {},
    }
    try:
        evidence.update({
            "format": 1,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "scope": "synthetic HTTP journey through actual Gunicorn process; no hosted provider or financial settlement",
            "limitations": [
                "App factory fixture bypasses hosted.py /data and HTTPS deployment guards.",
                "Synthetic development permissions are seeded directly; no identity or driver document review is replayed.",
                "UPI, payment reporting, bank settlement, SMS, email, voice, and live road routing are not exercised.",
                "This Linux venv uses Python 3.10.12; the pinned Docker runtime uses Python 3.12.12.",
            ],
        })
        run(args.output, evidence)
        evidence["result"] = "passed"
        return_code = 0
    except Exception as error:
        evidence["result"] = "failed"
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)[:240]}
        evidence.setdefault("limitations", []).append("Execution stopped at the first failed check.")
        return_code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"result": evidence["result"], "evidence": str(args.output),
                      "completed_steps": [key for key, value in evidence.get("steps", {}).items()
                                          if value.get("ok") is True]}, indent=2))
    if return_code:
        print(json.dumps(evidence.get("failure", {}), indent=2), file=sys.stderr)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
