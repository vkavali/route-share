"""Local prototype bearer authentication for native mobile clients."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash


MOBILE_SESSION_SECONDS = 8 * 60 * 60
LOGIN_ATTEMPTS_PER_MINUTE = 10


class MobileAuthError(Exception):
    def __init__(self, message: str, status: int, code: str):
        super().__init__(message)
        self.status = status
        self.code = code


class MobileAuthenticator:
    """Stores only token hashes; bearer requests are serialized per token stripe."""

    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._token_locks = tuple(threading.RLock() for _ in range(64))

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _utcnow(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    def _rate_limit(self, ip: str, account: str | None = None) -> None:
        now = self.clock()
        # One shared per-IP bucket prevents cycling account names to evade the
        # prototype limiter. Both web and mobile login call this path.
        key = (ip[:96], "*")
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= LOGIN_ATTEMPTS_PER_MINUTE:
                raise MobileAuthError("Too many sign-in attempts. Wait a minute and try again.", 429, "rate_limited")
            attempts.append(now)
            if len(self._attempts) > 4096:
                for stale_key in list(self._attempts):
                    if not self._attempts[stale_key] or self._attempts[stale_key][0] <= now - 60:
                        del self._attempts[stale_key]

    def verify_credentials(self, account: str, password: str, ip: str) -> dict | None:
        if not isinstance(account, str) or not account or len(account) > 128 or not isinstance(password, str) or len(password) > 1024:
            raise MobileAuthError("Account and password are required.", 400, "invalid_credentials")
        self._rate_limit(ip or "unknown")
        with self.store.read() as tx:
            user = tx.get("users", account)
        valid = user is not None and check_password_hash(user["password_hash"], password)
        return user if valid else None

    def login(self, account: str, password: str, ip: str) -> dict:
        user = self.verify_credentials(account, password, ip)
        if not user:
            raise MobileAuthError("Invalid account or password.", 401, "invalid_credentials")
        token = secrets.token_urlsafe(32)
        expiry = self._utcnow() + timedelta(seconds=MOBILE_SESSION_SECONDS)
        expires_at = expiry.isoformat()
        digest = self.token_hash(token)
        with self.store.transaction() as tx:
            for session in tx.list("mobile_sessions"):
                try:
                    expired = datetime.fromisoformat(session["expires_at"]) <= self._utcnow()
                except (KeyError, TypeError, ValueError):
                    expired = True
                if expired:
                    tx.delete("mobile_sessions", session["id"])
            tx.put("mobile_sessions", digest, {
                "id": digest, "user_id": user["id"], "account": account,
                "created_at": self._utcnow().isoformat(), "expires_at": expires_at,
            })
        safe_user = {key: value for key, value in user.items() if key not in {"password", "password_hash"}}
        return {"token": token, "user": safe_user, "expires_at": expires_at}

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
            if not session or not user:
                return None
            try:
                expiry = datetime.fromisoformat(session["expires_at"])
            except (KeyError, TypeError, ValueError):
                expiry = datetime.min.replace(tzinfo=timezone.utc)
            if expiry <= self._utcnow():
                with self.store.transaction() as tx:
                    tx.delete("mobile_sessions", digest)
                return None
            safe_user = {key: value for key, value in user.items() if key not in {"password", "password_hash"}}
            keep_lock = True
            return {"token_hash": digest, "user": safe_user, "lock": lock}
        finally:
            # Keep the stripe only on successful return, where Flask teardown owns it.
            if not keep_lock:
                lock.release()

    def revoke(self, token_hash: str) -> None:
        with self.store.transaction() as tx:
            tx.delete("mobile_sessions", token_hash)
