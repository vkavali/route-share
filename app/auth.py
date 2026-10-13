"""Shared current-account eligibility, independent of authentication method."""


def is_active_account(record):
    """Legacy accounts remain active; explicit restrictions always fail closed."""
    return (isinstance(record, dict)
            and record.get("account_status", "active") == "active"
            and record.get("status", "active") == "active"
            and record.get("disabled") is not True
            and record.get("suspended") is not True
            and record.get("is_active") is not False)


def auth_epoch(record):
    value = record.get("auth_epoch", 0) if isinstance(record, dict) else None
    return value if type(value) is int and 0 <= value < 2**53 else None


def current_actor_matches(record, snapshot):
    return (is_active_account(record) and isinstance(snapshot, dict)
            and record.get("id") == snapshot.get("id")
            and auth_epoch(record) is not None and auth_epoch(record) == auth_epoch(snapshot))


def web_session_hash(session_id):
    import hashlib
    if not isinstance(session_id, str) or not 32 <= len(session_id) <= 256:
        return None
    return hashlib.sha256(session_id.encode()).hexdigest()


def issue_web_session_in(tx, user, session_id, *, at=None):
    """Root generates cookie ID; persist its hash, never the cookie capability."""
    import time
    at = time.time() if at is None else at
    digest = web_session_hash(session_id)
    if not digest or not is_active_account(user) or auth_epoch(user) is None:
        raise ValueError("Cannot create an account session")
    for row in tx.list("web_sessions"):
        if row.get("expires_at", 0) <= at:
            tx.delete("web_sessions", row["id"])
    tx.put("web_sessions", digest, {"id": digest, "user_id": user["id"],
           "auth_epoch": auth_epoch(user), "expires_at": at + 8 * 3600})
    return "web:" + digest


def session_binding_matches_in(tx, user, binding, *, at=None):
    import time
    from datetime import datetime
    at = time.time() if at is None else at
    if not is_active_account(user) or auth_epoch(user) is None or not isinstance(binding, str):
        return False
    kind, _, digest = binding.partition(":")
    if kind not in {"web", "native"} or len(digest) != 64:
        return False
    row = tx.get("web_sessions" if kind == "web" else "mobile_sessions", digest)
    if not row or row.get("user_id") != user.get("id") or auth_epoch(row) != auth_epoch(user):
        return False
    expiry = row.get("expires_at")
    try:
        expiry = datetime.fromisoformat(expiry).timestamp() if kind == "native" else float(expiry)
        return expiry > at
    except (TypeError, ValueError, OverflowError):
        return False


def revoke_web_session_in(tx, session_id):
    digest = web_session_hash(session_id)
    if digest:
        tx.delete("web_sessions", digest)
