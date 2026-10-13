"""Self-service primary-store deletion and optional saved-code phone recovery.

Ordinary sign-in stays OTP-only; recovery is not recycled-number protection.
No legal erasure/retention claim, bank action or proof-free support override.
"""
from __future__ import annotations

import secrets
import time
import uuid

from .auth import auth_epoch, current_actor_matches, is_active_account, session_binding_matches_in
from .phone_auth import PhoneAuthError, _iso
from .user_projection import account_user

RETAINED = ["terminal_trip_booking_history", "settled_payment_records", "restricted_safety_audit", "phone_abuse_reservation"]
UNRESOLVED_PAYMENTS = {"agreed", "passenger_reported", "disputed", "refund_requested", "refund_reported"}
PROOF_SECONDS = 300


class AccountLifecycleError(PhoneAuthError):
    def __init__(self, message, status=400, code="invalid_action_proof", *, blockers=None, retry_after=None):
        super().__init__(message, status, code, retry_after)
        self.blockers = blockers or []


class AccountLifecycleService:
    def __init__(self, store, phone_auth, *, mobile_auth=None, clock=None):
        self.store, self.phone = store, phone_auth
        self.mobile_auth = mobile_auth or phone_auth.mobile_auth
        self.clock = clock or time.time

    def _hash(self, purpose, value):
        if not isinstance(self.phone.key, bytes) or len(self.phone.key) < 32:
            raise AccountLifecycleError("Account security is temporarily unavailable.", 503, "phone_auth_unavailable")
        return self.phone._digest("lifecycle-" + purpose, value)

    @staticmethod
    def _real(record):
        return (is_active_account(record) and record.get("auth_method") == "phone"
                and record.get("development") is False and record.get("role") == "member")

    def _actor(self, tx, actor, binding):
        current = tx.get("users", actor.get("id", "")) if isinstance(actor, dict) else None
        if not self._real(current) or not current_actor_matches(current, actor):
            raise AccountLifecycleError("This account session is unavailable.", 401, "account_unavailable")
        if not session_binding_matches_in(tx, current, binding, at=self.clock()):
            raise AccountLifecycleError("Sign in again before changing your account.", 401, "reauth_required")
        return current

    def _secret(self, value):
        self._hash("configuration-check", "")
        try:
            self.phone._flow(value)  # canonical 32-byte base64url, no plaintext storage
        except PhoneAuthError:
            raise AccountLifecycleError("Enter a valid saved recovery code.", 400, "invalid_recovery_code") from None
        return self._hash("recovery", value)

    def _prune(self, tx):
        for row in tx.list("account_action_proofs"):
            if row.get("expires_at", 0) <= self.clock():
                tx.delete("account_action_proofs", row["id"])

    @staticmethod
    def _blockers(tx, user_id):
        blockers = []
        for trip in tx.list("trips"):
            if trip.get("driver_id") == user_id and trip.get("status") in {"published", "started"}:
                blockers.append({"code": "active_trip", "trip_id": trip["id"]})
        own_bookings = {row["id"]: row for row in tx.list("bookings")
                        if user_id in {row.get("driver_id"), row.get("passenger_id")}}
        for booking in own_bookings.values():
            if booking.get("status") in {"pending", "accepted"}:
                blockers.append({"code": "active_booking", "booking_id": booking["id"]})
        for payment in tx.list("payments"):
            if payment.get("booking_id", payment.get("id")) in own_bookings and payment.get("status") in UNRESOLVED_PAYMENTS:
                blockers.append({"code": "unresolved_payment", "booking_id": payment.get("booking_id", payment["id"])})
        return blockers

    def status(self, actor, session_binding):
        with self.store.read() as tx:
            user = self._actor(tx, actor, session_binding)
            blockers = self._blockers(tx, user["id"])
            binding_hash = self._hash("binding", session_binding)
            proofs = [row["expires_at"] for row in tx.list("account_action_proofs")
                      if row.get("user_id") == user["id"] and row.get("binding_hash") == binding_hash
                      and row.get("auth_epoch") == auth_epoch(user) and not row.get("used")
                      and row.get("expires_at", 0) > self.clock()]
            key = tx.get("account_recovery_keys", user.get("recovery_key_id", ""))
            configured = bool(key and key.get("user_id") == user["id"])
        return {"deletion_allowed": not blockers, "blockers": blockers, "recovery_key_configured": configured,
                "recently_reauthenticated_until": _iso(max(proofs)) if proofs else None,
                "retained_categories": RETAINED.copy()}

    def reauth_start(self, actor, payload, session_binding, ip):
        purpose = payload.get("purpose")
        if not isinstance(purpose, str) or purpose not in {"delete", "recovery_key"}:
            raise AccountLifecycleError("Choose an account action.")
        with self.store.read() as tx:
            user = self._actor(tx, actor, session_binding)
        context = {"user_id": user["id"], "auth_epoch": auth_epoch(user), "purpose": purpose,
                   "binding_hash": self._hash("binding", session_binding)}
        return self.phone.start_for({"phone": user["auth_phone"], "flow_token": payload.get("flow_token"),
                    "request_id": payload.get("request_id")}, ip, purpose="account_reauth", context=context,
                    authorize=lambda tx: self._actor(tx, actor, session_binding))

    def reauth_verify(self, actor, payload, session_binding, ip):
        def authorize(tx, challenge):
            user = self._actor(tx, actor, session_binding)
            context = challenge.get("context", {})
            if (context.get("user_id") != user["id"] or context.get("auth_epoch") != auth_epoch(user)
                    or context.get("binding_hash") != self._hash("binding", session_binding)
                    or context.get("purpose") not in {"delete", "recovery_key"}
                    or challenge.get("phone") != user.get("auth_phone")):
                raise AccountLifecycleError("This account verification is unavailable.")
            return user

        def complete(tx, challenge):
            user = authorize(tx, challenge)
            self._prune(tx)
            token = secrets.token_urlsafe(32)
            digest = self._hash("action", token)
            expires = self.clock() + PROOF_SECONDS
            tx.put("account_action_proofs", digest, {"id": digest, "user_id": user["id"],
                   "auth_epoch": auth_epoch(user), "binding_hash": self._hash("binding", session_binding),
                   "purpose": challenge["context"]["purpose"], "expires_at": expires, "used": False})
            return {"action_token": token, "expires_at": _iso(expires), "purpose": challenge["context"]["purpose"]}
        return self.phone.verify_for(payload, ip, purpose="account_reauth", complete=complete, authorize=authorize)

    def _proof(self, tx, user, binding, token, purpose):
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise AccountLifecycleError("Verify this account action again.")
        row = tx.get("account_action_proofs", self._hash("action", token))
        if (not row or row.get("used") or row.get("user_id") != user["id"]
                or row.get("auth_epoch") != auth_epoch(user) or row.get("purpose") != purpose
                or row.get("binding_hash") != self._hash("binding", binding)):
            raise AccountLifecycleError("Verify this account action again.")
        if row["expires_at"] <= self.clock():
            raise AccountLifecycleError("Account verification expired. Verify again.", 410, "reauth_expired")
        return row

    def _install_key(self, tx, user, digest):
        for row in tx.list("account_recovery_keys"):
            if row.get("user_id") == user["id"]:
                tx.delete("account_recovery_keys", row["id"])
        tx.put("account_recovery_keys", digest, {"id": digest, "user_id": user["id"], "created_at": _iso(self.clock())})
        user["recovery_key_id"] = digest

    def set_recovery_key(self, actor, payload, session_binding):
        if payload.get("saved") is not True:
            raise AccountLifecycleError("Save your recovery code before continuing.", 400, "recovery_save_required")
        digest = self._secret(payload.get("recovery_secret"))
        with self.store.transaction() as tx:
            user = self._actor(tx, actor, session_binding)
            proof = self._proof(tx, user, session_binding, payload.get("action_token"), "recovery_key")
            if tx.get("account_recovery_keys", digest):
                raise AccountLifecycleError("Generate and save a new recovery code.", 400, "invalid_recovery_code")
            self._install_key(tx, user, digest)
            proof["used"] = True
            tx.put("account_action_proofs", proof["id"], proof)
            tx.put("users", user["id"], user)
        return {"recovery_key_configured": True}

    def _recover_actor(self, tx, digest):
        key = tx.get("account_recovery_keys", digest)
        user = tx.get("users", key.get("user_id")) if key else None
        if not self._real(user) or user.get("recovery_key_id") != digest:
            raise AccountLifecycleError("Recovery could not be verified. Check your saved code.", 400, "recovery_unavailable")
        return user

    def recovery_start(self, payload, ip):
        self.phone._ready()
        digest = self._secret(payload.get("recovery_secret"))
        failure = None
        with self.store.transaction() as tx:
            self.phone._prune(tx, self.clock())
            self.phone._consume(tx, self.clock(), [("recovery-ip", self.phone._ip(ip), 600, 20),
                                                   ("recovery-global", "all", 86400, 2000)])
            try:
                user = self._recover_actor(tx, digest)
            except AccountLifecycleError as exc:
                failure = exc
        if failure:
            raise failure
        phone = self.phone._phone(payload.get("new_phone"))
        if phone == user.get("auth_phone"):
            raise AccountLifecycleError("Use a different new phone number.", 400, "recovery_unavailable")
        context = {"user_id": user["id"], "auth_epoch": auth_epoch(user), "recovery_key_id": digest}
        def authorize(tx):
            current = self._recover_actor(tx, digest)
            if not current_actor_matches(current, user):
                raise AccountLifecycleError("Recovery changed. Start again.", 409, "recovery_unavailable")
        return self.phone.start_for({"phone": phone, "flow_token": payload.get("flow_token"),
                    "request_id": payload.get("request_id")}, ip, purpose="account_recovery", context=context, authorize=authorize)

    def _revoke(self, tx, user_id, *, phone_keys=(), except_challenge=None):
        for collection in ("mobile_sessions", "web_sessions", "account_action_proofs", "account_recovery_keys"):
            for row in tx.list(collection):
                if row.get("user_id") == user_id:
                    tx.delete(collection, row["id"])
        removed = set()
        for row in tx.list("phone_challenges"):
            if row["id"] == except_challenge:
                continue
            if row.get("phone_key") in phone_keys or row.get("context", {}).get("user_id") == user_id:
                tx.delete("phone_challenges", row["id"])
                removed.add(row["id"])
        for row in tx.list("phone_send_requests"):
            if row.get("challenge_id") in removed:
                tx.delete("phone_send_requests", row["id"])
        for row in tx.list("trusted_contact_links"):
            if row.get("actor_id") == user_id:
                tx.delete("trusted_contact_links", row["id"])

    def recovery_verify(self, payload, ip, native=False):
        if payload.get("saved") is not True:
            raise AccountLifecycleError("Save your replacement recovery code before continuing.", 400, "recovery_save_required")
        digest = self._secret(payload.get("recovery_secret"))
        replacement = self._secret(payload.get("new_recovery_secret"))
        if digest == replacement:
            raise AccountLifecycleError("Generate and save a new recovery code.", 400, "invalid_recovery_code")

        def authorize(tx, challenge):
            user = self._recover_actor(tx, digest)
            context = challenge.get("context", {})
            if (context.get("user_id") != user["id"] or context.get("auth_epoch") != auth_epoch(user)
                    or context.get("recovery_key_id") != digest):
                raise AccountLifecycleError("Recovery changed. Start again.", 409, "recovery_unavailable")
            return user

        def complete(tx, challenge):
            user = authorize(tx, challenge)
            new_key = challenge["phone_key"]
            if tx.get("phone_identities", new_key) or tx.get("account_recovery_keys", replacement):
                raise AccountLifecycleError("This new phone cannot be used for recovery.", 409, "recovery_unavailable")
            old_keys = [row["id"] for row in tx.list("phone_identities") if row.get("user_id") == user["id"]]
            for key in old_keys:
                tx.put("phone_identities", key, {"id": key, "user_id": user["id"], "status": "replaced"})
            self._revoke(tx, user["id"], phone_keys=[*old_keys, new_key], except_challenge=challenge["id"])
            user.update(auth_epoch=auth_epoch(user) + 1, auth_phone=challenge["phone"], phone=challenge["phone"],
                        phone_verified=True, share_phone=False)
            self._install_key(tx, user, replacement)
            tx.put("users", user["id"], user)
            tx.put("phone_identities", new_key, {"id": new_key, "user_id": user["id"],
                   "phone": challenge["phone"], "status": "active"})
            result = self.mobile_auth.issue_in(tx, user) if native else {"user": account_user(user)}
            result["onboarding_required"] = self.phone.requires_onboarding(user)
            return result
        return self.phone.verify_for(payload, ip, purpose="account_recovery", complete=complete, authorize=authorize)

    def delete(self, actor, payload, session_binding):
        if payload.get("confirm") is not True:
            raise AccountLifecycleError("Explicitly confirm account deletion.")
        try:
            key = payload.get("idempotency_key")
            if not isinstance(key, str) or str(uuid.UUID(key)) != key.lower():
                raise ValueError()
        except (ValueError, AttributeError):
            raise AccountLifecycleError("A deletion request identifier is required.") from None
        with self.store.transaction() as tx:
            user = self._actor(tx, actor, session_binding)
            self._proof(tx, user, session_binding, payload.get("action_token"), "delete")
            blockers = self._blockers(tx, user["id"])
            if blockers:
                raise AccountLifecycleError("Finish active journeys and unresolved payments before deleting this account.",
                                            409, "account_deletion_blocked", blockers=blockers)
            self._erase(tx, user)
            tx.put("account_deletions", user["id"], {"id": user["id"], "deleted_at": _iso(self.clock()),
                   "request_hash": self._hash("delete-request", key), "retained_categories": RETAINED.copy()})
        return {"deleted": True, "retained_categories": RETAINED.copy()}

    def _erase(self, tx, user):
        from .driver_verification import DriverVerificationService
        from .identity_verification import delete_user_evidence
        user_id = user["id"]
        delete_user_evidence(tx, user_id)
        keys = [row["id"] for row in tx.list("phone_identities") if row.get("user_id") == user_id]
        self._revoke(tx, user_id, phone_keys=keys)
        for key in keys:
            tx.put("phone_identities", key, {"id": key, "user_id": user_id, "status": "deleted"})
        for doc in tx.list("driver_documents"):
            if doc.get("user_id") == user_id:
                DriverVerificationService._delete_document(tx, doc["id"])
        for application in tx.list("driver_applications"):
            if application.get("user_id") == user_id:
                tx.put("driver_applications", application["id"], {"id": application["id"], "user_id": user_id,
                       "status": "withdrawn", "version": application.get("version", 0) + 1, "document_consent": False})
        request_ids = {row["id"] for row in tx.list("requests") if row.get("passenger_id") == user_id}
        trip_ids = {row["id"] for row in tx.list("trips") if row.get("driver_id") == user_id}
        for collection, belongs in (
            ("previews", lambda row: row.get("driver_id") == user_id),
            ("requests", lambda row: row.get("passenger_id") == user_id),
            ("matches", lambda row: row.get("request_id") in request_ids or row.get("trip_id") in trip_ids),
            ("messages", lambda row: row.get("sender_id") == user_id),
            ("notifications", lambda row: row.get("recipient_id") == user_id),
        ):
            for row in tx.list(collection):
                if belongs(row):
                    tx.delete(collection, row["id"])
        for collection in ("payout_accounts", "message_limits", "seat_request_limits"):
            tx.delete(collection, user_id)
        for row in tx.list("ratings"):
            if row.get("author_id") == user_id:
                tx.delete("ratings", row["id"])
        own_booking_ids = set()
        for row in tx.list("bookings"):
            if user_id not in {row.get("driver_id"), row.get("passenger_id")}:
                continue
            own_booking_ids.add(row["id"])
            if row.get("driver_id") == user_id:
                row["driver_name"] = "Deleted account"
                match = row.get("match") or {}
                for key in ("vehicle", "verification", "driver_summary"):
                    match.pop(key, None)
                match["driver_name"] = "Deleted account"
                row["match"] = match
            if row.get("passenger_id") == user_id:
                row["passenger_name"] = "Deleted account"
            row.pop("reason", None)
            tx.put("bookings", row["id"], row)
        for row in tx.list("trusted_contact_links"):
            if row.get("booking_id") in own_booking_ids:
                tx.delete("trusted_contact_links", row["id"])
        for row in tx.list("trips"):
            if row.get("driver_id") == user_id:
                row.update(driver_name="Deleted account", driver_vehicle={}, verification={})
                tx.put("trips", row["id"], row)
        # Financial retention is explicit facts only, never authored reasons or
        # nested copies of notes. Receipt rows contain hashes/version/time only.
        event_fields = {"id", "booking_id", "trip_id", "actor_id", "action", "at", "version", "status",
                        "fuel_paise", "toll_paise", "owner_share_paise"}
        def event_facts(event):
            return {key: value for key, value in event.items() if key in event_fields} if isinstance(event, dict) else {}
        payment_fields = {"id", "booking_id", "version", "status", "amount_paise", "currency", "breakdown",
                          "reference", "created_at", "updated_at", "agreed_at", "paid_reported_at",
                          "owner_confirmed_at", "refund_reported_at", "refunded_at", "voided_at", "budget_at_agreement"}
        budget_fields = {"id", "trip_id", "version", "fuel_paise", "toll_paise", "owner_share_paise", "total_paise",
                         "passenger_cap_paise", "declaration", "created_at", "updated_at"}
        for row in tx.list("payments"):
            if row.get("booking_id", row.get("id")) not in own_booking_ids:
                continue
            if row.get("status") in {"unquoted", "proposed"}:
                tx.delete("payments", row["id"])
            else:
                clean = {key: value for key, value in row.items() if key in payment_fields}
                if isinstance(clean.get("breakdown"), dict):
                    clean["breakdown"] = {key: value for key, value in clean["breakdown"].items()
                                          if key in {"fuel_paise", "toll_paise"}}
                if isinstance(clean.get("budget_at_agreement"), dict):
                    clean["budget_at_agreement"] = {key: value for key, value in clean["budget_at_agreement"].items() if key in budget_fields}
                clean["events"] = [event_facts(event) for event in row.get("events", [])]
                tx.put("payments", row["id"], clean)
        for row in tx.list("payment_events"):
            if row.get("booking_id") in own_booking_ids or row.get("actor_id") == user_id:
                tx.put("payment_events", row["id"], event_facts(row))
        for row in tx.list("trip_expense_budgets"):
            if row.get("trip_id", row.get("id")) in trip_ids:
                clean = {key: value for key, value in row.items() if key in budget_fields}
                clean["events"] = [event_facts(event) for event in row.get("events", [])]
                tx.put("trip_expense_budgets", row["id"], clean)
        for row in tx.list("trip_budget_events"):
            if row.get("trip_id") in trip_ids or row.get("actor_id") == user_id:
                tx.put("trip_budget_events", row["id"], event_facts(row))
        tx.put("users", user_id, {"id": user_id, "name": "Deleted account", "role": "member",
               "auth_method": "phone", "account_status": "deleted", "auth_epoch": auth_epoch(user) + 1,
               "development": False, "driver_approved": False, "deleted_at": _iso(self.clock())})
