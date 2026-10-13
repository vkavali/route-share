"""Provider-confirmed phone accounts with durable, atomic admission limits.

No OTP is generated or persisted here. Runtime adapters must perform bounded
HTTPS calls and report a positive provider verification, never a local bypass.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from .auth import is_active_account, auth_epoch, current_actor_matches
from .mobile_auth import MobileAuthenticator
from .user_projection import account_user


class PhoneAuthError(Exception):
    def __init__(self, message, status=400, code="invalid_phone_flow", retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


class PhoneProvider(Protocol):
    ready: bool

    def send(self, phone: str, *, challenge_id: str, expires_in: int) -> str: ...
    def verify(self, handle: str, code: str) -> bool: ...


DEFAULT_LIMITS = {
    "phone_hour": 5, "phone_day": 10, "ip_ten_minutes": 10,
    "ip_day": 50, "global_minute": 10, "verify_ip_ten_minutes": 30,
    "verify_global_day": 5000,
}
TTL = 300
COOLDOWN = 60
MAX_ATTEMPTS = 5


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _invalid():
    return PhoneAuthError("This sign-in flow is unavailable. Start again.")


class PhoneAuthService:
    def __init__(self, store, *, provider=None, hmac_key=None, global_daily_limit=None,
                 limits=None, mobile_auth=None, clock=None,
                 terms_version="2026-10-11", privacy_version="2026-10-11"):
        self.store, self.provider = store, provider
        self.clock = clock or time.time
        self.mobile_auth = mobile_auth or MobileAuthenticator(store, clock=self.clock)
        self.key = hmac_key.encode() if isinstance(hmac_key, str) else hmac_key
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        if any(type(v) is not int or not 1 <= v <= 100000 for v in self.limits.values()):
            raise ValueError("Phone authentication message limits must be bounded positive integers")
        self.daily_limit = global_daily_limit
        self.terms_version, self.privacy_version = terms_version, privacy_version
        self.enabled = (getattr(provider, "ready", False) is True
                        and isinstance(self.key, bytes) and len(self.key) >= 32
                        and type(global_daily_limit) is int and 1 <= global_daily_limit <= 100000)
        if self.enabled:
            # Rotating this key without migrating identities would allow duplicate
            # accounts. Fail closed rather than silently abandoning reservations.
            fingerprint = self._digest("key-fingerprint", "phone-auth-v1")
            with store.transaction() as tx:
                config = tx.get("phone_auth_config", "identity-key")
                if config and config.get("fingerprint") != fingerprint:
                    raise ValueError("Phone identity key differs from the persistent configuration")
                tx.put("phone_auth_config", "identity-key", {"id": "identity-key", "fingerprint": fingerprint})

    def capabilities(self):
        return {"enabled": self.enabled, "country_code": "+91", "otp_length": 6,
                "expires_in": TTL, "resend_after": COOLDOWN,
                "terms_version": self.terms_version, "privacy_version": self.privacy_version}

    def _ready(self):
        if not self.enabled:
            raise PhoneAuthError("Phone sign-in is temporarily unavailable. Try again later.", 503, "phone_auth_unavailable")

    def _digest(self, purpose, value):
        return hmac.new(self.key, (purpose + "\0" + value).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _phone(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:\+91)?[6-9][0-9]{9}", value):
            raise PhoneAuthError("Enter a valid Indian mobile number.", 400, "invalid_phone")
        return value if value.startswith("+91") else "+91" + value

    def _flow(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise _invalid()
        try:
            decoded = base64.urlsafe_b64decode(value + "=")
        except ValueError:
            raise _invalid() from None
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
            raise _invalid()
        return self._digest("flow", value)

    def _ip(self, value):
        try:
            normalized = str(ipaddress.ip_address(value))
        except (ValueError, TypeError):
            # Do not grant each malformed value an independent quota bucket.
            normalized = "unknown"
        return self._digest("ip", normalized)

    @staticmethod
    def _request(value):
        try:
            if not isinstance(value, str) or str(uuid.UUID(value)) != value.lower():
                raise ValueError()
        except (ValueError, AttributeError):
            raise _invalid() from None
        return value.lower()

    def _prune(self, tx, now):
        for collection in ("phone_challenges", "phone_send_requests", "phone_auth_limits", "phone_send_state"):
            for row in tx.list(collection):
                if row.get("retain_until", 0) <= now:
                    tx.delete(collection, row["id"])

    def _consume(self, tx, now, specs):
        updates = []
        for kind, key, period, maximum in specs:
            start = int(now // period) * period
            identity = self._digest("limit", f"{kind}:{key}:{start}")
            row = tx.get("phone_auth_limits", identity)
            count = row.get("count", 0) if row else 0
            if type(count) is not int or count < 0:
                raise PhoneAuthError("Phone sign-in is temporarily unavailable.", 503, "phone_auth_unavailable")
            if count >= maximum:
                raise PhoneAuthError("Too many attempts. Please wait before trying again.", 429,
                                     "phone_auth_rate_limited", max(1, int(start + period - now)))
            updates.append({"id": identity, "count": count + 1, "retain_until": start + period})
        for row in updates:
            tx.put("phone_auth_limits", row["id"], row)

    @staticmethod
    def _challenge_response(row):
        return {"challenge_id": row["id"], "expires_at": _iso(row["expires_at"]),
                "resend_at": _iso(row["resend_at"]), "masked_phone": "+91 ••••••" + row["phone"][-4:]}

    def _bound(self, tx, challenge_id, flow, now):
        if not isinstance(challenge_id, str) or len(challenge_id) > 64:
            raise _invalid()
        row = tx.get("phone_challenges", challenge_id)
        if not row or not hmac.compare_digest(row.get("flow_hash", ""), flow):
            raise _invalid()
        if row["expires_at"] <= now:
            raise PhoneAuthError("This code expired. Request a new code.", 410, "phone_auth_expired")
        return row

    def start(self, payload, ip):
        return self.start_for(payload, ip, purpose="signin")

    def start_for(self, payload, ip, *, purpose, context=None, authorize=None):
        """Internal trusted purpose/context; HTTP bodies never select these."""
        self._ready()
        phone, flow = self._phone(payload.get("phone")), self._flow(payload.get("flow_token"))
        request_id = self._request(payload.get("request_id"))
        phone_key, ip_key = self._digest("phone", phone), self._ip(ip)
        request_key = self._digest("send-request", flow + ":" + request_id + ":" + purpose + ":" + json.dumps(context or {}, sort_keys=True))
        now = self.clock()
        with self.store.transaction() as tx:
            now = self.clock()
            self._prune(tx, now)
            if authorize:
                authorize(tx)
            prior = tx.get("phone_send_requests", request_key)
            if prior:
                row = tx.get("phone_challenges", prior["challenge_id"])
                if not row or row["phone_key"] != phone_key:
                    raise _invalid()
                if row["expires_at"] <= now:
                    raise PhoneAuthError("This code expired. Request a new code.", 410, "phone_auth_expired")
                if row["state"] == "sent":
                    return self._challenge_response(row)
                if row["state"] == "sending":
                    raise PhoneAuthError("Code delivery is still processing. Please wait.", 409, "phone_auth_busy")
                raise PhoneAuthError("Code delivery could not be confirmed. Try again later.", 503, "phone_auth_unavailable")
            state = tx.get("phone_send_state", phone_key)
            if state and state["resend_at"] > now:
                raise PhoneAuthError("Please wait before requesting another code.", 429,
                                     "phone_auth_rate_limited", max(1, int(state["resend_at"] - now)))
            self._consume(tx, now, [
                ("send-global-day", "all", 86400, self.daily_limit),
                ("send-global-minute", "all", 60, self.limits["global_minute"]),
                ("send-phone-hour", phone_key, 3600, self.limits["phone_hour"]),
                ("send-phone-day", phone_key, 86400, self.limits["phone_day"]),
                ("send-ip-ten", ip_key, 600, self.limits["ip_ten_minutes"]),
                ("send-ip-day", ip_key, 86400, self.limits["ip_day"]),
            ])
            if state:
                old = tx.get("phone_challenges", state["challenge_id"])
                if old:
                    old.update(state="replaced", provider_handle=None)
                    tx.put("phone_challenges", old["id"], old)
            identity = str(uuid.uuid4())
            identity_record = tx.get("phone_identities", phone_key)
            identity_user = tx.get("users", identity_record["user_id"]) if identity_record else None
            identity_at_issue = ({"user_id": identity_record["user_id"], "auth_epoch": auth_epoch(identity_user)}
                                 if identity_record else None)
            row = {"id": identity, "phone": phone, "phone_key": phone_key, "flow_hash": flow,
                   "state": "sending", "purpose": purpose, "context": context or {}, "identity_at_issue": identity_at_issue, "attempts": 0, "expires_at": now + TTL,
                   "resend_at": now + COOLDOWN, "retain_until": now + TTL + 60}
            tx.put("phone_challenges", identity, row)
            tx.put("phone_send_state", phone_key, {"id": phone_key, "challenge_id": identity,
                   "resend_at": row["resend_at"], "retain_until": row["retain_until"]})
            tx.put("phone_send_requests", request_key, {"id": request_key, "challenge_id": identity,
                   "retain_until": row["retain_until"]})
        try:
            handle = self.provider.send(phone, challenge_id=identity, expires_in=TTL)
            success = isinstance(handle, str) and 1 <= len(handle) <= 512
        except Exception:
            handle, success = None, False
        with self.store.transaction() as tx:
            current = tx.get("phone_challenges", identity)
            if not current or current["state"] != "sending" or current["expires_at"] <= self.clock():
                raise _invalid()
            current.update(state="sent" if success else "failed", provider_handle=handle if success else None)
            tx.put("phone_challenges", identity, current)
        if not success:
            raise PhoneAuthError("Code delivery could not be confirmed. Try again later.", 503, "phone_auth_unavailable")
        return self._challenge_response(current)

    def resend(self, payload, ip):
        self._ready()
        flow = self._flow(payload.get("flow_token"))
        with self.store.read() as tx:
            row = self._bound(tx, payload.get("challenge_id"), flow, self.clock())
            if row.get("purpose", "signin") != "signin" or row["state"] not in {"sent", "failed", "replaced"}:
                raise _invalid()
        return self.start({"phone": row["phone"], "flow_token": payload.get("flow_token"),
                           "request_id": payload.get("request_id")}, ip)

    def _consent(self, payload):
        consent = payload.get("consent")
        if (not isinstance(consent, dict) or consent.get("terms_version") != self.terms_version
                or consent.get("privacy_version") != self.privacy_version or consent.get("adult_attested") is not True
                or consent.get("terms_accepted") is not True or consent.get("privacy_accepted") is not True):
            raise PhoneAuthError("Accept the current terms, privacy notice and adult attestation.", 400, "consent_required")
        return {"terms_version": self.terms_version, "privacy_version": self.privacy_version,
                "adult_attested": True, "terms_accepted": True, "privacy_accepted": True, "accepted_at": _iso(self.clock())}

    def requires_onboarding(self, user):
        consent = user.get("phone_consent") or {}
        return (user.get("auth_method") == "phone" and
                (not isinstance(user.get("name"), str) or not user["name"].strip()
                 or user.get("onboarding_required") is not False
                 or consent.get("terms_version") != self.terms_version
                 or consent.get("privacy_version") != self.privacy_version
                 or consent.get("adult_attested") is not True
                 or consent.get("terms_accepted") is not True or consent.get("privacy_accepted") is not True))

    def verify(self, payload, ip, *, native=False):
        self._ready()
        consent = self._consent(payload)

        def complete(tx, current):
            identity = tx.get("phone_identities", current["phone_key"])
            user = tx.get("users", identity["user_id"]) if identity else None
            issued = current.get("identity_at_issue")
            actual = {"user_id": identity["user_id"], "auth_epoch": auth_epoch(user)} if identity else None
            if issued != actual:
                raise PhoneAuthError("This sign-in flow changed. Request a new code.", 409, "invalid_phone_flow")
            if identity and (identity.get("status") != "active" or not is_active_account(user)
                             or user.get("auth_method") != "phone" or user.get("development") is not False
                             or user.get("role") != "member"):
                raise PhoneAuthError("This account is unavailable. Contact support.", 403, "account_unavailable")
            if not identity:
                user_id = "member_" + uuid.uuid4().hex
                user = {"id": user_id, "name": "", "role": "member", "development": False,
                        "account_status": "active", "auth_epoch": 0, "auth_method": "phone", "auth_phone": current["phone"],
                        "phone": current["phone"], "phone_verified": True, "share_phone": False,
                        "driver_approved": False, "driver_approval": None, "staff_capabilities": [],
                        "onboarding_required": True,
                        "verification": {key: "verified" if key == "phone" else "not_checked"
                                         for key in ("phone", "identity", "dl", "rc", "insurance", "selfie")}}
                tx.put("phone_identities", current["phone_key"], {"id": current["phone_key"],
                       "user_id": user_id, "phone": current["phone"], "status": "active"})
            user.update(phone_consent=consent, phone_verified=True)
            tx.put("users", user["id"], user)
            response = self.mobile_auth.issue_in(tx, user) if native else {"user": account_user(user)}
            response["onboarding_required"] = self.requires_onboarding(user)
            return response

        return self.verify_for(payload, ip, purpose="signin", complete=complete)

    def verify_for(self, payload, ip, *, purpose, complete, authorize=None):
        self._ready()
        flow = self._flow(payload.get("flow_token"))
        code = payload.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise PhoneAuthError("Enter the six-digit code.", 400, "phone_auth_invalid_code")
        failure = None
        with self.store.transaction() as tx:
            now = self.clock()
            self._prune(tx, now)
            self._consume(tx, now, [("verify-ip", self._ip(ip), 600, self.limits["verify_ip_ten_minutes"]),
                                   ("verify-global", "all", 86400, self.limits["verify_global_day"])])
            try:
                row = self._bound(tx, payload.get("challenge_id"), flow, now)
                if row.get("purpose", "signin") != purpose:
                    raise _invalid()
                if authorize:
                    authorize(tx, row)
                if row["state"] == "verifying":
                    raise PhoneAuthError("Code verification is processing. Please wait.", 409, "phone_auth_busy")
                if row["state"] != "sent":
                    raise PhoneAuthError("This sign-in flow is unavailable. Start again.", 409, "invalid_phone_flow")
                if row["attempts"] >= MAX_ATTEMPTS:
                    raise PhoneAuthError("Too many code attempts. Request a new code.", 429, "phone_auth_rate_limited", COOLDOWN)
                lease = secrets.token_hex(16)
                row.update(state="verifying", lease=lease, attempts=row["attempts"] + 1)
                tx.put("phone_challenges", row["id"], row)
            except PhoneAuthError as exc:
                failure = exc
        if failure:
            raise failure
        try:
            result = self.provider.verify(row["provider_handle"], code)
            provider_error = type(result) is not bool
        except Exception:
            result, provider_error = False, True
        failure = None
        response = None
        with self.store.transaction() as tx:
            current = tx.get("phone_challenges", row["id"])
            if (not current or current.get("lease") != lease or current["state"] != "verifying"
                    or current["expires_at"] <= self.clock()):
                raise _invalid()
            current.pop("lease", None)
            if provider_error or result is not True:
                current["state"] = "sent"
                failure = (PhoneAuthError("Code verification is temporarily unavailable. Try again.", 503, "phone_auth_unavailable")
                           if provider_error else PhoneAuthError("The code could not be verified.", 400, "phone_auth_invalid_code"))
            else:
                try:
                    if authorize:
                        authorize(tx, current)
                    response = complete(tx, current)
                except PhoneAuthError as exc:
                    failure = exc
                current.update(state="consumed", provider_handle=None)
            tx.put("phone_challenges", current["id"], current)
        if failure:
            raise failure
        return response

    def profile(self, user_id, payload, *, actor=None):
        name = payload.get("name")
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or any(ord(character) < 32 for character in name)):
            raise PhoneAuthError("Name must contain 1 to 80 characters.", 400, "invalid_name")
        with self.store.transaction() as tx:
            user = tx.get("users", user_id)
            if (not is_active_account(user) or (actor is not None and not current_actor_matches(user, actor))
                    or user.get("auth_method") != "phone" or user.get("role") != "member"):
                raise PhoneAuthError("This account is unavailable.", 403, "account_unavailable")
            consent = user.get("phone_consent") or {}
            if (consent.get("terms_version") != self.terms_version or consent.get("privacy_version") != self.privacy_version
                    or consent.get("adult_attested") is not True
                    or consent.get("terms_accepted") is not True or consent.get("privacy_accepted") is not True):
                raise PhoneAuthError("Accept the current terms and privacy notice by signing in again.", 400, "consent_required")
            user.update(name=name.strip(), onboarding_required=False)
            tx.put("users", user_id, user)
        return {"user": account_user(user), "onboarding_required": False}
