"""Private expense agreements and manual UPI acknowledgements, never settlement.

Disabled by default. No bank API, callbacks, refunds, or transfer verification are
implemented here. Quote fields and payment events never enter public trip records.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

from .permissions import can_drive, has_current_identity_review
from .auth import current_actor_matches, is_active_account


class PaymentError(Exception):
    def __init__(self, message, status=400, code="payment_invalid"):
        super().__init__(message)
        self.status, self.code = status, code


KEY = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
UPI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,255}@[A-Za-z][A-Za-z0-9.-]{1,63}$")
MAX_PAISE = 10_000_000  # Input bound, not a fare, provider limit, or approved price.
RECONCILIATION = {"report_paid", "confirm_received", "dispute", "request_refund", "report_refund", "confirm_refund", "void_unpaid"}
TRANSITIONS = {
    "void_unpaid": ({"agreed"}, "driver", "voided_unpaid"),
    "agree": ({"proposed"}, "passenger", "agreed"),
    # An owner's unpaid claim cannot erase a transfer made before cancellation.
    # Reopening restores the reserved amount and blocks further collection when
    # the cap is exceeded; it never initiates a new transfer.
    "report_paid": ({"agreed", "voided_unpaid"}, "passenger", "passenger_reported"),
    "confirm_received": ({"passenger_reported"}, "driver", "owner_confirmed"),
    "dispute": ({"agreed", "passenger_reported", "owner_confirmed", "refund_requested", "refund_reported"}, "either", "disputed"),
    "request_refund": ({"passenger_reported", "owner_confirmed", "disputed"}, "passenger", "refund_requested"),
    "report_refund": ({"refund_requested", "disputed"}, "driver", "refund_reported"),
    "confirm_refund": ({"refund_reported"}, "passenger", "refunded"),
}


def _integer(value, name, minimum=0, maximum=MAX_PAISE):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PaymentError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def _text(value, name, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise PaymentError(f"Enter a valid {name}.")
    value = value.strip()
    if required and not value:
        raise PaymentError(f"Enter a valid {name}.")
    return value


class PaymentService:
    def __init__(self, store, enabled=False):
        self.store = store
        self.enabled = enabled is True

    def dispatch(self, action, user, payload):
        methods = {"payments": self._payments, "payment": self._payment,
                   "payment_action": self._payment_action, "payout_account": self._payout_account,
                   "trip_budget": self._trip_budget, "trip_budget_action": self._trip_budget_action}
        if action not in methods:
            raise PaymentError("Unknown payment action.", 404, "not_found")
        if not isinstance(payload, dict):
            raise PaymentError("A JSON object is required.")
        return methods[action](user, payload)

    @staticmethod
    def _actor(tx, user):
        actor = tx.get("users", user.get("id", ""))
        if not current_actor_matches(actor, user) or actor.get("role") != "member":
            raise PaymentError("Payments are available only to booking participants.", 403, "not_participant")
        return actor

    @staticmethod
    def _booking(tx, booking_id, actor):
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise PaymentError("A booking is required.")
        booking = tx.get("bookings", booking_id)
        if not booking or actor["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
            raise PaymentError("This payment is not available to this account.", 403, "not_participant")
        return booking

    @staticmethod
    def _eligible(tx, booking):
        a, b = booking.get("driver_id", ""), booking.get("passenger_id", "")
        trip = tx.get("trips", booking.get("trip_id", "")) or {}
        return (booking.get("status") in {"accepted", "segment_completed"}
                and trip.get("status") in {"published", "started", "completed"}
                and not tx.get("blocks", a + ":" + b) and not tx.get("blocks", b + ":" + a))

    @staticmethod
    def _new(booking):
        return {"id": booking["id"], "booking_id": booking["id"], "version": 0, "status": "unquoted",
                "amount_paise": None, "currency": "INR", "breakdown": None, "note": "",
                "reference": None, "events": []}

    @staticmethod
    def _individual(user):
        return (is_active_account(user) and user.get("role") == "member"
                and user.get("development") is False and user.get("auth_method") == "phone"
                and user.get("phone_verified") is True and isinstance(user.get("auth_phone"), str)
                and re.fullmatch(r"\+91[6-9][0-9]{9}", user["auth_phone"]) is not None)

    @classmethod
    def _reviewed_owner(cls, user):
        approval = user.get("driver_approval")
        return (cls._individual(user) and isinstance(approval, dict) and approval.get("kind") == "reviewed"
                and can_drive(user))

    def _collection_identity_reason(self, tx, booking):
        driver = tx.get("users", booking.get("driver_id", "")) or {}
        passenger = tx.get("users", booking.get("passenger_id", "")) or {}
        if not self._individual(driver) or not self._individual(passenger):
            return "verified_individual_accounts_required"
        if not has_current_identity_review(driver) or not has_current_identity_review(passenger):
            return "identity_review_required"
        if not self._reviewed_owner(driver):
            return "reviewed_driver_required"
        if not self._eligible(tx, booking):
            return "booking_ineligible"
        trip = tx.get("trips", booking.get("trip_id", "")) or {}
        vehicle = driver.get("vehicle") or {}
        planned_vehicle = trip.get("driver_vehicle") or {}
        if any(vehicle.get(k, "") != planned_vehicle.get(k, "") for k in ("model", "plate")):
            return "driver_vehicle_changed"
        return None

    def _collectible(self, tx, booking):
        return self._collection_identity_reason(tx, booking) is None

    @staticmethod
    def _quote_matches(booking, amount):
        quote = booking.get("price_quote")
        if quote is None:
            return True  # Legacy expense agreements have no advertised fare.
        return (isinstance(quote, dict) and quote.get("currency") == "INR"
                and type(quote.get("amount_paise")) is int
                and quote["amount_paise"] >= 0 and quote["amount_paise"] == amount)

    @classmethod
    def _require_booking_quote(cls, booking, amount):
        if not cls._quote_matches(booking, amount):
            raise PaymentError("The payment total must match the fare saved with this booking.",
                               409, "booking_price_mismatch")

    def _collection_eligibility(self, tx, booking, payment):
        reason = "payments_disabled" if not self.enabled else self._collection_identity_reason(tx, booking)
        if reason is None and payment["status"] in {"voided_unpaid", "refunded"}:
            reason = "payment_closed"
        if reason is None and payment.get("agreed_at") and not self._quote_matches(booking, payment.get("amount_paise")):
            reason = "booking_price_mismatch"
        if reason is None and not tx.get("trip_expense_budgets", booking["trip_id"]):
            reason = "trip_budget_required"
        if reason is None and not self._budget_available(tx, booking["trip_id"]):
            reason = "expense_cap_exceeded"
        return {"eligible": reason is None, "reason": reason}

    @staticmethod
    def _reserved(tx, trip_id, exclude_booking=None):
        bookings = {b["id"]: b for b in tx.list("bookings")}
        total = 0
        for payment in tx.list("payments"):
            if payment.get("booking_id") == exclude_booking:
                continue
            linked_trip = payment.get("trip_id") or bookings.get(payment.get("booking_id"), {}).get("trip_id")
            if linked_trip != trip_id or payment.get("status") in {"unquoted", "refunded", "voided_unpaid"}:
                continue
            # Include proposals and legacy agreements, disputed and refund-pending
            # amounts. A refund claim is not a recipient-confirmed refund.
            amount = payment.get("amount_paise")
            if type(amount) is not int or not 1 <= amount <= MAX_PAISE:
                raise PaymentError("Expense history needs reconciliation.", 409, "budget_history_invalid")
            total += amount
        return total

    def _budget_view(self, tx, trip_id):
        budget = tx.get("trip_expense_budgets", trip_id)
        if not budget:
            return None
        keys = ("trip_id", "version", "fuel_paise", "toll_paise", "owner_share_paise", "total_paise",
                "passenger_cap_paise", "declaration", "events", "created_at", "updated_at")
        result = {key: budget[key] for key in keys}
        reserved = self._reserved(tx, trip_id)
        return {**result, "reserved_paise": reserved,
                "remaining_paise": max(0, budget["passenger_cap_paise"] - reserved)}

    def _budget_available(self, tx, trip_id):
        budget = tx.get("trip_expense_budgets", trip_id)
        return bool(budget and self._reserved(tx, trip_id) <= budget["passenger_cap_paise"])

    @staticmethod
    def _trip_for_budget(tx, trip_id, actor):
        if not isinstance(trip_id, str) or not trip_id or len(trip_id) > 128:
            raise PaymentError("A trip is required.")
        trip = tx.get("trips", trip_id)
        if not trip:
            raise PaymentError("This expense budget is not available.", 403, "not_participant")
        if actor["id"] != trip.get("driver_id"):
            participant = any(b.get("trip_id") == trip_id and b.get("passenger_id") == actor["id"]
                              and (b.get("status") in {"accepted", "segment_completed"}
                                   or tx.get("payments", b["id"])) for b in tx.list("bookings"))
            if not participant:
                raise PaymentError("This expense budget is not available.", 403, "not_participant")
        return trip

    def _budget_eligibility(self, trip, actor):
        reason = None
        if not self.enabled:
            reason = "payments_disabled"
        elif actor["id"] != trip.get("driver_id"):
            reason = "trip_owner_required"
        elif not self._individual(actor):
            reason = "verified_individual_accounts_required"
        elif not has_current_identity_review(actor):
            reason = "identity_review_required"
        elif not self._reviewed_owner(actor):
            reason = "reviewed_driver_required"
        elif trip.get("status") not in {"published", "started", "completed"}:
            reason = "booking_ineligible"
        return {"eligible": reason is None, "reason": reason}

    def _can_manage_budget(self, trip, actor):
        return self._budget_eligibility(trip, actor)["eligible"]

    def _budget_response(self, tx, trip, actor):
        can_set = self._can_manage_budget(trip, actor)
        return {"budget": self._budget_view(tx, trip["id"]),
                "allowed_actions": ["set_budget"] if can_set else [], "enabled": self.enabled,
                "eligibility": self._budget_eligibility(trip, actor)}

    def _trip_budget(self, user, payload):
        with self.store.read() as tx:
            actor = self._actor(tx, user)
            trip = self._trip_for_budget(tx, payload.get("trip_id"), actor)
            return self._budget_response(tx, trip, actor)

    def _trip_budget_action(self, user, payload):
        if not self.enabled:
            raise PaymentError("Direct UPI expense agreements are not enabled.", 403, "payments_disabled")
        if payload.get("action") != "set_budget":
            raise PaymentError("Unknown expense budget action.")
        version = _integer(payload.get("expected_version"), "expected_version", maximum=2**31-1)
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise PaymentError("A valid idempotency key is required.")
        try:
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            raise PaymentError("Invalid expense budget request.") from None
        with self.store.transaction() as tx:
            actor = self._actor(tx, user)
            trip = self._trip_for_budget(tx, payload.get("trip_id"), actor)
            response = self._budget_response(tx, trip, actor)
            if "set_budget" not in response["allowed_actions"]:
                raise PaymentError("Only the approved trip owner can declare expenses.", 403, "driver_required")
            record = tx.get("trip_expense_budgets", trip["id"])
            receipt_id = hashlib.sha256(f"{actor['id']}:{key}".encode()).hexdigest()
            receipt = tx.get("trip_budget_receipts", receipt_id)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise PaymentError("This idempotency key was used for a different request.", 409, "idempotency_conflict")
                return {**response, "replayed": True, "applied_version": receipt["version"]}
            if version != (record["version"] if record else 0):
                raise PaymentError("Expense budget changed. Refresh before trying again.", 409, "version_conflict")
            fuel = _integer(payload.get("fuel_paise"), "fuel_paise")
            toll = _integer(payload.get("toll_paise"), "toll_paise")
            total = _integer(fuel + toll, "total_paise", 1)
            owner_share = _integer(payload.get("owner_share_paise"), "owner_share_paise", 1, total)
            reason = _text(payload.get("reason"), "reason", 240, True)
            cap = total - owner_share
            if self._reserved(tx, trip["id"]) > cap:
                raise PaymentError("Existing expense reservations exceed this passenger cap.", 409, "expense_cap_exceeded")
            stamp = datetime.now(timezone.utc).isoformat()
            event = {"id": uuid.uuid4().hex, "trip_id": trip["id"], "actor_id": actor["id"],
                     "action": "set_budget", "version": version + 1, "at": stamp, "reason": reason,
                     "fuel_paise": fuel, "toll_paise": toll, "owner_share_paise": owner_share}
            record = {"id": trip["id"], "trip_id": trip["id"], "version": version + 1,
                      "fuel_paise": fuel, "toll_paise": toll, "owner_share_paise": owner_share,
                      "total_paise": total, "passenger_cap_paise": cap, "declaration": "owner_declared_unverified",
                      "created_at": record["created_at"] if record else stamp, "updated_at": stamp,
                      "events": [*(record["events"] if record else []), event]}
            tx.put("trip_expense_budgets", trip["id"], record)
            tx.put("trip_budget_events", event["id"], event)
            tx.put("trip_budget_receipts", receipt_id, {"id": receipt_id, "fingerprint": fingerprint,
                                                      "version": record["version"], "created_at": stamp})
            return {**self._budget_response(tx, trip, actor), "replayed": False, "applied_version": record["version"]}

    @staticmethod
    def _can_void(tx, booking, payment):
        trip = tx.get("trips", booking.get("trip_id", "")) or {}
        terminal = (booking.get("status") in {"cancelled", "declined", "segment_completed"}
                    or trip.get("status") in {"cancelled", "completed"})
        return terminal and payment["status"] == "agreed" and not payment.get("paid_reported_at")

    def _allowed(self, tx, booking, actor, payment):
        if not self.enabled:
            return []
        role = "driver" if actor["id"] == booking["driver_id"] else "passenger"
        eligible = self._eligible(tx, booking)
        collectible = self._collectible(tx, booking)
        actions = []
        if collectible and self._budget_available(tx, booking["trip_id"]) and role == "driver" and payment["status"] in {"unquoted", "proposed"}:
            budget = tx.get("trip_expense_budgets", booking["trip_id"])
            if self._reserved(tx, booking["trip_id"], booking["id"]) < budget["passenger_cap_paise"]:
                actions.append("propose")
        for action, (states, who, _) in TRANSITIONS.items():
            if payment["status"] in states and who in {role, "either"} and (eligible or action in RECONCILIATION):
                if action == "agree" and not collectible:
                    continue
                if action == "agree" and not self._budget_available(tx, booking["trip_id"]):
                    continue
                if action == "void_unpaid" and not self._can_void(tx, booking, payment):
                    continue
                # A dispute about an unpaid agreement does not establish money to refund.
                if action in {"request_refund", "report_refund"} and not payment.get("paid_reported_at"):
                    continue
                actions.append(action)
        return actions

    def _view(self, tx, booking, actor, record):
        payment = record or self._new(booking)
        keys = ("booking_id", "version", "status", "amount_paise", "currency", "breakdown", "note",
                "reference", "events", "created_at", "updated_at", "agreed_at", "paid_reported_at",
                "owner_confirmed_at", "refund_reported_at", "refunded_at", "voided_at", "void_reason", "budget_at_agreement")
        view = {key: payment[key] for key in keys if key in payment}
        eligibility = self._collection_eligibility(tx, booking, payment)
        view.update(can_manage_budget=self._can_manage_budget(tx.get("trips", booking["trip_id"]) or {}, actor),
                    trip_id=booking["trip_id"], budget=self._budget_view(tx, booking["trip_id"]), payee_name=None, upi_id=None, upi_uri=None, verification="manual_only",
                    allowed_actions=self._allowed(tx, booking, actor, payment),
                    collection_available=eligibility["eligible"], collection_eligibility=eligibility)
        eligible = self._eligible(tx, booking)
        # Payee snapshot is disclosed only after agreement, while the pair remains eligible.
        if self.enabled and eligible and payment.get("agreed_at") and (view["collection_available"] or payment.get("paid_reported_at")):
            view["payee_name"] = payment.get("payee_name")
            view["upi_id"] = payment.get("upi_id")
            # Never offer another transfer once a passenger reports one.
            if payment["status"] == "agreed" and view["collection_available"] and "report_paid" in view["allowed_actions"]:
                amount = payment["amount_paise"]
                view["upi_uri"] = "upi://pay?" + urlencode({"pa": payment["upi_id"], "pn": payment["payee_name"],
                    "am": f"{amount // 100}.{amount % 100:02d}", "cu": "INR",
                    "tn": "Shared trip expense", "tr": payment["reference"]}, quote_via=quote)
        return view

    def _payments(self, user, payload):
        with self.store.read() as tx:
            actor = self._actor(tx, user)
            rows = []
            for booking in tx.list("bookings"):
                if actor["id"] not in {booking.get("driver_id"), booking.get("passenger_id")}:
                    continue
                record = tx.get("payments", booking["id"])
                if record or self._eligible(tx, booking):
                    rows.append(self._view(tx, booking, actor, record))
            return {"payments": rows, "enabled": self.enabled}

    def _payment(self, user, payload):
        with self.store.read() as tx:
            actor = self._actor(tx, user)
            booking = self._booking(tx, payload.get("booking_id"), actor)
            return {"payment": self._view(tx, booking, actor, tx.get("payments", booking["id"])), "enabled": self.enabled}

    def _payout_account(self, user, payload):
        with self.store.read() as tx:
            actor = self._actor(tx, user)
            if not can_drive(actor):
                raise PaymentError("Current driver approval is required.", 403, "driver_required")
            record = tx.get("payout_accounts", actor["id"])
            account = {key: record[key] for key in ("payee_name", "upi_id", "updated_at")} if record else None
            return {"payout_account": account, "enabled": self.enabled}

    def _payment_action(self, user, payload):
        if not self.enabled:
            raise PaymentError("Direct UPI expense agreements are not enabled.", 403, "payments_disabled")
        action = payload.get("action")
        if not isinstance(action, str) or action not in {"propose", *TRANSITIONS}:
            raise PaymentError("Unknown payment action.")
        version = _integer(payload.get("expected_version"), "expected_version", maximum=2**31-1)
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise PaymentError("A valid idempotency key is required.")
        try:
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            raise PaymentError("Invalid payment request.") from None
        with self.store.transaction() as tx:
            actor = self._actor(tx, user)
            booking = self._booking(tx, payload.get("booking_id"), actor)
            record = tx.get("payments", booking["id"]) or self._new(booking)
            receipt_id = hashlib.sha256(f"{actor['id']}:{key}".encode()).hexdigest()
            receipt = tx.get("payment_receipts", receipt_id)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise PaymentError("This idempotency key was used for a different request.", 409, "idempotency_conflict")
                return {"payment": self._view(tx, booking, actor, record), "enabled": True,
                        "replayed": True, "applied_version": receipt["version"]}
            if version != record["version"]:
                raise PaymentError("Payment changed. Refresh it before trying again.", 409, "version_conflict")
            if action not in self._allowed(tx, booking, actor, record):
                raise PaymentError("This action is not available for this booking and payment state.", 409, "payment_action_unavailable")
            stamp = datetime.now(timezone.utc).isoformat()
            if action == "propose":
                amount = _integer(payload.get("amount_paise"), "amount_paise", 1)
                self._require_booking_quote(booking, amount)
                breakdown = payload.get("breakdown")
                if not isinstance(breakdown, dict) or set(breakdown) != {"fuel_paise", "toll_paise"}:
                    raise PaymentError("Specify fuel_paise and toll_paise only.")
                breakdown = {k: _integer(v, k) for k, v in breakdown.items()}
                if sum(breakdown.values()) != amount:
                    raise PaymentError("Fuel and toll amounts must equal the proposed total.")
                budget = tx.get("trip_expense_budgets", booking["trip_id"])
                if not budget or self._reserved(tx, booking["trip_id"], booking["id"]) + amount > budget["passenger_cap_paise"]:
                    raise PaymentError("This quote exceeds the trip passenger expense cap.", 409, "expense_cap_exceeded")
                name = _text(payload.get("payee_name"), "payee name", 80, True)
                upi = _text(payload.get("upi_id"), "UPI ID", 320, True)
                if not UPI.fullmatch(upi):
                    raise PaymentError("Enter a valid UPI ID, not a URL.", code="invalid_upi")
                record.update(amount_paise=amount, breakdown=breakdown, note=_text(payload.get("note", ""), "note", 240),
                              payee_name=name, upi_id=upi, status="proposed")
                if not record["reference"]:
                    record["reference"] = "RS" + uuid.uuid4().hex
                tx.put("payout_accounts", actor["id"], {"id": actor["id"], "payee_name": name, "upi_id": upi, "updated_at": stamp})
            else:
                if action == "void_unpaid":
                    record["void_reason"] = _text(payload.get("reason"), "reason", 240, True)
                if action == "agree":
                    self._require_booking_quote(booking, record["amount_paise"])
                    budget = tx.get("trip_expense_budgets", booking["trip_id"])
                    record["budget_at_agreement"] = {k: budget[k] for k in
                        ("version", "fuel_paise", "toll_paise", "owner_share_paise", "passenger_cap_paise", "declaration")}
                record["status"] = TRANSITIONS[action][2]
                timestamps = {"agree": "agreed_at", "report_paid": "paid_reported_at", "confirm_received": "owner_confirmed_at",
                              "report_refund": "refund_reported_at", "confirm_refund": "refunded_at", "void_unpaid": "voided_at"}
                if action in timestamps:
                    record[timestamps[action]] = stamp
            record["trip_id"] = booking["trip_id"]
            record["version"] += 1
            record.setdefault("created_at", stamp)
            record["updated_at"] = stamp
            event = {"id": uuid.uuid4().hex, "booking_id": booking["id"], "actor_id": actor["id"],
                     "action": action, "at": stamp, "version": record["version"], "status": record["status"]}
            if action == "void_unpaid":
                event["reason"] = record["void_reason"]
            record["events"] = [*record["events"], event]
            tx.put("payment_events", event["id"], event)
            tx.put("payments", booking["id"], record)
            tx.put("payment_receipts", receipt_id, {"id": receipt_id, "fingerprint": fingerprint,
                                                    "version": record["version"], "created_at": stamp})
            return {"payment": self._view(tx, booking, actor, record), "enabled": True, "replayed": False,
                    "applied_version": record["version"]}
