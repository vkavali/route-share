"""Short-lived, revocable bearer snapshots for a trusted contact.

The link intentionally carries a small trip summary only. It is not an account,
chat, phone-number, or live-location sharing mechanism.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeSerializer


UTC = timezone.utc
MAX_LINK_SECONDS = 24 * 60 * 60
LINK_COLLECTION = "trusted_contact_links"
TOKEN_VERSION = 1


class TrustedContactError(Exception):
    """Service error carrying an HTTP-compatible status and stable code."""

    def __init__(self, message: str, status: int = 400, code: str = "trusted_contact_invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class TrustedContactService:
    """Create/read/revoke one-time-returned signed links using an existing Store."""

    def __init__(self, store, signing_secret: str | bytes, now=None):
        if not signing_secret:
            raise ValueError("A non-empty signing secret is required")
        self.store = store
        self._serializer = URLSafeSerializer(signing_secret, salt="trusted-contact-snapshot-v1")
        self._now = now or (lambda: datetime.now(UTC))
        self._hash_key = signing_secret.encode() if isinstance(signing_secret, str) else signing_secret

    def _current_time(self) -> datetime:
        value = self._now()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _blocked(tx, first: str, second: str) -> bool:
        return bool(tx.get("blocks", first + ":" + second) or tx.get("blocks", second + ":" + first))

    @staticmethod
    def _end_at(booking: dict, trip: dict) -> datetime | None:
        match = booking.get("match") or {}
        end = _parse(match.get("dropoff_at"))
        if end is not None:
            return end
        departure = _parse(trip.get("departure"))
        route = trip.get("current_route") or trip.get("route") or {}
        duration = route.get("duration_s")
        if departure is None or isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return None
        detour = trip.get("max_detour_minutes", 0)
        if isinstance(detour, bool) or not isinstance(detour, (int, float)):
            detour = 0
        return departure + timedelta(seconds=max(0, duration) + max(0, detour) * 60)

    @staticmethod
    def _payload_value(payload, key):
        return payload.get(key) if isinstance(payload, dict) else None

    def create_snapshot_link(self, user, payload):
        """Return a bearer token exactly once after validating an active booking."""
        booking_id = self._payload_value(payload, "booking_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise TrustedContactError("A booking is required.", code="invalid_booking")
        alias = self._payload_value(payload, "alias")
        if alias is not None:
            if not isinstance(alias, str) or len(alias.strip()) > 80:
                raise TrustedContactError("Contact label must be 80 characters or fewer.", code="invalid_alias")
            alias = alias.strip() or None

        actor_id = user.get("id") if isinstance(user, dict) else None
        if not actor_id:
            raise TrustedContactError("Sign in to create a trusted-contact link.", 401, "unauthenticated")
        now = self._current_time()
        with self.store.transaction() as tx:
            booking = tx.get("bookings", booking_id)
            if not booking or actor_id not in {booking.get("driver_id"), booking.get("passenger_id")}:
                raise TrustedContactError("This booking is unavailable to this account.", 403, "not_participant")
            trip = tx.get("trips", booking.get("trip_id"))
            if not trip:
                raise TrustedContactError("This journey is no longer available.", 410, "link_unavailable")
            counterpart_id = booking["passenger_id"] if actor_id == booking["driver_id"] else booking["driver_id"]
            if self._blocked(tx, actor_id, counterpart_id):
                raise TrustedContactError("Trusted sharing is unavailable for this journey.", 410, "link_unavailable")
            if booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
                raise TrustedContactError("A link is available only for an accepted active journey.", 410, "link_unavailable")
            if booking.get("live_location_ended_reason") in {"arrival", "blocked"}:
                raise TrustedContactError("This journey link is no longer available.", 410, "link_unavailable")
            end_at = self._end_at(booking, trip)
            if end_at is None or end_at <= now:
                raise TrustedContactError("This journey link is no longer available.", 410, "link_unavailable")

            expires_at = min(now + timedelta(seconds=MAX_LINK_SECONDS), end_at)
            # The signed claim stores whole Unix seconds; keep the persisted and
            # displayed deadline no later than the signed deadline.
            expires_at = datetime.fromtimestamp(int(expires_at.timestamp()), UTC)
            link_id = uuid.uuid4().hex
            claims = {
                "v": TOKEN_VERSION,
                "id": link_id,
                "exp": int(expires_at.timestamp()),
                "nonce": secrets.token_urlsafe(32),
                "alias": alias,
            }
            token = self._serializer.dumps(claims)
            token_hash = hmac.new(self._hash_key, token.encode("utf-8"), hashlib.sha256).hexdigest()
            tx.put(LINK_COLLECTION, link_id, {
                "id": link_id,
                "token_hash": token_hash,
                "version": TOKEN_VERSION,
                "created_at": _stamp(now),
                "expires_at": _stamp(expires_at),
                "booking_id": booking_id,
                "actor_id": actor_id,
            })
            snapshot = self._snapshot(booking, trip, expires_at, alias)
            return {"link_id": link_id, "token": token, "expires_at": _stamp(expires_at), "snapshot": snapshot}

    def revoke_link(self, user, payload):
        link_id = self._payload_value(payload, "link_id")
        actor_id = user.get("id") if isinstance(user, dict) else None
        if not isinstance(link_id, str) or not link_id or len(link_id) > 128:
            raise TrustedContactError("A trusted-contact link is required.", code="invalid_link")
        if not actor_id:
            raise TrustedContactError("Sign in to revoke this link.", 401, "unauthenticated")
        with self.store.transaction() as tx:
            link = tx.get(LINK_COLLECTION, link_id)
            if not link or link.get("actor_id") != actor_id:
                raise TrustedContactError("This link is unavailable to this account.", 404, "not_found")
            if not link.get("revoked_at"):
                link["revoked_at"] = _stamp(self._current_time())
                tx.put(LINK_COLLECTION, link_id, link)
        return {"link_id": link_id, "revoked": True}

    def read_snapshot(self, token):
        """Read a currently eligible signed link; the bearer can be forwarded."""
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
        try:
            claims = self._serializer.loads(token)
        except BadSignature as exc:
            raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable") from exc
        if not isinstance(claims, dict) or claims.get("v") != TOKEN_VERSION:
            raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
        link_id, exp = claims.get("id"), claims.get("exp")
        if not isinstance(link_id, str) or not isinstance(exp, int) or isinstance(exp, bool):
            raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
        now = self._current_time()
        if now.timestamp() >= exp:
            raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
        token_hash = hmac.new(self._hash_key, token.encode("utf-8"), hashlib.sha256).hexdigest()
        with self.store.read() as tx:
            link = tx.get(LINK_COLLECTION, link_id)
            if not link or link.get("version") != TOKEN_VERSION or link.get("revoked_at"):
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            if not hmac.compare_digest(link.get("token_hash", ""), token_hash):
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            stored_expiry = _parse(link.get("expires_at"))
            if stored_expiry is None or now >= stored_expiry:
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            booking = tx.get("bookings", link.get("booking_id"))
            trip = tx.get("trips", booking.get("trip_id")) if booking else None
            if not booking or not trip:
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            counterpart_id = booking.get("passenger_id") if link["actor_id"] == booking.get("driver_id") else booking.get("driver_id")
            if self._blocked(tx, link["actor_id"], counterpart_id):
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            if booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            if booking.get("live_location_ended_reason") in {"arrival", "blocked"}:
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            end_at = self._end_at(booking, trip)
            if end_at is None or now >= end_at:
                raise TrustedContactError("This journey link is unavailable.", 410, "link_unavailable")
            return self._snapshot(booking, trip, stored_expiry, claims.get("alias"))

    @staticmethod
    def _snapshot(booking: dict, trip: dict, end_at: datetime, alias):
        vehicle = trip.get("driver_vehicle") or trip.get("vehicle") or {}
        # Keep the public shape explicit: adding a source field requires a review here.
        return {
            "alias": alias if isinstance(alias, str) else None,
            "trip_date": trip.get("departure"),
            "trip_status": trip.get("status"),
            "pickup": (booking.get("pickup") or {}).get("label", ""),
            "dropoff": (booking.get("dropoff") or {}).get("label", ""),
            "driver_name": trip.get("driver_name", ""),
            "vehicle_model": vehicle.get("model", ""),
            "vehicle_plate": vehicle.get("plate", ""),
            "expires_at": _stamp(end_at),
        }
