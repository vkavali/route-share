"""Persisted account permissions for closed-beta service actions."""

from __future__ import annotations

from datetime import datetime, timezone


STAFF_CAPABILITIES = frozenset({"ops.read", "verify.review", "safety.act", "staff.manage"})
DRIVER_ACTIONS = frozenset({"preview", "publish", "accept", "start_trip"})
TRAVEL_ACTIONS = frozenset({
    "preview", "publish", "search", "request", "accept", "decline", "cancel_booking",
    "start_trip", "complete_segment", "complete_trip", "cancel_trip", "rate", "block_person",
    "board_segment",
})


class PermissionDenied(Exception):
    """An authenticated account is not allowed to perform the requested action."""


def _approval_expiry(user: dict) -> datetime | None:
    approval = user.get("driver_approval")
    if not user.get("driver_approved") or not isinstance(approval, dict):
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
    if user.get("role") != "member":
        return False
    approval = user.get("driver_approval")
    expiry = _approval_expiry(user)
    if expiry is None or expiry <= (at or datetime.now(timezone.utc)):
        return False
    kind = approval.get("kind")
    if kind == "development":
        return user.get("development") is True
    if kind == "reviewed":
        verification = user.get("verification") or {}
        return verification.get("dl") == "verified" and verification.get("rc") == "verified"
    return False


def access_summary(user: dict, at: datetime | None = None) -> dict:
    is_staff = user.get("role") == "staff"
    grants = user.get("staff_capabilities", []) if is_staff else []
    capabilities = sorted({value for value in grants if isinstance(value, str) and value in STAFF_CAPABILITIES}) if isinstance(grants, (list, tuple, set)) else []
    return {"is_staff": is_staff, "can_drive": can_drive(user, at), "staff_capabilities": capabilities}


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
    if action in DRIVER_ACTIONS and not access["can_drive"]:
        raise PermissionDenied("Current driver approval is required for this action.")
    if action in TRAVEL_ACTIONS and role != "member":
        raise PermissionDenied("This action is available only to member accounts.")
