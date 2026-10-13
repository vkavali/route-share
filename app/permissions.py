"""Persisted account permissions for closed-beta service actions."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re

from .auth import is_active_account


STAFF_CAPABILITIES = frozenset({"ops.read", "verify.review", "safety.act", "staff.manage"})
DRIVER_ACTIONS = frozenset({"preview", "publish", "accept", "start_trip"})
TRAVEL_ACTIONS = frozenset({
    "preview", "publish", "search", "request", "accept", "decline", "cancel_booking",
    "start_trip", "complete_segment", "complete_trip", "cancel_trip", "rate", "block_person",
    "board_segment",
})


class PermissionDenied(Exception):
    """An authenticated account is not allowed to perform the requested action."""


def has_verified_phone(user: dict) -> bool:
    return (is_active_account(user) and user.get("role") == "member"
            and user.get("development") is False and user.get("auth_method") == "phone"
            and user.get("phone_verified") is True and isinstance(user.get("auth_phone"), str)
            and re.fullmatch(r"\+91[6-9][0-9]{9}", user["auth_phone"]) is not None)


def _identity_dates(user):
    approval = user.get("identity_approval")
    if (not isinstance(approval, dict) or approval.get("kind") != "human_document_review"
            or approval.get("source") not in ("identity_application", "driver_application")
            or not isinstance(approval.get("application_id"), str)
            or not 1 <= len(approval["application_id"]) <= 128):
        return None
    try:
        reviewed = datetime.fromisoformat(approval["reviewed_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError):
        return None
    try:
        valid = reviewed.tzinfo is not None and expires.tzinfo is not None and reviewed < expires <= reviewed + timedelta(days=365)
    except (OverflowError, TypeError):
        return None
    if not valid:
        return None
    return reviewed.astimezone(timezone.utc), expires.astimezone(timezone.utc)


def has_current_identity_review(user: dict, at: datetime | None = None) -> bool:
    if not is_active_account(user) or user.get("role") != "member" or user.get("development") is not False:
        return False
    dates = _identity_dates(user)
    current = at or datetime.now(timezone.utc)
    return bool(dates and dates[0] <= current < dates[1])


def identity_review_summary(user: dict, at: datetime | None = None) -> dict:
    current = at or datetime.now(timezone.utc)
    if user.get("development") is True:
        return {"status": "development", "method": None, "expires_at": None}
    if has_current_identity_review(user, current):
        return {"status": "reviewed", "method": "human_document_review", "expires_at": _identity_dates(user)[1].isoformat()}
    dates = _identity_dates(user)
    if dates and dates[1] <= current and user.get("development") is False:
        return {"status": "expired", "method": "human_document_review", "expires_at": dates[1].isoformat()}
    return {"status": "not_checked", "method": None, "expires_at": None}


def can_request(user: dict, at: datetime | None = None) -> bool:
    if not is_active_account(user) or user.get("role") != "member":
        return False
    # Domain's persisted same-account-pool check isolates these test accounts.
    return user.get("development") is True or (has_verified_phone(user) and has_current_identity_review(user, at))


def _approval_expiry(user: dict) -> datetime | None:
    approval = user.get("driver_approval")
    if user.get("driver_approved") is not True or not isinstance(approval, dict):
        return None
    raw = approval.get("expires_at")
    if not isinstance(raw, str):
        return None
    try:
        expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if expiry.tzinfo is None:
        return None
    return expiry.astimezone(timezone.utc)


def can_drive(user: dict, at: datetime | None = None) -> bool:
    """True only for a currently approved member with a valid approval record."""
    if not is_active_account(user) or user.get("role") != "member":
        return False
    approval = user.get("driver_approval")
    expiry = _approval_expiry(user)
    if expiry is None or expiry <= (at or datetime.now(timezone.utc)):
        return False
    kind = approval.get("kind")
    development = kind == "development" and user.get("development") is True
    if kind == "development" and approval.get("review_scope") != "human_document_review":
        return development
    if kind == "reviewed" or development:
        if not development and (not has_verified_phone(user) or not has_current_identity_review(user, at)):
            return False
        verification = user.get("verification")
        if not isinstance(verification, dict):
            return False
        if any(verification.get(key) != "verified" for key in ("dl", "rc", "insurance", "selfie", "identity")):
            return False
        expiries = approval.get("document_expiries")
        if not isinstance(expiries, dict):
            return False
        current = at or datetime.now(timezone.utc)
        for kind in ("dl", "rc", "insurance"):
            raw = expiries.get(kind)
            if not isinstance(raw, str):
                return False
            try:
                document_expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return False
            if document_expiry.tzinfo is None or document_expiry <= current:
                return False
        return True
    return False


def access_summary(user: dict, at: datetime | None = None) -> dict:
    is_staff = user.get("role") == "staff"
    grants = user.get("staff_capabilities", []) if is_staff else []
    capabilities = sorted({value for value in grants if isinstance(value, str) and value in STAFF_CAPABILITIES}) if isinstance(grants, (list, tuple, set)) else []
    return {"is_staff": is_staff, "can_drive": can_drive(user, at), "can_request": can_request(user, at), "staff_capabilities": capabilities}


def authorize(user: dict, action: str, at: datetime | None = None) -> None:
    role = user.get("role")
    access = access_summary(user, at)
    if action == "operations":
        if not access["is_staff"] or "ops.read" not in access["staff_capabilities"]:
            raise PermissionDenied("Operations access is not granted.")
        return
    if action == "resolve_report":
        if not access["is_staff"] or "safety.act" not in access["staff_capabilities"]:
            raise PermissionDenied("Safety report resolution is not granted.")
        return
    if role == "staff" and action in TRAVEL_ACTIONS:
        raise PermissionDenied("Staff accounts cannot change travel bookings.")
    if action == "request" and not access["can_request"]:
        raise PermissionDenied("Current identity review and verified phone sign-in are required to request a seat.")
    if action in DRIVER_ACTIONS and not access["can_drive"]:
        raise PermissionDenied("Current driver approval is required for this action.")
    if action in TRAVEL_ACTIONS and role != "member":
        raise PermissionDenied("This action is available only to member accounts.")
