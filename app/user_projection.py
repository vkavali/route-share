"""Explicit account DTOs; private evidence and payment data never belong here."""

from .permissions import access_summary, identity_review_summary
from .auth import auth_epoch


def account_user(record):
    result = {key: record[key] for key in (
        "id", "name", "role", "development", "driver_approved", "phone", "share_phone",
    ) if key in record}
    result["access"] = access_summary(record)
    result["identity_review"] = identity_review_summary(record)
    result["phone_verified"] = record.get("phone_verified") is True
    result["onboarding_required"] = record.get("onboarding_required") is True
    result["auth_epoch"] = auth_epoch(record)
    result["staff_capabilities"] = result["access"]["staff_capabilities"]
    vehicle = record.get("vehicle")
    result["vehicle"] = {key: vehicle[key] for key in ("model", "plate") if key in vehicle} if isinstance(vehicle, dict) else {}
    verification = record.get("verification")
    states = {"not_checked", "pending", "verified", "rejected", "expired"}
    result["verification"] = {key: verification.get(key) if isinstance(verification, dict) and isinstance(verification.get(key), str) and verification[key] in states else "not_checked"
                              for key in ("phone", "identity", "dl", "rc", "insurance", "selfie")}
    result["verification"]["identity"] = {"reviewed": "verified", "expired": "expired"}.get(result["identity_review"]["status"], "not_checked")
    approval = record.get("driver_approval")
    result["driver_approval"] = None
    if isinstance(approval, dict):
        result["driver_approval"] = {key: approval[key] for key in ("kind", "expires_at", "review_scope") if key in approval}
        dates = approval.get("document_expiries")
        if isinstance(dates, dict):
            result["driver_approval"]["document_expiries"] = {key: dates[key] for key in ("dl", "rc", "insurance") if isinstance(dates.get(key), str)}
    return result


def operations_user(record):
    own = account_user(record)
    return {key: own[key] for key in (
        "id", "name", "role", "development", "driver_approved", "access", "staff_capabilities",
        "verification", "driver_approval", "identity_review",
    ) if key in own}
