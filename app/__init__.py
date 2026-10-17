"""Flask API for the supervised local route-sharing beta."""

from __future__ import annotations

import hmac
import io
import json
import math
import os
import re
import secrets
import weakref
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, session, send_file, render_template
from flask.json.provider import DefaultJSONProvider
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from .community import CommunityError
from .auth import (is_active_account, auth_epoch, current_actor_matches, web_session_hash,
                   issue_web_session_in, revoke_web_session_in, session_binding_matches_in)
from .phone_auth import PhoneAuthError, PhoneAuthService
from .account_lifecycle import AccountLifecycleError, AccountLifecycleService
from .backup_email import BackupEmailService
from .driver_verification import DriverVerificationError, DriverVerificationService, MAX_DOCUMENT_BYTES
from .identity_verification import IdentityVerificationError, IdentityVerificationService
from .payments import PaymentError, PaymentService
from .reviews import ReviewsError, ReviewsService
from .geocoding import GeocodingError, NominatimGeocoder
from .live_location import LiveLocationError, LiveLocationStore, distance_m
from .mobile_auth import MobileAuthError, MobileAuthenticator
from .providers import public_flags
from .permissions import access_summary
from .user_projection import account_user
from .location_policy import sharing_window
from .trusted_contacts import TrustedContactService, TrustedContactError
from .store import Store
from .voice import VoiceError, VoiceService, MAX_MULTIPART_BYTES, bounded_upload, parse_upload, request_id as voice_request_id

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
    return account_user(record)


