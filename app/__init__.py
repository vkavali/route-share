"""Flask API for the supervised local route-sharing beta."""

from __future__ import annotations

import hmac
import json
import math
import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, session
from flask.json.provider import DefaultJSONProvider
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from .community import CommunityError
from .geocoding import GeocodingError, NominatimGeocoder
from .live_location import LiveLocationError, LiveLocationStore, distance_m
from .mobile_auth import MobileAuthError, MobileAuthenticator
from .providers import public_flags
from .permissions import access_summary
from .location_policy import sharing_window
from .trusted_contacts import TrustedContactService, TrustedContactError
from .store import Store

MAX_JSON_BYTES = 16 * 1024
ACCOUNT_NAMES = {
    "driver": ("Development driver", "member"),
    "passenger": ("Development passenger", "member"),
    "passenger2": ("Development passenger 2", "member"),
    "admin": ("Development staff", "staff"),
}
POST_REQUIRED = {
    "preview": ("origin", "destination", "departure", "seats", "max_detour_minutes"),
    "publish": ("preview_id",),
    "search": ("origin", "destination", "window_start", "window_end", "seats"),
    "request": ("match_id",),
    "accept": ("booking_id",),
    "decline": ("booking_id",),
    "cancel_booking": ("booking_id", "reason"),
    "start_trip": ("trip_id",),
    "complete_segment": ("booking_id",),
    "board_segment": ("booking_id",),
    "complete_trip": ("trip_id",),
    "cancel_trip": ("trip_id", "reason"),
    "rate": ("booking_id", "stars"),
    "report_safety": ("booking_id", "category", "details", "idempotency_key"),
    "block_person": ("booking_id",),
    "resolve_report": ("report_id", "resolution"),
    "update_profile": ("name", "share_phone"),
    "contact": ("booking_id",),
    "send_message": ("booking_id", "text", "client_message_id"),
    "mark_chat_read": ("booking_id", "upto_message_id"),
    "mark_notification_read": ("notification_id",),
}


