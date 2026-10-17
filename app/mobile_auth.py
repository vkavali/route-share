"""Local prototype bearer authentication for native mobile clients."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash

from .auth import current_actor_matches, is_active_account, auth_epoch
from .user_projection import account_user


MOBILE_SESSION_SECONDS = 8 * 60 * 60
LOGIN_ATTEMPTS_PER_MINUTE = 10
MAX_PASSWORD_LOGIN_SCOPES = 4096


class MobileAuthError(Exception):
    def __init__(self, message: str, status: int, code: str):
        super().__init__(message)
        self.status = status
        self.code = code


class MobileAuthenticator:
    """Stores only token hashes; bearer requests are serialized per token stripe."""

    def __init__(self, store, *, clock=None, demo_password_enabled=True, rate_limit_key=None):
        self.store = store
        self.demo_password_enabled = demo_password_enabled
        self.clock = clock or time.time
        # Production callers pass Flask's persistent SECRET_KEY. The fallback
        # keeps standalone/test instances usable; it is intentionally not
        # suitable for sharing rate-limit state across processes.
        self._rate_limit_key = (rate_limit_key.encode("utf-8") if isinstance(rate_limit_key, str)
                                else rate_limit_key or secrets.token_bytes(32))
        self._token_locks = tuple(threading.RLock() for _ in range(64))

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _utcnow(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    def _rate_limit(self, ip: str, account: str | None = None) -> None:
        now = self.clock()
        try:
            normalized_ip = ipaddress.ip_address(str(ip).strip()).compressed
        except ValueError:
            normalized_ip = "unknown"
        scope = hmac.new(self._rate_limit_key, b"password-login-ip-v1\0" + normalized_ip.encode("ascii"),
                         hashlib.sha256).hexdigest()
        limited = False
        cutoff = now - 60
        # Store.transaction uses SQLite BEGIN IMMEDIATE, making check-and-add
        # atomic across web/mobile callers, restarts, and worker processes.
        with self.store.transaction() as tx:
            # Store only HMAC keys and timestamps, never raw addresses/accounts.
            active_scopes = []
            for stale in tx.list("password_login_attempts"):
                expiry = stale.get("expires_at")
                if isinstance(expiry, (int, float)) and expiry > now:
                    active_scopes.append(stale)
                else:
                    tx.delete("password_login_attempts", stale["id"])
            state = tx.get("password_login_attempts", scope)
            attempts = [stamp for stamp in (state or {}).get("attempts", [])
                        if isinstance(stamp, (int, float)) and stamp > cutoff]
            if state is None and len(active_scopes) >= MAX_PASSWORD_LOGIN_SCOPES:
                # Never evict a live scope to admit a new source.
                limited = True
            elif len(attempts) >= LOGIN_ATTEMPTS_PER_MINUTE:
                limited = True
                if state is not None and attempts != state.get("attempts"):
                    state.update(attempts=attempts, expires_at=max(attempts) + 60)
                    tx.put("password_login_attempts", scope, state)
            else:
                attempts.append(now)
                tx.put("password_login_attempts", scope, {
                    "id": scope, "attempts": attempts, "expires_at": max(attempts) + 60,
                })
        if limited:
            raise MobileAuthError("Too many sign-in attempts. Wait a minute and try again.", 429, "rate_limited")

    def verify_credentials(self, account: str, password: str, ip: str) -> dict | None:
        if not isinstance(account, str) or not account or len(account) > 128 or not isinstance(password, str) or len(password) > 1024:
            raise MobileAuthError("Account and password are required.", 400, "invalid_credentials")
        self._rate_limit(ip or "unknown")
        with self.store.read() as tx:
            user = tx.get("users", account)
        valid = (is_active_account(user) and isinstance(user.get("password_hash"), str)
                 and (self.demo_password_enabled or user.get("development") is not True or user.get("role") == "staff")
                 and check_password_hash(user["password_hash"], password))
        return user if valid else None

    def login(self, account: str, password: str, ip: str) -> dict:
        user = self.verify_credentials(account, password, ip)
        if not user:
            raise MobileAuthError("Invalid account or password.", 401, "invalid_credentials")
        with self.store.transaction() as tx:
            current = tx.get("users", user["id"])
            if (not is_active_account(current) or not current_actor_matches(current, user)
                    or current.get("password_hash") != user.get("password_hash")):
                raise MobileAuthError("Invalid account or password.", 401, "invalid_credentials")
            return self.issue_in(tx, current)

    def issue_in(self, tx, user):
        """Issue inside the caller's transaction, including OTP consumption."""
        if not is_active_account(user):
            raise MobileAuthError("Account unavailable.", 403, "account_unavailable")
        token = secrets.token_urlsafe(32)
        expires_at = (self._utcnow() + timedelta(seconds=MOBILE_SESSION_SECONDS)).isoformat()
        digest = self.token_hash(token)
        for existing in tx.list("mobile_sessions"):
            try:
                expired = datetime.fromisoformat(existing["expires_at"]) <= self._utcnow()
            except (KeyError, TypeError, ValueError):
                expired = True
            if expired:
                tx.delete("mobile_sessions", existing["id"])
        tx.put("mobile_sessions", digest, {
            "id": digest, "user_id": user["id"], "account": user["id"],
            "created_at": self._utcnow().isoformat(), "expires_at": expires_at, "auth_epoch": auth_epoch(user),
        })
        return {"token": token, "user": account_user(user), "expires_at": expires_at}

    def authenticate(self, token: str):
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            return None
        digest = self.token_hash(token)
        with self.store.read() as tx:
            session = tx.get("mobile_sessions", digest)
        if not session:
            return None
        lock = self._token_locks[int(digest[:2], 16) % len(self._token_locks)]
        lock.acquire()
        keep_lock = False
        try:
            with self.store.read() as tx:
                session = tx.get("mobile_sessions", digest)
                user = tx.get("users", session.get("user_id")) if session else None
            if not session or not is_active_account(user) or auth_epoch(session) != auth_epoch(user):
                return None
            try:
                expiry = datetime.fromisoformat(session["expires_at"])
            except (KeyError, TypeError, ValueError):
                expiry = datetime.min.replace(tzinfo=timezone.utc)
            if expiry <= self._utcnow():
                with self.store.transaction() as tx:
                    tx.delete("mobile_sessions", digest)
                return None
            safe_user = account_user(user)
            keep_lock = True
            return {"token_hash": digest, "user": safe_user, "lock": lock}
        finally:
            # Keep the stripe only on successful return, where Flask teardown owns it.
            if not keep_lock:
                lock.release()

    def revoke(self, token_hash: str) -> None:
        with self.store.transaction() as tx:
            tx.delete("mobile_sessions", token_hash)
