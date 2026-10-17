"""Verified backup email for recovering an existing phone account, never sign-in.

OTP/proof hashes are domain separated, addresses encrypted, and every mutation
rechecks current session/epoch/email version inside the SQLite transaction.
"""
from __future__ import annotations

import hmac
import re
import secrets
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

from .auth import auth_epoch
from .account_lifecycle import AccountLifecycleError
from .phone_auth import PhoneAuthError, _iso
from .user_projection import account_user

TTL, COOLDOWN, ATTEMPTS, RECOVERY_TTL = 300, 60, 5, 600
GENERIC_MESSAGE = "Check your email for a code. Recovery works only with a previously verified backup email."


def unavailable():
    return AccountLifecycleError("This email verification is unavailable. Start again.", 400, "email_verification_invalid")


class BackupEmailService:
    def __init__(self, store, lifecycle, *, provider=None, encryption_key=None, daily_limit=None, clock=None):
        self.store, self.life, self.phone = store, lifecycle, lifecycle.phone
        self.provider, self.clock = provider, clock or time.time
        self.cipher = None
        try:
            if encryption_key:
                self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        except (ValueError, TypeError):
            pass
        self.daily_limit = daily_limit
        self.enabled = (self.phone.enabled and self.cipher is not None and getattr(provider, "ready", False) is True
                        and type(daily_limit) is int and 1 <= daily_limit <= 100000)
        # A changed encryption key must never silently strand existing addresses.
        if self.cipher:
            with store.transaction() as tx:
                guard = tx.get("backup_email_config", "encryption")
                if guard:
                    try:
                        valid = self.cipher.decrypt(guard["token"].encode()) == b"backup-email-v1"
                    except (InvalidToken, ValueError, KeyError):
                        valid = False
                    if not valid:
                        raise ValueError("Backup email encryption key differs from the persistent configuration")
                else:
                    tx.put("backup_email_config", "encryption", {"id": "encryption", "token": self._encrypt("backup-email-v1")})

    def _hash(self, purpose, value):
        return self.life._hash("email-" + purpose, value)

    def _ready(self):
        if not self.enabled:
            raise AccountLifecycleError("Backup email is temporarily unavailable. Try again later.", 503, "backup_email_unavailable")

    def _encrypt(self, value):
        return self.cipher.encrypt(value.encode()).decode()

    def _decrypt(self, value):
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except (InvalidToken, AttributeError, ValueError):
            raise AccountLifecycleError("Backup email is temporarily unavailable.", 503, "backup_email_unavailable") from None

    @staticmethod
    def _email(value):
        # Deliberately bounded ASCII mailbox syntax; no display names, CRLF,
        # quoted local parts or provider-specific plus/dot alias normalization.
        if not isinstance(value, str):
            raise AccountLifecycleError("Enter a valid email address.", 400, "invalid_email")
        value = value.strip().lower()
        if (len(value) > 254 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9.-]+\.[a-z]{2,63}", value)):
            raise AccountLifecycleError("Enter a valid email address.", 400, "invalid_email")
        local, domain = value.split("@")
        if (len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split("."))):
            raise AccountLifecycleError("Enter a valid email address.", 400, "invalid_email")
        return value

    @staticmethod
    def _mask(address):
        local, domain = address.split("@")
        return local[0] + "•••@" + domain

    def status_in(self, tx, user):
        row = tx.get("account_backup_emails", user["id"])
        return {"enabled": self.enabled, "configured": bool(row),
                "masked_email": self._mask(self._decrypt(row["address"])) if row and self.cipher else None,
                "verified_at": row["verified_at"] if row else None}

    def _prune(self, tx):
        for collection in ("email_challenges", "email_send_requests", "email_send_state", "email_recovery_proofs"):
            for row in tx.list(collection):
                if row.get("retain_until", row.get("expires_at", 0)) <= self.clock():
                    tx.delete(collection, row["id"])
        self.phone._prune(tx, self.clock())

    def _version(self, tx, user_id):
        row = tx.get("account_backup_emails", user_id)
        return row.get("version") if row else None

    def _enroll_actor(self, tx, row, actor, binding):
        user = self.life._actor(tx, actor, binding)
        proof = tx.get("account_action_proofs", row["action_proof"])
        if (row.get("user_id") != user["id"] or row.get("auth_epoch") != auth_epoch(user)
                or row.get("binding_hash") != self.life._hash("binding", binding)
                or self._version(tx, user["id"]) != row.get("previous_version")
                or not proof or proof.get("used") or proof.get("purpose") != "backup_email"
                or proof.get("user_id") != user["id"] or proof.get("auth_epoch") != auth_epoch(user)
                or proof.get("binding_hash") != row["binding_hash"] or proof["expires_at"] <= self.clock()):
            raise unavailable()
        return user

    def _recovery_actor(self, tx, row):
        user = tx.get("users", row.get("user_id", ""))
        email = tx.get("account_backup_emails", row.get("user_id", ""))
        if (not self.life._real(user) or not email or row.get("auth_epoch") != auth_epoch(user)
                or row.get("email_version") != email.get("version") or row.get("address_key") != email.get("address_key")):
            raise unavailable()
        return user

    def start_enrollment(self, actor, payload, binding, ip):
        self._ready()
        address = self._email(payload.get("email"))
        with self.store.read() as tx:
            user = self.life._actor(tx, actor, binding)
            proof = self.life._proof(tx, user, binding, payload.get("action_token"), "backup_email")
            context = {"user_id": user["id"], "auth_epoch": auth_epoch(user), "action_proof": proof["id"],
                       "binding_hash": self.life._hash("binding", binding), "previous_version": self._version(tx, user["id"])}
        return self._start(address, payload, ip, "enroll", context,
                           authorize=lambda tx, row: self._enroll_actor(tx, row, actor, binding))

    def start_recovery(self, payload, ip):
        self._ready()
        address = self._email(payload.get("email"))
        key = self._hash("address", address)
        context = {}
        with self.store.read() as tx:
            for email in tx.list("account_backup_emails"):
                if email["address_key"] == key:
                    user = tx.get("users", email["user_id"])
                    if self.life._real(user):
                        context = {"user_id": user["id"], "auth_epoch": auth_epoch(user), "email_version": email["version"]}
                    break
        # Send the same message even for an unknown address: neither response,
        # delivery nor send latency says whether this address owns an account.
        return self._start(address, payload, ip, "recover", context)

    def _start(self, address, payload, ip, purpose, context, authorize=None):
        flow = self.phone._flow(payload.get("flow_token"))
        request_id = self.phone._request(payload.get("request_id"))
        address_key = self._hash("address", address)
        request_key = self._hash("request", flow + ":" + request_id + ":" + purpose)
        with self.store.transaction() as tx:
            self._prune(tx)
            if authorize:
                authorize(tx, context)
            prior = tx.get("email_send_requests", request_key)
            if prior:
                row = tx.get("email_challenges", prior["challenge_id"])
                if not row or row["address_key"] != address_key or row["purpose"] != purpose or row["expires_at"] <= self.clock():
                    raise unavailable()
                if row["state"] == "sending":
                    raise AccountLifecycleError("Email delivery is processing. Please wait.", 409, "email_busy")
                if row["state"] != "sent":
                    raise unavailable()
                return self._response(row)
            state = tx.get("email_send_state", address_key)
            if state and state["resend_at"] > self.clock():
                raise AccountLifecycleError("Please wait before requesting another code.", 429, "email_rate_limited",
                                            retry_after=max(1, int(state["resend_at"] - self.clock())))
            self.phone._consume(tx, self.clock(), [
                ("email-send-address-hour", address_key, 3600, 5), ("email-send-address-day", address_key, 86400, 10),
                ("email-send-ip-ten", self.phone._ip(ip), 600, 10), ("email-send-ip-day", self.phone._ip(ip), 86400, 50),
                ("email-send-global-minute", "all", 60, 20), ("email-send-global-day", "all", 86400, self.daily_limit)])
            if state:
                old = tx.get("email_challenges", state["challenge_id"])
                if old:
                    old.update(state="replaced", code_hash=None)
                    tx.put("email_challenges", old["id"], old)
            identity, code = str(uuid.uuid4()), f"{secrets.randbelow(1000000):06d}"
            row = {"id": identity, "purpose": purpose, "flow_hash": flow, "address_key": address_key,
                   "address": self._encrypt(address), "code_hash": self._hash("code", identity + ":" + code),
                   "state": "sending", "attempts": 0, "expires_at": self.clock() + TTL,
                   "resend_at": self.clock() + COOLDOWN, "retain_until": self.clock() + TTL + 60, **context}
            tx.put("email_challenges", identity, row)
            tx.put("email_send_requests", request_key, {"id": request_key, "challenge_id": identity, "retain_until": row["retain_until"], "user_id": context.get("user_id")})
            tx.put("email_send_state", address_key, {"id": address_key, "challenge_id": identity, "resend_at": row["resend_at"], "retain_until": row["retain_until"], "user_id": context.get("user_id")})
        try:
            self.provider.send_code(address, code, "backup_email" if purpose == "enroll" else "account_recovery")
            delivered = True
        except Exception:
            delivered = False
        failure = None
        with self.store.transaction() as tx:
            current = tx.get("email_challenges", identity)
            if not current or current["state"] != "sending" or current["expires_at"] <= self.clock():
                raise unavailable()
            try:
                if authorize:
                    authorize(tx, current)
                elif current.get("user_id"):
                    self._recovery_actor(tx, current)
            except PhoneAuthError as exc:
                failure = exc
            current["state"] = "sent" if delivered and not failure else "failed"
            if current["state"] == "failed":
                current["code_hash"] = None
            tx.put("email_challenges", identity, current)
        if failure:
            # The public recovery response remains generic even on a concurrent change.
            if purpose != "recover":
                raise failure
        if not delivered:
            raise AccountLifecycleError("Email delivery could not be confirmed. Wait a minute and request a new code.", 503, "backup_email_unavailable", retry_after=COOLDOWN)
        return self._response(current)

    def _response(self, row):
        response = {"challenge_id": row["id"], "expires_at": _iso(row["expires_at"]), "resend_at": _iso(row["resend_at"])}
        if row["purpose"] == "recover":
            response["message"] = GENERIC_MESSAGE
        else:
            response["masked_email"] = self._mask(self._decrypt(row["address"]))
        return response

    def _verify(self, payload, ip, purpose, complete):
        self._ready()
        flow = self.phone._flow(payload.get("flow_token"))
        code = payload.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise AccountLifecycleError("Enter the six-digit email code.", 400, "email_invalid_code")
        failure, response = None, None
        with self.store.transaction() as tx:
            self._prune(tx)
            self.phone._consume(tx, self.clock(), [("email-verify-ip", self.phone._ip(ip), 600, 30),
                                                   ("email-verify-global", "all", 86400, 5000)])
            try:
                identity = payload.get("challenge_id")
                row = tx.get("email_challenges", identity) if isinstance(identity, str) and len(identity) <= 64 else None
                if (not row or row["purpose"] != purpose or row["flow_hash"] != flow
                        or row["state"] != "sent" or row["expires_at"] <= self.clock()):
                    raise unavailable()
                if row["attempts"] >= ATTEMPTS:
                    raise AccountLifecycleError("Too many code attempts. Request a new code.", 429, "email_rate_limited", retry_after=COOLDOWN)
                row["attempts"] += 1
                if not hmac.compare_digest(row["code_hash"], self._hash("code", row["id"] + ":" + code)):
                    tx.put("email_challenges", row["id"], row)
                    raise AccountLifecycleError("The email code could not be verified.", 400, "email_invalid_code")
                # A correct OTP is always consumed, including a concurrent account change.
                row.update(state="consumed", code_hash=None)
                tx.put("email_challenges", row["id"], row)
                response = complete(tx, row)
            except PhoneAuthError as exc:
                failure = exc
        if failure:
            raise failure
        return response

    def verify_enrollment(self, actor, payload, binding, ip):
        def complete(tx, row):
            user = self._enroll_actor(tx, row, actor, binding)
            if any(email["address_key"] == row["address_key"] and email["user_id"] != user["id"]
                   for email in tx.list("account_backup_emails")):
                raise AccountLifecycleError("This address cannot be used as your backup email. Use another address.", 409, "backup_email_unavailable")
            proof = tx.get("account_action_proofs", row["action_proof"])
            proof["used"] = True
            tx.put("account_action_proofs", proof["id"], proof)
            self._clear_flows(tx, user["id"])
            tx.put("account_backup_emails", user["id"], {"id": user["id"], "user_id": user["id"],
                   "address_key": row["address_key"], "address": row["address"], "version": secrets.token_hex(16),
                   "verified_at": _iso(self.clock())})
            return {"backup_email": self.status_in(tx, user)}
        return self._verify(payload, ip, "enroll", complete)

    @staticmethod
    def _clear_flows(tx, user_id):
        for collection in ("email_challenges", "email_send_requests", "email_send_state", "email_recovery_proofs"):
            for row in tx.list(collection):
                if row.get("user_id") == user_id:
                    tx.delete(collection, row["id"])
        for row in tx.list("phone_challenges"):
            if row.get("purpose") == "email_account_recovery" and row.get("context", {}).get("user_id") == user_id:
                tx.delete("phone_challenges", row["id"])

    def remove(self, actor, payload, binding):
        with self.store.transaction() as tx:
            user = self.life._actor(tx, actor, binding)
            proof = self.life._proof(tx, user, binding, payload.get("action_token"), "backup_email")
            self._clear_flows(tx, user["id"])
            tx.delete("account_backup_emails", user["id"])
            proof["used"] = True
            tx.put("account_action_proofs", proof["id"], proof)
            return {"backup_email": self.status_in(tx, user)}

    def verify_recovery(self, payload, ip):
        def complete(tx, row):
            user = self._recovery_actor(tx, row)
            token = secrets.token_urlsafe(32)
            digest = self._hash("recovery-proof", token)
            expires = self.clock() + RECOVERY_TTL
            tx.put("email_recovery_proofs", digest, {"id": digest, "user_id": user["id"],
                   "auth_epoch": auth_epoch(user), "email_version": row["email_version"],
                   "address_key": row["address_key"], "flow_hash": row["flow_hash"], "expires_at": expires})
            return {"recovery_token": token, "expires_at": _iso(expires)}
        return self._verify(payload, ip, "recover", complete)

    def _recovery_proof(self, tx, payload):
        token = payload.get("recovery_token")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise unavailable()
        row = tx.get("email_recovery_proofs", self._hash("recovery-proof", token))
        if not row or row["flow_hash"] != self.phone._flow(payload.get("flow_token")) or row["expires_at"] <= self.clock():
            raise unavailable()
        return row, self._recovery_actor(tx, row)

    def start_phone(self, payload, ip):
        self._ready()
        new_phone = self.phone._phone(payload.get("new_phone"))
        with self.store.read() as tx:
            proof, user = self._recovery_proof(tx, payload)
        if new_phone == user.get("auth_phone"):
            raise AccountLifecycleError("Use a different new phone number.", 400, "recovery_unavailable")
        context = {"user_id": user["id"], "auth_epoch": auth_epoch(user), "email_proof": proof["id"]}
        def authorize(tx):
            current, _ = self._recovery_proof(tx, payload)
            if current["id"] != proof["id"]:
                raise unavailable()
        result = self.phone.start_for({"phone": new_phone, "flow_token": payload.get("flow_token"),
                    "request_id": payload.get("request_id")}, ip, purpose="email_account_recovery", context=context, authorize=authorize)
        with self.store.read() as tx:
            authorize(tx)  # SMS provider work happened outside any write transaction.
        return result

    def verify_phone(self, payload, ip, native=False):
        self._ready()
        def authorize(tx, challenge):
            proof, user = self._recovery_proof(tx, payload)
            context = challenge.get("context", {})
            if (context.get("email_proof") != proof["id"] or context.get("user_id") != user["id"]
                    or context.get("auth_epoch") != auth_epoch(user)):
                raise unavailable()
            return user
        def complete(tx, challenge):
            user = authorize(tx, challenge)
            if tx.get("phone_identities", challenge["phone_key"]):
                raise AccountLifecycleError("This new phone cannot be used for recovery.", 409, "recovery_unavailable")
            old_keys = [row["id"] for row in tx.list("phone_identities") if row.get("user_id") == user["id"]]
            for key in old_keys:
                tx.put("phone_identities", key, {"id": key, "user_id": user["id"], "status": "replaced"})
            self.life._revoke(tx, user["id"], phone_keys=[*old_keys, challenge["phone_key"]], except_challenge=challenge["id"])
            user.update(auth_epoch=auth_epoch(user) + 1, auth_phone=challenge["phone"], phone=challenge["phone"], phone_verified=True, share_phone=False)
            user.pop("recovery_key_id", None)
            tx.put("users", user["id"], user)
            tx.put("phone_identities", challenge["phone_key"], {"id": challenge["phone_key"], "user_id": user["id"], "phone": challenge["phone"], "status": "active"})
            result = self.life.mobile_auth.issue_in(tx, user) if native else {"user": account_user(user)}
            result["onboarding_required"] = self.phone.requires_onboarding(user)
            return result
        return self.phone.verify_for(payload, ip, purpose="email_account_recovery", complete=complete, authorize=authorize)