def _persistent_secret(path: Path) -> str:
    """Load or create a stable local signing key without replacing an existing one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(48)
        descriptor = None
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_text(encoding="utf-8").strip()
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise
        return value


def _safe(value: Any) -> Any:
    """Strip credentials recursively from every object returned by the API."""
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key not in {"password_hash", "password", "contribution_inr", "contribution_note"}}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite numbers are not valid API data")
    return value


class StrictJSONProvider(DefaultJSONProvider):
    def dumps(self, obj: Any, **kwargs: Any) -> str:
        kwargs["allow_nan"] = False
        return super().dumps(obj, **kwargs)


def _safe_user(record: dict[str, Any]) -> dict[str, Any]:
    return {**_safe({key: value for key, value in record.items() if key != "password_hash"}), "access": access_summary(record)}


def _seed_users(store: Store, password: str, *, passwords: dict[str, str] | None = None, development: bool = True) -> None:
    defaults = {"vehicle": {"model": "", "plate": ""}, "verification": {
        "phone": "not_checked", "identity": "not_checked", "dl": "not_checked",
        "rc": "not_checked", "selfie": "not_checked",
    }, "development": True, "phone": ""}
    with store.transaction() as tx:
        for account, (name, role) in ACCOUNT_NAMES.items():
            record = tx.get("users", account) or {"id": account, **defaults}
            record.setdefault("name", name)
            record.setdefault("phone", "")
            record.setdefault("share_phone", False)
            record.setdefault("verification", dict(defaults["verification"]))
            # One-time permission migration: restarting must not restore revoked grants.
            if record.get("permission_schema") != 1:
                record.update(role=role, driver_approved=(account == "driver"), permission_schema=1)
                record["staff_capabilities"] = ["ops.read", "verify.review", "safety.act", "staff.manage"] if account == "admin" else []
                if account == "driver":
                    record["driver_approval"] = {"kind": "development", "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), "note": "Test permission only; licence and RC have not been verified."}
            record.update({
                "password_hash": generate_password_hash(passwords[account] if passwords else password),
                "development": development,
            })
            tx.put("users", account, record)


def _hosted_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _hosted_passwords(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("BETA_ACCOUNT_PASSWORDS must be a JSON object.") from exc
    if not isinstance(value, dict) or set(value) != set(ACCOUNT_NAMES):
        raise ValueError("BETA_ACCOUNT_PASSWORDS must define exactly driver, passenger, passenger2 and admin.")
    passwords = list(value.values())
    if any(not isinstance(password, str) or not 24 <= len(password) <= 1024 or password == "local-beta-only" for password in passwords):
        raise ValueError("Each hosted account password must be 24 to 1024 characters and must not use the local default.")
    if len({password.casefold() for password in passwords}) != len(passwords):
        raise ValueError("Hosted account passwords must be distinct.")
    return value


def _canonical_public_origin(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("PUBLIC_ORIGIN must be a canonical HTTPS origin.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("PUBLIC_ORIGIN must be a canonical HTTPS origin.") from exc
    hostname = parsed.hostname
    if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or hostname != hostname.lower()
            or port == 443):
        raise ValueError("PUBLIC_ORIGIN must be a canonical HTTPS origin without path, query, credentials or default port.")
    hostpart = f"[{hostname}]" if ":" in hostname else hostname
    canonical = f"https://{hostpart}" + (f":{port}" if port else "")
    if value != canonical:
        raise ValueError("PUBLIC_ORIGIN must be a canonical HTTPS origin without a trailing slash.")
    return canonical


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static", static_url_path="/static")
    app.json = StrictJSONProvider(app)
    app.config.update(
        SECRET_KEY=None,
        DATABASE_PATH=os.environ.get("BETA_DATABASE", "work/beta.sqlite3"),
        SECRET_PATH=os.environ.get("BETA_SECRET_FILE"),
        BETA_PASSWORD=os.environ.get("BETA_PASSWORD", "local-beta-only"),
        HOSTED_MODE=_hosted_enabled(os.environ.get("ROUTE_SHARE_HOSTED", "0")),
        PUBLIC_ORIGIN=os.environ.get("PUBLIC_ORIGIN"),
        BETA_ACCOUNT_PASSWORDS=os.environ.get("BETA_ACCOUNT_PASSWORDS"),
        MAX_CONTENT_LENGTH=MAX_JSON_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
        DEVELOPMENT_MODE=True,
        TESTING=False,
        NOMINATIM_BASE_URL=os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org/search"),
    )
    if config:
        app.config.update(config)
    hosted_mode = _hosted_enabled(app.config["HOSTED_MODE"])
    app.config["HOSTED_MODE"] = hosted_mode
    if hosted_mode:
        app.config["PUBLIC_ORIGIN"] = _canonical_public_origin(app.config.get("PUBLIC_ORIGIN"))
        account_passwords = _hosted_passwords(app.config.get("BETA_ACCOUNT_PASSWORDS"))
        app.config.update(
            DEVELOPMENT_MODE=False,
            SESSION_COOKIE_SECURE=True,
            PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
        )
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    else:
        account_passwords = None
    secret_path = app.config.get("SECRET_PATH") or str(Path(app.config["DATABASE_PATH"]).with_name(".flask-secret"))
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or _persistent_secret(Path(secret_path))
    store = Store(app.config["DATABASE_PATH"])
    # These four seeded identities remain development/test accounts in every
    # deployment; hosted access does not imply verified real-world identity.
    _seed_users(store, str(app.config["BETA_PASSWORD"]), passwords=account_passwords, development=True)
    app.extensions["beta_store"] = store
    live_locations = LiveLocationStore(auto_expire=not app.config["TESTING"])
    app.extensions["live_location_store"] = live_locations
    trusted_contacts = TrustedContactService(store, app.config["SECRET_KEY"])
    app.extensions["trusted_contact_service"] = trusted_contacts
    mobile_auth = MobileAuthenticator(store)
    app.extensions["mobile_auth"] = mobile_auth
    geocoder = NominatimGeocoder(app.config["NOMINATIM_BASE_URL"])
    app.extensions["geocoder"] = geocoder

    # Imports are delayed until app construction so the API can be imported while
    # the domain module is being assembled by the rest of the beta implementation.
    from .domain import DomainError, Service
    from .routing import OSRMProvider

    service = Service(store, OSRMProvider(store=store))
    app.extensions["beta_service"] = service

    def error(message: str, status: int):
        return jsonify({"error": message}), status

    def authenticated_user() -> dict[str, Any] | None:
        bearer_user = getattr(g, "mobile_user", None)
        if bearer_user is not None:
            return _safe_user(bearer_user)
        account = session.get("account")
        if not account:
            return None
        with store.read() as tx:
            record = tx.get("users", account)
        return _safe_user(record) if record else None

    @app.before_request
    def enforce_request_limits_and_csrf():
        host_header = request.host.casefold()
        healthcheck_request = request.path == "/api/health" and request.method == "GET"
        if app.config["HOSTED_MODE"]:
            public_netloc = urlsplit(app.config["PUBLIC_ORIGIN"]).netloc.casefold()
            railway_health_host = healthcheck_request and host_header == "healthcheck.railway.app"
            if host_header != public_netloc and not railway_health_host:
                return error("This hosted beta only accepts its configured public host", 400)
            if not request.is_secure and not healthcheck_request:
                return error("HTTPS is required", 400)
        else:
            host = urlsplit("//" + request.host).hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                return error("This development server only accepts loopback hosts", 400)
        if request.content_length is not None and request.content_length > MAX_JSON_BYTES:
            return error("Request body is too large", 413)
        authorization = request.headers.get("Authorization")
        if authorization is not None:
            scheme, _, token = authorization.partition(" ")
            if scheme.casefold() != "bearer" or not token.strip():
                return jsonify({"error": "Invalid mobile bearer token.", "code": "invalid_token"}), 401
            auth = mobile_auth.authenticate(token.strip())
            if not auth:
                return jsonify({"error": "Mobile session expired or revoked. Sign in again.", "code": "invalid_token"}), 401
            g.mobile_user = auth["user"]
            g.mobile_token_hash = auth["token_hash"]
            g.mobile_auth_lock = auth["lock"]
        if request.path not in {"/api/login", "/api/mobile/login", "/api/bootstrap"}:
            expected_user_id = request.headers.get("X-Expected-User-ID")
            if expected_user_id is not None:
                active_user = authenticated_user()
                if (not isinstance(expected_user_id, str) or not expected_user_id
                        or len(expected_user_id) > 128 or not active_user
                        or active_user.get("id") != expected_user_id):
                    return jsonify({"error": "Account changed. Refresh and try again.", "code": "account_changed"}), 409
        if request.path == "/api/mobile/login" and request.method == "POST":
            return None
        if request.method != "POST":
            return None
        if getattr(g, "mobile_user", None) is not None:
            return None
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        source = origin or referer
        if not source:
            return error("Same-origin request required", 403)
        parsed = urlsplit(source)
        expected = urlsplit(app.config["PUBLIC_ORIGIN"] if app.config["HOSTED_MODE"] else request.host_url)
        malformed_origin = bool(origin and (parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password))
        if malformed_origin or (parsed.scheme, parsed.netloc.lower()) != (expected.scheme, expected.netloc.lower()):
            return error("Same-origin request required", 403)
        if request.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}:
            return error("Same-origin request required", 403)
        token = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(str(token), supplied):
            return error("Invalid CSRF token", 403)
        return None

    @app.teardown_request
    def release_mobile_auth_lock(_exc):
        lock = getattr(g, "mobile_auth_lock", None)
        if lock is not None:
            lock.release()

    def json_body() -> dict[str, Any] | tuple[Any, int]:
        if not request.is_json:
            return error("Content-Type must be application/json", 415)
        try:
            body = json.loads(request.get_data(cache=True), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return error("Request body must be valid JSON", 400)
        if not isinstance(body, dict):
            return error("Request body must be a JSON object", 400)
        return body

    def dispatch(action: str, user: dict[str, Any], body: dict[str, Any]):
        required = POST_REQUIRED.get(action, ())
        missing = [field for field in required if field not in body]
        if missing:
            return error(f"Missing required field: {missing[0]}", 400)
        result = service.dispatch(action, user, body)
        cleanup_live_locations()
        if action == "board_segment":
            booking = result.get("booking", {})
            live_locations.restrict_actor(booking.get("id", ""), user["id"], allowed=True, consent_phase="onboard")
        return jsonify(_safe(result))

    def cleanup_live_locations() -> None:
        with store.read() as tx:
            trips = {trip["id"]: trip for trip in tx.list("trips")}
            active = {
                booking["id"] for booking in tx.list("bookings")
                if booking.get("status") == "accepted"
                and (trip := trips.get(booking.get("trip_id"))) is not None
                and trip.get("status") in {"published", "started"}
                and not booking.get("live_location_ended_reason")
            }
        live_locations.purge_except(active)

    def route_segment(booking: dict, trip: dict):
        """Return a committed road-line segment only when both snapped endpoints fit."""
        full = trip.get("current_route") or trip.get("route") or {}
        coords = full.get("coordinates") or []
        match = booking.get("match") or {}
        start, end = match.get("routed_pickup"), match.get("routed_dropoff")
        if not start or not end or len(coords) < 2:
            return None
        def nearest(point):
            best = min(range(len(coords)), key=lambda i: distance_m(point, {"lat": coords[i][1], "lon": coords[i][0]}))
            return best if distance_m(point, {"lat": coords[best][1], "lon": coords[best][0]}) <= 500 else None
        first, last = nearest(start), nearest(end)
        if first is None or last is None or first >= last:
            return None
        return {"coordinates": coords[first:last + 1], "provider": full.get("provider")}

    @app.errorhandler(LiveLocationError)
    def handle_live_location_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(GeocodingError)
    def handle_geocoding_error(exc):
        return error(str(exc), 503)

    @app.errorhandler(MobileAuthError)
    def handle_mobile_auth_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(CommunityError)
    def handle_community_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(DomainError)
    def handle_domain_error(exc):
        return error(str(getattr(exc, "message", exc)), int(getattr(exc, "status", 400)))

    @app.errorhandler(413)
    def too_large(_exc):
        return error("Request body is too large", 413)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return error(exc.description if exc.code and exc.code < 500 else "Request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        if app.testing:
            raise exc
        app.logger.exception("Unhandled API error")
        return error("Internal server error", 500)

    @app.after_request
    def harden_response(response):
        response.headers["Cache-Control"] = "no-store"
        # ETag + no-store is contradictory: a browser that retained a stale ETag
        # can get a 304 and serve outdated CSS. Strip validators so revalidation
        # is never attempted against a no-store response.
        response.headers.pop("ETag", None)
        response.headers.pop("Last-Modified", None)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org https://tile.openstreetmap.org https://*.tile.openstreetmap.org; connect-src 'self' https://tiles.openfreemap.org; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        if app.config["HOSTED_MODE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        # Touch SQLite so the platform probe checks availability without
        # returning user data, record counts or deployment configuration.
        with store.read() as tx:
            tx.list("health_probe")
        return jsonify({"status": "ok", "mode": "hosted_beta" if hosted_mode else "local_development"})

    @app.get("/api/bootstrap")
    def bootstrap():
        mobile_user = getattr(g, "mobile_user", None)
        token = None if mobile_user is not None else session.setdefault("csrf_token", secrets.token_urlsafe(32))
        user = _safe_user(mobile_user) if mobile_user is not None else authenticated_user()
        payload: dict[str, Any] = {
            "user": user, "csrf_token": token, "flags": public_flags(),
            "mode": "hosted_beta" if hosted_mode else "local_development",
        }
        try:
            extra = service.dispatch("bootstrap", user, {})
            if isinstance(extra, dict):
                payload.update(_safe(extra))
                payload["user"] = user
                payload["csrf_token"] = token
                payload["flags"] = public_flags()
                payload["mode"] = "hosted_beta" if hosted_mode else "local_development"
        except DomainError:
            pass
        return jsonify(_safe(payload))

    @app.post("/api/mobile/login")
    def mobile_login():
        body = json_body()
        if not isinstance(body, dict):
            return body
        result = mobile_auth.login(body.get("account"), body.get("password"), request.remote_addr or "unknown")
        result["user"] = _safe_user(result["user"])
        return jsonify(result)

    @app.post("/api/mobile/logout")
    def mobile_logout():
        user = authenticated_user()
        token_hash = getattr(g, "mobile_token_hash", None)
        if user is None or token_hash is None:
            return jsonify({"error": "Mobile bearer authentication is required.", "code": "invalid_token"}), 401
        body = json_body()
        if not isinstance(body, dict):
            return body
        mobile_auth.revoke(token_hash)
        live_locations.stop_actor(user["id"])
        return jsonify({"ok": True})

    @app.get("/api/places")
    def places():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        query = request.args.get("q", "").strip()
        language = request.args.get("lang", "en")
        if not 3 <= len(query) <= 160:
            return error("Enter a place name between 3 and 160 characters.", 400)
        if re.fullmatch(r"\s*[+-]?\d+(?:\.\d+)?\s*[,;]\s*[+-]?\d+(?:\.\d+)?\s*", query):
            return jsonify({"error": "Choose the point on the map.", "code": "coordinates_not_searchable"}), 400
        if language not in {"en", "te", "hi"}:
            return error("Language must be en, te, or hi.", 400)
        return jsonify({"places": app.extensions["geocoder"].search(query, language)})

    def live_request_body():
        user = authenticated_user()
        if not user:
            return None, error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return None, body
        booking_id = body.get("booking_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            return None, error("A valid booking_id is required.", 400)
        return (user, body, booking_id), None

    def numeric_location(body):
        values = [body.get("lat"), body.get("lon"), body.get("accuracy")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            return None
        lat, lon, accuracy = map(float, values)
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 <= accuracy <= 10000:
            return None
        return lat, lon, accuracy

    def enforce_location_window(tx, booking, trip, actor_id, *, require_start=False):
        pair = {booking["driver_id"], booking["passenger_id"]}
        if any({b.get("blocker_id"), b.get("blocked_id")} == pair for b in tx.list("blocks")):
            live_locations.revoke_booking(booking["id"])
            raise LiveLocationError("Sharing is blocked for this booking.", 403, "blocked")
        windows = {pid: sharing_window(booking, trip, pid) for pid in pair}
        for pid, window in windows.items():
            live_locations.restrict_actor(booking["id"], pid, allowed=window["start_allowed"], consent_phase=window["consent_phase"])
        window = windows[actor_id]
        if window["expired"]:
            live_locations.revoke_booking(booking["id"])
            raise LiveLocationError("Location sharing has expired for this journey.", 409, "journey_ended")
        if require_start and not window["start_allowed"]:
            raise LiveLocationError("Location sharing opens shortly before your pickup.", 409, "sharing_not_started")
        return window

    @app.errorhandler(TrustedContactError)
    def handle_trusted_contact_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.get("/trip-share")
    def shared_trip_page():
        return app.send_static_file("trip-share.html")

    @app.post("/api/shared_trip")
    def read_shared_trip():
        body = json_body()
        if not isinstance(body, dict):
            return body
        return jsonify(trusted_contacts.read_snapshot(body.get("token")))

    @app.post("/api/create_trip_link")
    def create_trip_link():
        user = authenticated_user()
        if not user or user.get("role") != "member":
            return error("Member access required", 403)
        body = json_body()
        if not isinstance(body, dict):
            return body
        result = trusted_contacts.create_snapshot_link(user, body)
        origin = app.config["PUBLIC_ORIGIN"] if hosted_mode else request.host_url.rstrip("/")
        result["url"] = origin + "/trip-share#" + result.pop("token")
        return jsonify(result)

    @app.post("/api/revoke_trip_link")
    def revoke_trip_link():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return body
        return jsonify(trusted_contacts.revoke_link(user, body))

    @app.get("/api/live_location")
    def get_live_location():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        booking_id = request.args.get("booking_id", "")
        if not booking_id or len(booking_id) > 128:
            return error("A valid booking_id is required.", 400)
        with store.transaction() as tx:
            booking = tx.get("bookings", booking_id)
            if not booking or user["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
                raise LiveLocationError("Location sharing is only available to booking participants.", 403, "not_participant")
            trip = tx.get("trips", booking.get("trip_id"))
            if not trip or booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
                live_locations.revoke_booking(booking_id)
                raise LiveLocationError("Location sharing is available only for an accepted, active journey.", 409, "journey_ended")
            window = enforce_location_window(tx, booking, trip, user["id"])
            if booking.get("live_location_ended_reason"):
                result = live_locations.snapshot(booking_id, user["id"], {}, ended_reason=booking["live_location_ended_reason"])
            else:
                participants = {}
                for participant_id in (booking["driver_id"], booking["passenger_id"]):
                    participant = tx.get("users", participant_id)
                    if participant:
                        participants[participant_id] = participant.get("name", "Participant")
                result = live_locations.snapshot(booking_id, user["id"], participants)
            match = booking.get("match") or {}
            result.update({**window, "recipient_name": participants.get(window["recipient_id"], "") if not booking.get("live_location_ended_reason") else "",
                "pickup": match.get("routed_pickup") or booking.get("pickup"),
                "dropoff": match.get("routed_dropoff") or booking.get("dropoff"),
                "route": route_segment(booking, trip),
            })
            return jsonify(_safe(result))

    @app.post("/api/start_sharing")
    def start_sharing():
        parsed, failure = live_request_body()
        if failure:
            return failure
        user, _body, booking_id = parsed
        with store.transaction() as tx:
            booking = tx.get("bookings", booking_id)
            if not booking or user["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
                raise LiveLocationError("Location sharing is only available to booking participants.", 403, "not_participant")
            trip = tx.get("trips", booking.get("trip_id"))
            if not trip or booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
                live_locations.revoke_booking(booking_id)
                raise LiveLocationError("Location sharing is available only for an accepted, active journey.", 409, "journey_ended")
            if booking.get("live_location_ended_reason"):
                reason = str(booking["live_location_ended_reason"])
                raise LiveLocationError("Sharing has ended for this booking.", 409, reason)
            window = enforce_location_window(tx, booking, trip, user["id"], require_start=True)
            return jsonify({**live_locations.start(booking_id, user["id"], consent_phase=window["consent_phase"]), **window})

    @app.post("/api/share_location")
    def share_location():
        parsed, failure = live_request_body()
        if failure:
            return failure
        user, body, booking_id = parsed
        sharing_id = body.get("sharing_id")
        if not isinstance(sharing_id, str) or not sharing_id or len(sharing_id) > 256:
            raise LiveLocationError("Sharing session expired or stopped. Start sharing again to continue.", code="sharing_expired")
        location = numeric_location(body)
        if location is None:
            return error("Location must include valid finite coordinates and accuracy.", 400)
        lat, lon, accuracy = location
        with store.transaction() as tx:
            booking = tx.get("bookings", booking_id)
            if not booking or user["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
                raise LiveLocationError("Location sharing is only available to booking participants.", 403, "not_participant")
            trip = tx.get("trips", booking.get("trip_id"))
            if not trip or booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
                live_locations.revoke_booking(booking_id)
                raise LiveLocationError("Location sharing is available only for an accepted, active journey.", 409, "journey_ended")
            if booking.get("live_location_ended_reason"):
                if not live_locations.is_known_sharing_id(booking_id, user["id"], sharing_id):
                    raise LiveLocationError("Sharing session expired or stopped. Start sharing again to continue.", code="sharing_expired")
                live_locations.revoke_booking(booking_id)
                return jsonify({"ok": True, "sharing_allowed": False, "stopped_reason": booking["live_location_ended_reason"]})
            # Keep the DB transaction open while taking the location lock. This
            # serializes arrival with booking/trip completion without storing GPS.
            window = enforce_location_window(tx, booking, trip, user["id"], require_start=True)
            live_locations.require_lease(booking_id, user["id"], sharing_id, consent_phase=window["consent_phase"])
            if accuracy <= 200:
                match = booking.get("match") or {}
                dropoff = match.get("routed_dropoff") or booking.get("dropoff")
                if dropoff and distance_m({"lat": lat, "lon": lon}, dropoff) <= 150 + accuracy:
                    booking["live_location_ended_at"] = datetime.now(timezone.utc).isoformat()
                    booking["live_location_ended_reason"] = "arrival"
                    tx.put("bookings", booking_id, booking)
                    live_locations.revoke_booking(booking_id)
                    return jsonify({"ok": True, "sharing_allowed": False, "stopped_reason": "arrival"})
            result = live_locations.update(booking_id, user["id"], sharing_id, lat=lat, lon=lon, accuracy=accuracy,
                                           updated_at=datetime.now(timezone.utc).isoformat())
            return jsonify(result)

    @app.post("/api/stop_sharing")
    def stop_sharing():
        parsed, failure = live_request_body()
        if failure:
            return failure
        user, body, booking_id = parsed
        sharing_id = body.get("sharing_id")
        if not isinstance(sharing_id, str) or not sharing_id or len(sharing_id) > 256:
            raise LiveLocationError("Sharing session expired or stopped. Start sharing again to continue.", code="sharing_expired")
        with store.transaction() as tx:
            booking = tx.get("bookings", booking_id)
            if not booking or user["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
                raise LiveLocationError("Location sharing is only available to booking participants.", 403, "not_participant")
            live_locations.stop(booking_id, user["id"], sharing_id)
            return jsonify({"ok": True, "sharing_allowed": False})

    @app.post("/api/login")
    def login():
        body = json_body()
        if not isinstance(body, dict):
            return body
        account, password = body.get("account"), body.get("password")
        if not isinstance(account, str) or not isinstance(password, str):
            return error("Account and password are required", 400)
        try:
            record = mobile_auth.verify_credentials(account, password, request.remote_addr or "unknown")
        except MobileAuthError as exc:
            if exc.status == 429:
                return jsonify({"error": str(exc), "code": exc.code}), exc.status
            return error("Account and password are required", 400)
        if not record:
            return error("Invalid account or password", 401)
        csrf_token = session.get("csrf_token")
        session.clear()
        if csrf_token:
            session["csrf_token"] = csrf_token
        session["account"] = account
        if hosted_mode:
            session.permanent = True
        return jsonify({"user": _safe_user(record)})

    @app.post("/api/logout")
    def logout():
        account = session.get("account")
        if account:
            live_locations.stop_actor(account)
        session.pop("account", None)
        return jsonify({"ok": True})

    @app.get("/api/state")
    def state():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        result = _safe(service.dispatch("state", user, {}))
        if isinstance(result, dict):
            result["user"] = _safe_user(user)
            # State already contains only the current participant's bookings.
            # Enrich those rows with the committed road segment only; never
            # return the driver's full corridor route through this endpoint.
            bookings = result.get("bookings")
            if isinstance(bookings, list):
                with store.read() as tx:
                    for booking in bookings:
                        if not isinstance(booking, dict) or booking.get("status") not in {"accepted", "segment_completed"}:
                            continue
                        trip = tx.get("trips", booking.get("trip_id"))
                        segment = route_segment(booking, trip) if trip else None
                        if segment is not None:
                            booking["route"] = segment
            result.update(service.community.unread_counts(user["id"]))
        return jsonify(result)

    @app.get("/api/operations")
    def operations():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        if "ops.read" not in access_summary(user)["staff_capabilities"]:
            return error("Operations access required", 403)
        return jsonify(_safe(service.dispatch("operations", user, {})))

    for action in POST_REQUIRED:
        def post_action(action_name: str = action):
            user = authenticated_user()
            if not user:
                return error("Authentication required", 401)
            body = json_body()
            if not isinstance(body, dict):
                return body
            return dispatch(action_name, user, body)

        app.add_url_rule(f"/api/{action}", endpoint=f"post_{action}", view_func=post_action, methods=["POST"])

    for action in ("profile", "contact", "chat", "chats", "notifications"):
        def get_community_action(action_name: str = action):
            user = authenticated_user()
            if not user:
                return error("Authentication required", 401)
            result = service.dispatch(action_name, user, request.args.to_dict(flat=True))
            return jsonify(_safe(result))

        app.add_url_rule(f"/api/{action}", endpoint=f"get_{action}", view_func=get_community_action, methods=["GET"])

    return app