def _seed_users(store: Store, password: str, *, passwords: dict[str, str] | None = None, development: bool = True) -> None:
    defaults = {"vehicle": {"model": "", "plate": ""}, "verification": {
        "phone": "not_checked", "identity": "not_checked", "dl": "not_checked",
        "rc": "not_checked", "selfie": "not_checked",
    }, "development": True, "phone": ""}
    with store.transaction() as tx:
        for account, (name, role) in ACCOUNT_NAMES.items():
            record = tx.get("users", account)
            existed = record is not None
            record = record or {"id": account, **defaults}
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
            configured_password = passwords[account] if passwords else password
            stored_hash = record.get("password_hash")
            try:
                unchanged_password = isinstance(stored_hash, str) and check_password_hash(stored_hash, configured_password)
            except (TypeError, ValueError):
                unchanged_password = False
            if not unchanged_password:
                record["password_hash"] = generate_password_hash(configured_password)
                if existed:
                    old_epoch = auth_epoch(record)
                    record["auth_epoch"] = (old_epoch if old_epoch is not None else 0) + 1
                    # Revoke both session types when the configured credential changes.
                    for collection in ("web_sessions", "mobile_sessions"):
                        for binding in tx.list(collection):
                            if binding.get("user_id") == account:
                                tx.delete(collection, binding["id"])
            record["development"] = development
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
    if (not hostname or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or (":" not in hostname and (len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in hostname.split("."))))):
        raise ValueError("PUBLIC_ORIGIN must contain an exact valid host, never a wildcard.")
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
        PUBLIC_ORIGIN_ALIASES=os.environ.get("PUBLIC_ORIGIN_ALIASES", ""),
        BETA_ACCOUNT_PASSWORDS=os.environ.get("BETA_ACCOUNT_PASSWORDS"),
        MAX_CONTENT_LENGTH=MAX_JSON_BYTES,
        VOICE_ENABLED=_hosted_enabled(os.environ.get("VOICE_ENABLED", "0")),
        VOICE_MODEL_PATH_EN=os.environ.get("VOICE_MODEL_PATH_EN"),
        VOICE_MODEL_PATH_TE=os.environ.get("VOICE_MODEL_PATH_TE"),
        VOICE_DAILY_LIMIT=os.environ.get("VOICE_DAILY_LIMIT", "100"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
        DEVELOPMENT_MODE=True,
        TESTING=False,
        DIRECT_UPI_ENABLED=_hosted_enabled(os.environ.get("DIRECT_UPI_ENABLED", "0")),
        PHONE_AUTH_ENABLED=_hosted_enabled(os.environ.get("PHONE_AUTH_ENABLED", "0")),
        PHONE_AUTH_SDK_ENABLED=_hosted_enabled(os.environ.get("PHONE_AUTH_SDK_ENABLED", "0")),
        PHONE_AUTH_HMAC_KEY=os.environ.get("PHONE_AUTH_HMAC_KEY"),
        BACKUP_EMAIL_ENABLED=_hosted_enabled(os.environ.get("BACKUP_EMAIL_ENABLED", "0")),
        BACKUP_EMAIL_ENCRYPTION_KEY=os.environ.get("BACKUP_EMAIL_ENCRYPTION_KEY"),
        BACKUP_EMAIL_DAILY_LIMIT=os.environ.get("BACKUP_EMAIL_DAILY_LIMIT"),
        HOSTINGER_MAIL_API_TOKEN=os.environ.get("HOSTINGER_MAIL_API_TOKEN"),
        HOSTINGER_MAILBOX_RESOURCE_ID=os.environ.get("HOSTINGER_MAILBOX_RESOURCE_ID"),
        PHONE_AUTH_DAILY_LIMIT=os.environ.get("PHONE_AUTH_DAILY_LIMIT"),
        IDENTITY_EVIDENCE_KEY=os.environ.get("IDENTITY_EVIDENCE_KEY"),
        DEMO_PASSWORD_ENABLED=_hosted_enabled(os.environ.get("DEMO_PASSWORD_ENABLED", "1")),
        MSG91_WIDGET_ID=os.environ.get("MSG91_WIDGET_ID"),
        MSG91_TOKEN_AUTH=os.environ.get("MSG91_TOKEN_AUTH"),
        MSG91_AUTH_KEY=os.environ.get("MSG91_AUTH_KEY"),
        MSG91_CONTRACT_VERIFIED=_hosted_enabled(os.environ.get("MSG91_CONTRACT_VERIFIED", "0")),
        MSG91_SDK_CONTRACT_VERIFIED=_hosted_enabled(os.environ.get("MSG91_SDK_CONTRACT_VERIFIED", "0")),
        MSG91_PROVIDER_ABUSE_CONTROLS_CONFIRMED=_hosted_enabled(os.environ.get("MSG91_PROVIDER_ABUSE_CONTROLS_CONFIRMED", "0")),
        APP_DISPLAY_NAME=os.environ.get("APP_DISPLAY_NAME", "SeatPal"),
        PUBLIC_OPERATOR_NAME=os.environ.get("PUBLIC_OPERATOR_NAME", ""),
        PUBLIC_SUPPORT_EMAIL=os.environ.get("PUBLIC_SUPPORT_EMAIL", ""),
        NOMINATIM_BASE_URL=os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org/search"),
    )
    if config:
        app.config.update(config)
    hosted_mode = _hosted_enabled(app.config["HOSTED_MODE"])
    app.config["HOSTED_MODE"] = hosted_mode
    accepted_public_netlocs = frozenset()
    if hosted_mode:
        app.config["PUBLIC_ORIGIN"] = _canonical_public_origin(app.config.get("PUBLIC_ORIGIN"))
        aliases = app.config["PUBLIC_ORIGIN_ALIASES"]
        if not isinstance(aliases, str):
            raise ValueError("PUBLIC_ORIGIN_ALIASES must be a comma-separated string of HTTPS origins.")
        try:
            alias_origins = [_canonical_public_origin(item.strip()) for item in aliases.split(",")] if aliases else []
        except ValueError as exc:
            raise ValueError("PUBLIC_ORIGIN_ALIASES contains an invalid canonical HTTPS origin.") from exc
        accepted_public_netlocs = frozenset(urlsplit(origin).netloc.casefold()
            for origin in [app.config["PUBLIC_ORIGIN"], *alias_origins])
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
    mobile_auth = MobileAuthenticator(store, demo_password_enabled=_hosted_enabled(app.config["DEMO_PASSWORD_ENABLED"]),
                                      rate_limit_key=app.config["SECRET_KEY"])
    app.extensions["mobile_auth"] = mobile_auth
    operator_name = str(app.config["PUBLIC_OPERATOR_NAME"]).strip()
    support_email = str(app.config["PUBLIC_SUPPORT_EMAIL"]).strip()
    operator_configured = bool(1 <= len(operator_name) <= 160 and
                               re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", support_email))
    phone_provider = None
    phone_sdk_provider = None
    if _hosted_enabled(app.config["PHONE_AUTH_ENABLED"]) and operator_configured:
        # An injected provider is only permitted in an explicitly isolated test app.
        if app.testing and app.config.get("PHONE_AUTH_PROVIDER") is not None:
            phone_provider = app.config["PHONE_AUTH_PROVIDER"]
        else:
            from .sms_provider import MSG91Provider
            phone_provider = MSG91Provider(
                widget_id=app.config["MSG91_WIDGET_ID"], token_auth=app.config["MSG91_TOKEN_AUTH"],
                auth_key=app.config["MSG91_AUTH_KEY"], handle_secret=app.config["PHONE_AUTH_HMAC_KEY"],
                contract_verified=_hosted_enabled(app.config["MSG91_CONTRACT_VERIFIED"]),
            )
        if _hosted_enabled(app.config.get("PHONE_AUTH_SDK_ENABLED")):
            if app.testing and app.config.get("PHONE_AUTH_SDK_PROVIDER") is not None:
                phone_sdk_provider = app.config["PHONE_AUTH_SDK_PROVIDER"]
            else:
                from .sms_provider import MSG91WebSDKVerifier
                phone_sdk_provider = MSG91WebSDKVerifier(
                    widget_id=app.config["MSG91_WIDGET_ID"], token_auth=app.config["MSG91_TOKEN_AUTH"],
                    auth_key=app.config["MSG91_AUTH_KEY"],
                    contract_verified=_hosted_enabled(app.config["MSG91_SDK_CONTRACT_VERIFIED"]),
                    abuse_controls_confirmed=_hosted_enabled(app.config["MSG91_PROVIDER_ABUSE_CONTROLS_CONFIRMED"]),
                )
    daily_limit = app.config["PHONE_AUTH_DAILY_LIMIT"]
    if isinstance(daily_limit, str) and re.fullmatch(r"[0-9]{1,6}", daily_limit):
        daily_limit = int(daily_limit)
    phone_auth = PhoneAuthService(store, provider=phone_provider,
        hmac_key=app.config["PHONE_AUTH_HMAC_KEY"], global_daily_limit=daily_limit,
        sdk_provider=phone_sdk_provider, mobile_auth=mobile_auth)
    app.extensions["phone_auth"] = phone_auth
    lifecycle = AccountLifecycleService(store, phone_auth, mobile_auth=mobile_auth)
    app.extensions["account_lifecycle"] = lifecycle
    email_provider = None
    if _hosted_enabled(app.config["BACKUP_EMAIL_ENABLED"]):
        if app.testing and app.config.get("BACKUP_EMAIL_PROVIDER") is not None:
            email_provider = app.config["BACKUP_EMAIL_PROVIDER"]
        else:
            from .email_delivery import email_provider_from_config
            email_provider = email_provider_from_config(app.config)
    email_limit = app.config["BACKUP_EMAIL_DAILY_LIMIT"]
    if isinstance(email_limit, str) and re.fullmatch(r"[0-9]{1,6}", email_limit):
        email_limit = int(email_limit)
    backup_email = BackupEmailService(store, lifecycle, provider=email_provider,
        encryption_key=app.config["BACKUP_EMAIL_ENCRYPTION_KEY"], daily_limit=email_limit)
    lifecycle.backup_email = backup_email
    app.extensions["backup_email"] = backup_email
    geocoder = NominatimGeocoder(app.config["NOMINATIM_BASE_URL"])
    app.extensions["geocoder"] = geocoder
    voice_service = VoiceService(store=store, daily_limit=app.config["VOICE_DAILY_LIMIT"], model_paths={
        language: app.config.get("VOICE_MODEL_PATH_" + language.upper())
        for language in ("en", "te")
    } if _hosted_enabled(app.config["VOICE_ENABLED"]) else {})
    app.extensions["voice_service"] = voice_service
    weakref.finalize(app, voice_service.close)

    # Imports are delayed until app construction so the API can be imported while
    # the domain module is being assembled by the rest of the beta implementation.
    from .domain import DomainError, Service
    from .routing import OSRMProvider

    service = Service(store, OSRMProvider(store=store))
    service.community.maintenance()
    app.extensions["beta_service"] = service
    verification_service = DriverVerificationService(store, encryption_key=app.config.get("IDENTITY_EVIDENCE_KEY"))
    identity_service = IdentityVerificationService(store, encryption_key=app.config.get("IDENTITY_EVIDENCE_KEY"))
    reviews_service = ReviewsService(store)
    payment_service = PaymentService(store, enabled=_hosted_enabled(app.config["DIRECT_UPI_ENABLED"]))
    app.extensions["driver_verification_service"] = verification_service
    app.extensions["identity_verification_service"] = identity_service
    app.extensions["reviews_service"] = reviews_service
    app.extensions["payment_service"] = payment_service

    def feature_flags():
        return {**public_flags(), "direct_upi_enabled": payment_service.enabled,
                # A manual UPI declaration is not a verified gateway charge.
                "paid_rides_enabled": False,
                "verified_payment_settlement_enabled": False,
                "payment_provider_mode": "direct_upi_manual" if payment_service.enabled else "disabled",
                "driver_document_review_enabled": True,
                "public_registration_enabled": phone_auth.public_enabled,
                "demo_password_enabled": mobile_auth.demo_password_enabled}

    def phone_capabilities_payload():
        return {**phone_auth.capabilities(), "backup_email_enabled": backup_email.enabled, "terms_url": "/terms", "privacy_url": "/privacy",
                "operator_configured": operator_configured}

    def error(message: str, status: int):
        return jsonify({"error": message}), status

    def authenticated_user() -> dict[str, Any] | None:
        bearer_user = getattr(g, "mobile_user", None)
        account = bearer_user.get("id") if bearer_user is not None else session.get("account")
        if not account:
            return None
        with store.read() as tx:
            record = tx.get("users", account)
            snapshot = bearer_user if bearer_user is not None else {"id": account, "auth_epoch": session.get("auth_epoch")}
            if not current_actor_matches(record, snapshot) or not session_binding_matches_in(tx, record, account_session_binding()):
                return None
        result = _safe_user(record)
        result["onboarding_required"] = phone_auth.requires_onboarding(record)
        return result

    def account_session_binding():
        token_hash = getattr(g, "mobile_token_hash", None)
        if token_hash:
            return "native:" + token_hash
        digest = web_session_hash(session.get("auth_session_id"))
        return "web:" + digest if digest else ""

    def establish_web_session(user, *, rotate_csrf=True, expected_password_hash=None):
        session_id = secrets.token_urlsafe(32)
        previous_csrf = session.get("csrf_token")
        with store.transaction() as tx:
            current = tx.get("users", user["id"])
            if (not current_actor_matches(current, user)
                    or (expected_password_hash is not None
                        and current.get("password_hash") != expected_password_hash)):
                raise PhoneAuthError("Account changed. Sign in again.", 401, "account_changed")
            revoke_web_session_in(tx, session.get("auth_session_id"))
            issue_web_session_in(tx, current, session_id)
        session.clear()
        session.update(account=user["id"], auth_epoch=auth_epoch(user), auth_session_id=session_id,
                       csrf_token=secrets.token_urlsafe(32) if rotate_csrf or not previous_csrf else previous_csrf)
        session.permanent = True
        return session["csrf_token"]

    @app.before_request
    def enforce_request_limits_and_csrf():
        host_header = request.host.casefold()
        healthcheck_request = request.path == "/api/health" and request.method == "GET"
        if app.config["HOSTED_MODE"]:
            railway_health_host = healthcheck_request and host_header == "healthcheck.railway.app"
            if host_header not in accepted_public_netlocs and not railway_health_host:
                return error("This hosted beta only accepts its configured public host", 400)
            if not request.is_secure and not healthcheck_request:
                return error("HTTPS is required", 400)
        else:
            host = urlsplit("//" + request.host).hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                return error("This development server only accepts loopback hosts", 400)
        voice_upload = request.path == "/api/voice/transcribe" and request.method == "POST"
        document_upload = request.path in {"/api/driver_documents", "/api/identity_documents"} and request.method == "POST"
        if document_upload:
            # Raise only this authenticated multipart endpoint's parser bound.
            request.max_content_length = MAX_DOCUMENT_BYTES + 64 * 1024
            # Werkzeug buffers a multipart chunk before it separates fields/files.
            # Keep that parser buffer bounded, then separately bound text fields.
            request.max_form_memory_size = 128 * 1024
            request.max_form_parts = 8
        limit = MAX_DOCUMENT_BYTES + 64 * 1024 if document_upload else MAX_JSON_BYTES
        if not voice_upload and request.content_length is not None and request.content_length > limit:
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
        if request.path in {"/api/voice/capabilities", "/api/voice/transcribe", "/api/voice/cancel"}:
            user = authenticated_user()
            if not user:
                return error("Authentication required", 401)
            if user.get("role") != "member":
                return error("Voice trip entry is available to members only", 403)
            if voice_upload and request.content_length is not None and request.content_length > MAX_MULTIPART_BYTES:
                raise VoiceError("VOICE_INVALID_AUDIO", 413)
        if request.path not in {"/api/login", "/api/mobile/login", "/api/bootstrap"}:
            expected_user_id = request.headers.get("X-Expected-User-ID")
            if expected_user_id is not None:
                active_user = authenticated_user()
                if (not isinstance(expected_user_id, str) or not expected_user_id
                        or len(expected_user_id) > 128 or not active_user
                        or active_user.get("id") != expected_user_id):
                    return jsonify({"error": "Account changed. Refresh and try again.", "code": "account_changed"}), 409
        # A half-created phone account cannot call member APIs before onboarding.
        active_user = authenticated_user()
        onboarding_routes = {"/api/bootstrap", "/api/phone/capabilities", "/api/phone/profile",
                             "/api/logout", "/api/mobile/logout", "/api/health",
                             "/api/account/lifecycle", "/api/account/reauth/start", "/api/account/reauth/verify",
                             "/api/account/recovery-key", "/api/account/delete",
                             "/api/account/backup-email/start", "/api/account/backup-email/verify", "/api/account/backup-email/remove"}
        if (request.path.startswith("/api/") and active_user and active_user.get("onboarding_required")
                and request.path not in onboarding_routes):
            return jsonify({"error": "Complete your account details first.", "code": "onboarding_required"}), 403
        mobile_signin_routes = {"/api/mobile/login", "/api/mobile/phone/start",
                                "/api/mobile/phone/resend", "/api/mobile/phone/verify",
                                "/api/mobile/account/recovery/start", "/api/mobile/account/recovery/verify",
                                "/api/mobile/account/recovery/email/start", "/api/mobile/account/recovery/email/verify",
                                "/api/mobile/account/recovery/phone/start", "/api/mobile/account/recovery/phone/verify"}
        if request.path in mobile_signin_routes and request.method == "POST":
            # Native unauthenticated requests carry no browser session. Refuse
            # cookie/Origin-bearing requests here so this cannot bypass web CSRF.
            if request.path != "/api/mobile/login" and (request.headers.get("Origin") or request.headers.get("Cookie")):
                return error("Use the browser sign-in endpoint", 403)
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
        # Host was already allowlisted above; aliases never authorize cross-origin browser POSTs.
        expected = urlsplit(request.host_url)
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
            g.mobile_auth_lock = None
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

    @app.errorhandler(VoiceError)
    def handle_voice_error(exc):
        return jsonify({"error": str(exc), "code": exc.code, **(exc.quota or {})}), exc.status

    @app.errorhandler(GeocodingError)
    def handle_geocoding_error(exc):
        return error(str(exc), 503)

    @app.errorhandler(MobileAuthError)
    def handle_mobile_auth_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(PhoneAuthError)
    def handle_phone_auth_error(exc):
        payload = {"error": str(exc), "code": exc.code}
        if exc.retry_after is not None:
            payload["retry_after"] = exc.retry_after
        response = jsonify(payload)
        if exc.retry_after is not None:
            response.headers["Retry-After"] = str(exc.retry_after)
        return response, exc.status

    @app.errorhandler(IdentityVerificationError)
    def handle_identity_verification_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(AccountLifecycleError)
    def handle_lifecycle_error(exc):
        payload = {"error": str(exc), "code": exc.code}
        if getattr(exc, "blockers", None) is not None:
            payload["blockers"] = exc.blockers
        response = jsonify(payload)
        if getattr(exc, "retry_after", None) is not None:
            payload["retry_after"] = exc.retry_after
            response = jsonify(payload)
            response.headers["Retry-After"] = str(exc.retry_after)
        return response, exc.status

    @app.errorhandler(CommunityError)
    def handle_community_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(DriverVerificationError)
    @app.errorhandler(ReviewsError)
    @app.errorhandler(PaymentError)
    def handle_account_flow_error(exc):
        return jsonify({"error": str(exc), "code": exc.code}), exc.status

    @app.errorhandler(DomainError)
    def handle_domain_error(exc):
        payload = {"error": str(getattr(exc, "message", exc))}
        if getattr(exc, "code", None):
            payload["code"] = exc.code
        return jsonify(payload), int(getattr(exc, "status", 400))

    @app.errorhandler(413)
    def too_large(_exc):
        if request.path == "/api/voice/transcribe":
            return handle_voice_error(VoiceError("VOICE_INVALID_AUDIO", 413))
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
        if request.path == "/api/voice/transcribe":
            response.headers["Connection"] = "close"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if phone_auth.sdk_enabled:
            script_src = ("'self' https://verify.msg91.com https://www.google.com/recaptcha/ "
                          "https://www.gstatic.com/recaptcha/ https://hcaptcha.com https://*.hcaptcha.com")
            frame_src = ("https://verify.msg91.com https://www.google.com/recaptcha/ "
                         "https://www.gstatic.com/recaptcha/ https://hcaptcha.com https://*.hcaptcha.com")
            connect_src = ("'self' https://tiles.openfreemap.org https://control.msg91.com https://api.msg91.com "
                           "https://www.google.com/recaptcha/ https://www.gstatic.com/recaptcha/ "
                           "https://hcaptcha.com https://*.hcaptcha.com")
            style_src = "'self' 'unsafe-inline' https://hcaptcha.com https://*.hcaptcha.com"
        else:
            script_src = "'self'"
            frame_src = "'self'"
            connect_src = "'self' https://tiles.openfreemap.org"
            style_src = "'self' 'unsafe-inline'"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src {script_src}; frame-src {frame_src}; worker-src 'self' blob:; "
            f"style-src {style_src}; img-src 'self' data: blob: https://tiles.openfreemap.org "
            "https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
            f"connect-src {connect_src}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        if app.config["HOSTED_MODE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.route("/static/maps/india-soi-boundaries.geojson", methods=["GET", "HEAD"])
    def india_soi_boundaries():
        """Serve the phone map boundary data, using its gzip sidecar when accepted."""
        raw_path = Path(app.static_folder) / "maps" / "india-soi-boundaries.geojson"
        gzip_path = raw_path.with_name(raw_path.name + ".gz")
        use_gzip = (gzip_path.is_file()
                    and request.accept_encodings.quality("gzip") > 0)
        response = send_file(
            gzip_path if use_gzip else raw_path,
            mimetype="application/geo+json",
            conditional=True,
            etag=True,
        )
        response.vary.add("Accept-Encoding")
        if use_gzip:
            response.headers["Content-Encoding"] = "gzip"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/welcome")
    @app.get("/welcome/latest")
    @app.get("/welcome/previous")
    @app.get("/faq")
    def public_site():
        from .public_site import public_site_context
        from .public_site_latest import public_site_latest_context
        args = dict(
            page="faq" if request.path == "/faq" else "landing",
            language=request.args.get("lang", "en"), app_name=app.config["APP_DISPLAY_NAME"],
            registration_enabled=phone_auth.public_enabled, payments_enabled=payment_service.enabled,
            support_email=support_email, operator_configured=operator_configured)
        if request.path in {"/welcome", "/welcome/latest"}:
            return render_template("public-site-latest.html", **public_site_latest_context(
                landing_path=request.path, **args))
        context = public_site_context(**args)
        if request.path == "/welcome/previous":
            lang = context["lang"]
            context["links"].update(landing="/welcome/previous?lang=" + lang,
                                    en="/welcome/previous?lang=en", te="/welcome/previous?lang=te")
            context.update(comparison_url="/welcome/latest?lang=" + lang,
                           comparison_label="Latest design" if lang == "en" else "కొత్త డిజైన్")
        return render_template("public-site.html", **context)

    @app.get("/terms")
    @app.get("/privacy")
    def public_policy():
        from .public_site import normalize_public_language
        return render_template("public-policy.html", privacy=request.path == "/privacy",
            app_name=str(app.config["APP_DISPLAY_NAME"])[:80], operator_name=operator_name,
            support_email=support_email, operator_configured=operator_configured,
            registration_enabled=phone_auth.public_enabled,
            version=phone_auth.privacy_version if request.path == "/privacy" else phone_auth.terms_version,
            public_lang=normalize_public_language(request.args.get("lang", "en")))

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
        user = authenticated_user()
        payload: dict[str, Any] = {
            "user": user, "csrf_token": token, "flags": feature_flags(),
            "phone_auth": phone_capabilities_payload(),
            "mode": "hosted_beta" if hosted_mode else "local_development",
        }
        try:
            extra = service.dispatch("bootstrap", user, {})
            if isinstance(extra, dict):
                payload.update(_safe(extra))
                payload["user"] = user
                payload["csrf_token"] = token
                payload["flags"] = feature_flags()
                payload["mode"] = "hosted_beta" if hosted_mode else "local_development"
        except DomainError:
            pass
        return jsonify(_safe(payload))

    @app.get("/api/phone/capabilities")
    def phone_capabilities():
        return jsonify(phone_capabilities_payload())

    @app.post("/api/phone/start")
    @app.post("/api/phone/resend")
    @app.post("/api/phone/verify")
    @app.post("/api/mobile/phone/start")
    @app.post("/api/mobile/phone/resend")
    @app.post("/api/mobile/phone/verify")
    def phone_signin():
        if authenticated_user():
            return jsonify({"error": "Sign out before signing in to another account.", "code": "sign_out_required"}), 409
        body = json_body()
        if not isinstance(body, dict):
            return body
        action = request.path.rsplit("/", 1)[-1]
        native = request.path.startswith("/api/mobile/")
        # Never use an arbitrary X-Forwarded-For value. In hosted mode only the
        # final proxy hop is trusted by the configured ProxyFix middleware.
        ip = request.remote_addr or "unknown"
        if action == "verify":
            result = phone_auth.verify(body, ip, native=native)
            if not native:
                result["csrf_token"] = establish_web_session(result["user"])
        else:
            result = getattr(phone_auth, action)(body, ip)
        return jsonify(result)

    @app.post("/api/phone/sdk/start")
    @app.post("/api/phone/sdk/resend")
    @app.post("/api/phone/sdk/verify")
    def phone_sdk_signin():
        if authenticated_user():
            return jsonify({"error": "Sign out before signing in to another account.", "code": "sign_out_required"}), 409
        body = json_body()
        if not isinstance(body, dict):
            return body
        action = request.path.rsplit("/", 1)[-1]
        ip = request.remote_addr or "unknown"
        result = getattr(phone_auth, "sdk_" + action)(body, ip, session.get("csrf_token"))
        if action == "verify":
            result["csrf_token"] = establish_web_session(result["user"])
        return jsonify(result)

    @app.post("/api/phone/profile")
    def phone_profile():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return body
        return jsonify(phone_auth.profile(user["id"], body, actor=user))

    @app.get("/api/account/lifecycle")
    def account_lifecycle():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        return jsonify(lifecycle.status(user, account_session_binding()))

    @app.post("/api/account/reauth/start")
    @app.post("/api/account/reauth/verify")
    @app.post("/api/account/recovery-key")
    @app.post("/api/account/delete")
    def account_lifecycle_action():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return body
        binding = account_session_binding()
        if request.path.endswith("/start"):
            release_mobile_auth_lock(None)
            result = lifecycle.reauth_start(user, body, binding, request.remote_addr or "unknown")
        elif request.path.endswith("/verify"):
            release_mobile_auth_lock(None)
            result = lifecycle.reauth_verify(user, body, binding, request.remote_addr or "unknown")
        elif request.path.endswith("/recovery-key"):
            result = lifecycle.set_recovery_key(user, body, binding)
        else:
            result = lifecycle.delete(user, body, binding)
            # The transaction has committed before releasing active device streams.
            live_locations.stop_actor(user["id"])
            voice_service.cancel_owner(user["id"])
            if getattr(g, "mobile_user", None) is None:
                session.clear()
        return jsonify(result)

    @app.post("/api/account/backup-email/start")
    @app.post("/api/account/backup-email/verify")
    @app.post("/api/account/backup-email/remove")
    def account_backup_email():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return body
        binding = account_session_binding()
        ip = request.remote_addr or "unknown"
        if request.path.endswith("/start"):
            release_mobile_auth_lock(None)
            result = backup_email.start_enrollment(user, body, binding, ip)
        elif request.path.endswith("/verify"):
            result = backup_email.verify_enrollment(user, body, binding, ip)
        else:
            result = backup_email.remove(user, body, binding)
        return jsonify(result)

    @app.post("/api/account/recovery/email/start")
    @app.post("/api/account/recovery/email/verify")
    @app.post("/api/account/recovery/phone/start")
    @app.post("/api/account/recovery/phone/verify")
    @app.post("/api/mobile/account/recovery/email/start")
    @app.post("/api/mobile/account/recovery/email/verify")
    @app.post("/api/mobile/account/recovery/phone/start")
    @app.post("/api/mobile/account/recovery/phone/verify")
    def account_email_recovery():
        if authenticated_user():
            return jsonify({"error": "Sign out before recovering an account.", "code": "sign_out_required"}), 409
        body = json_body()
        if not isinstance(body, dict):
            return body
        ip = request.remote_addr or "unknown"
        native = request.path.startswith("/api/mobile/")
        if request.path.endswith("/email/start"):
            result = backup_email.start_recovery(body, ip)
        elif request.path.endswith("/email/verify"):
            result = backup_email.verify_recovery(body, ip)
        elif request.path.endswith("/phone/start"):
            result = backup_email.start_phone(body, ip)
        else:
            result = backup_email.verify_phone(body, ip, native=native)
            live_locations.stop_actor(result["user"]["id"])
            voice_service.cancel_owner(result["user"]["id"])
            if not native:
                result["csrf_token"] = establish_web_session(result["user"])
        return jsonify(result)

    @app.post("/api/account/recovery/start")
    @app.post("/api/account/recovery/verify")
    @app.post("/api/mobile/account/recovery/start")
    @app.post("/api/mobile/account/recovery/verify")
    def account_recovery():
        if authenticated_user():
            return jsonify({"error": "Sign out before recovering an account.", "code": "sign_out_required"}), 409
        body = json_body()
        if not isinstance(body, dict):
            return body
        ip = request.remote_addr or "unknown"
        native = request.path.startswith("/api/mobile/")
        if request.path.endswith("/start"):
            result = lifecycle.recovery_start(body, ip)
        else:
            result = lifecycle.recovery_verify(body, ip, native=native)
            live_locations.stop_actor(result["user"]["id"])
            voice_service.cancel_owner(result["user"]["id"])
            if not native:
                result["csrf_token"] = establish_web_session(result["user"])
        return jsonify(result)

    @app.post("/api/mobile/login")
    def mobile_login():
        body = json_body()
        if not isinstance(body, dict):
            return body
        result = mobile_auth.login(body.get("account"), body.get("password"), request.remote_addr or "unknown")
        # The authenticator already projects the persisted record. Projecting its
        # public DTO again loses the private evidence used to calculate access.
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
        voice_service.cancel_owner(user["id"])
        live_locations.stop_actor(user["id"])
        return jsonify({"ok": True})

    @app.get("/api/voice/capabilities")
    def voice_capabilities():
        return jsonify(voice_service.capabilities())

    @app.post("/api/voice/cancel")
    def voice_cancel():
        body = json_body()
        if not isinstance(body, dict):
            return body
        if set(body) != {"request_id"}:
            raise VoiceError("VOICE_INVALID_AUDIO")
        return jsonify(voice_service.cancel(authenticated_user()["id"], body["request_id"]))

    @app.post("/api/voice/transcribe")
    def voice_transcribe():
        user = authenticated_user()
        identity = voice_request_id(request.headers.get("X-Voice-Request-ID"))
        if request.mimetype != "multipart/form-data":
            raise VoiceError("VOICE_INVALID_AUDIO")
        # Reserve under the bearer lock, then release it before any body read or
        # inference. Logout/cancel with this same token must remain responsive.
        bearer = request.headers.get("Authorization")
        with voice_service.reserve(user["id"], identity, on_admitted=lambda: release_mobile_auth_lock(None)) as job:
            with bounded_upload(request.environ, job) as environ:
                parsed_id, language, audio = parse_upload(environ)
            if parsed_id != identity:
                raise VoiceError("VOICE_INVALID_AUDIO")
            result = voice_service.transcribe(job, identity, language, audio)
            del audio
            if bearer is not None:
                auth = mobile_auth.authenticate(bearer.partition(" ")[2].strip())
                if not auth:
                    return jsonify({"error": "Mobile session expired or revoked. Sign in again.", "code": "invalid_token"}), 401
                g.mobile_user, g.mobile_token_hash, g.mobile_auth_lock = auth["user"], auth["token_hash"], auth["lock"]
            current = authenticated_user()
            if not current or current.get("id") != user["id"] or current.get("role") != "member":
                return error("Authentication required", 401)
            # Logout can cancel an in-flight browser request even though its
            # signed cookie was already loaded. Never return its late transcript.
            voice_service.ensure_current(job)
            return jsonify(result)

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

    @app.get("/api/places/reverse")
    def reverse_place():
        if not authenticated_user():
            return error("Authentication required", 401)
        language = request.args.get("lang", "en")
        if language not in {"en", "te", "hi"}:
            return error("Language must be en, te, or hi.", 400)
        try:
            lat, lon = float(request.args.get("lat", "")), float(request.args.get("lon", ""))
        except (TypeError, ValueError, OverflowError):
            return error("Choose a valid point on the map.", 400)
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return error("Choose a valid point on the map.", 400)
        # Explicit user lookup only; returned object coordinates are not a snap.
        return jsonify({"place": app.extensions["geocoder"].reverse(lat, lon, language)})

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
            if not current_actor_matches(tx.get("users", user["id"]), user) or not session_binding_matches_in(tx, user, account_session_binding()):
                raise PhoneAuthError("Account session changed. Sign in again.", 401, "account_changed")
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
            if not current_actor_matches(tx.get("users", user["id"]), user) or not session_binding_matches_in(tx, user, account_session_binding()):
                raise PhoneAuthError("Account session changed. Sign in again.", 401, "account_changed")
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
            if not current_actor_matches(tx.get("users", user["id"]), user) or not session_binding_matches_in(tx, user, account_session_binding()):
                raise PhoneAuthError("Account session changed. Sign in again.", 401, "account_changed")
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
            if not current_actor_matches(tx.get("users", user["id"]), user) or not session_binding_matches_in(tx, user, account_session_binding()):
                raise PhoneAuthError("Account session changed. Sign in again.", 401, "account_changed")
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
        establish_web_session(record, rotate_csrf=False, expected_password_hash=record["password_hash"])
        return jsonify({"user": _safe_user(record)})

    @app.post("/api/logout")
    def logout():
        account = session.get("account")
        with store.transaction() as tx:
            revoke_web_session_in(tx, session.get("auth_session_id"))
        if account:
            voice_service.cancel_owner(account)
            live_locations.stop_actor(account)
        session.pop("account", None)
        session.pop("auth_session_id", None)
        session.pop("auth_epoch", None)
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

    # These services keep document evidence, payee details and review publication
    # consent in private collections with explicit response projections.
    @app.get("/api/payments/trip-budget/<trip_id>")
    def trip_payment_budget(trip_id):
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        return jsonify(payment_service.dispatch("trip_budget", user, {"trip_id": trip_id}))

    @app.post("/api/payments/trip-budget/action")
    def change_trip_payment_budget():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        body = json_body()
        if not isinstance(body, dict):
            return body
        return jsonify(payment_service.dispatch("trip_budget_action", user, body))

    account_reads = {
        "driver_application": lambda user, body: verification_service.get_application(user),
        "verification_queue": lambda user, body: verification_service.verification_queue(user),
        "identity_application": lambda user, body: identity_service.get_application(user),
        "identity_verification_queue": lambda user, body: identity_service.verification_queue(user),
        "reviews": lambda user, body: reviews_service.dispatch("reviews", user, body),
        "driver_profile": lambda user, body: reviews_service.dispatch("driver_profile", user, body),
        "payments": lambda user, body: payment_service.dispatch("payments", user, body),
        "payment": lambda user, body: payment_service.dispatch("payment", user, body),
        "payout_account": lambda user, body: payment_service.dispatch("payout_account", user, body),
    }
    account_writes = {
        "driver_application": verification_service.save_application,
        "submit_driver_application": verification_service.submit_application,
        "review_driver_application": verification_service.review_application,
        "driver_review_progress": verification_service.save_review_progress,
        "identity_review_progress": identity_service.save_review_progress,
        "identity_application": identity_service.save_application,
        "submit_identity_application": identity_service.submit_application,
        "withdraw_identity_application": identity_service.withdraw_application,
        "review_identity_application": identity_service.review_application,
        "payment_action": lambda user, body: payment_service.dispatch("payment_action", user, body),
    }
    for name, method in account_reads.items():
        def get_account_flow(handler=method):
            user = authenticated_user()
            if not user:
                return error("Authentication required", 401)
            return jsonify(handler(user, request.args.to_dict(flat=True)))
        app.add_url_rule(f"/api/{name}", endpoint=f"account_get_{name}", view_func=get_account_flow, methods=["GET"])
    for name, method in account_writes.items():
        def post_account_flow(handler=method):
            user = authenticated_user()
            if not user:
                return error("Authentication required", 401)
            body = json_body()
            if not isinstance(body, dict):
                return body
            return jsonify(handler(user, body))
        app.add_url_rule(f"/api/{name}", endpoint=f"account_post_{name}", view_func=post_account_flow, methods=["POST"])

    def review_progress_response(service):
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        if set(request.args) != {"application_id"} or len(request.args.getlist("application_id")) != 1:
            return jsonify({"error": "Supply one application identifier", "code": "review_progress_invalid"}), 400
        return jsonify(service.get_review_progress(user, request.args["application_id"]))

    @app.get("/api/identity_review_progress")
    def identity_review_progress():
        return review_progress_response(identity_service)

    @app.get("/api/driver_review_progress")
    def driver_review_progress():
        return review_progress_response(verification_service)

    @app.post("/api/driver_documents")
    def upload_driver_document():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        if user.get("role") != "member":
            return error("Driver applications are for member accounts", 403)
        if request.mimetype != "multipart/form-data":
            return error("Upload documents as multipart/form-data", 415)
        if set(request.files) != {"file"} or len(request.files.getlist("file")) != 1:
            return error("Choose exactly one document", 400)
        if set(request.form) - {"kind", "expires_on", "expected_version"} or any(len(request.form.getlist(k)) != 1 for k in request.form):
            return error("Invalid document fields", 400)
        if sum(len(value.encode("utf-8")) for value in request.form.values()) > MAX_JSON_BYTES:
            return error("Document fields are too large", 413)
        raw_version = request.form.get("expected_version", "")
        if not re.fullmatch(r"[0-9]{1,10}", raw_version):
            return error("A valid expected_version is required", 400)
        file = request.files["file"]
        return jsonify(verification_service.upload_document(
            user, kind=request.form.get("kind"), expires_on=request.form.get("expires_on"),
            filename=file.filename or "document", content=file.stream, expected_version=int(raw_version),
        ))

    @app.get("/api/driver_document")
    def download_driver_document():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        document_id = request.args.get("document_id", "")
        if not document_id or len(document_id) > 128:
            return error("A document identifier is required", 400)
        document = verification_service.get_document(user, document_id)
        return send_file(io.BytesIO(document["content"]), mimetype=document["content_type"],
                         as_attachment=True, download_name=document["filename"], max_age=0)

    def document_preview_response(service):
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        if (set(request.args) - {"document_id", "page"}
                or any(len(request.args.getlist(key)) != 1 for key in request.args)):
            return error("Invalid document preview parameters", 400)
        return jsonify(service.get_document_preview(user, request.args.get("document_id", ""), request.args.get("page", "1")))

    @app.get("/api/driver_document_preview")
    def preview_driver_document():
        return document_preview_response(verification_service)

    @app.get("/api/identity_document_preview")
    def preview_identity_document():
        return document_preview_response(identity_service)

    @app.post("/api/identity_documents")
    def upload_identity_document():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        if user.get("role") != "member":
            return error("Identity applications are for member accounts", 403)
        if request.mimetype != "multipart/form-data":
            return error("Upload documents as multipart/form-data", 415)
        if set(request.files) != {"file"} or len(request.files.getlist("file")) != 1:
            return error("Choose exactly one document", 400)
        if set(request.form) - {"kind", "expires_on", "expected_version"} or any(len(request.form.getlist(k)) != 1 for k in request.form):
            return error("Invalid document fields", 400)
        if sum(len(value.encode("utf-8")) for value in request.form.values()) > MAX_JSON_BYTES:
            return error("Document fields are too large", 413)
        raw_version = request.form.get("expected_version", "")
        if not re.fullmatch(r"[0-9]{1,10}", raw_version):
            return error("A valid expected_version is required", 400)
        file = request.files["file"]
        return jsonify(identity_service.upload_document(
            user, kind=request.form.get("kind"), expires_on=request.form.get("expires_on"),
            filename=file.filename or "document", content=file.stream, expected_version=int(raw_version),
        ))

    @app.get("/api/identity_document")
    def download_identity_document():
        user = authenticated_user()
        if not user:
            return error("Authentication required", 401)
        document_id = request.args.get("document_id", "")
        if not document_id or len(document_id) > 128:
            return error("A document identifier is required", 400)
        document = identity_service.get_document(user, document_id)
        return send_file(io.BytesIO(document["content"]), mimetype=document["content_type"],
                         as_attachment=True, download_name=document["filename"], max_age=0)

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
