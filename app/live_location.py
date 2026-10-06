"""Ephemeral, consent-gated live locations for accepted route segments."""

from __future__ import annotations

import math
import secrets
import threading
import time
from datetime import datetime, timezone


LOCATION_TTL_SECONDS = 120
ARRIVAL_ACCURACY_METERS = 200.0
_MAX_REMEMBERED_SHARING_IDS = 4096
_EARTH_RADIUS_M = 6_371_000.0


class LiveLocationError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "sharing_unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code


def distance_m(a: dict, b: dict) -> float:
    lat1, lon1 = math.radians(float(a["lat"])), math.radians(float(a["lon"]))
    lat2, lon2 = math.radians(float(b["lat"])), math.radians(float(b["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


class LiveLocationStore:
    """Thread-safe memory only. Locations are overwritten and expire after 120s."""

    def __init__(self, clock=None, *, auto_expire=True):
        self.clock = clock or time.monotonic
        self.auto_expire = auto_expire
        self._lock = threading.RLock()
        self._leases: dict[str, dict[str, dict]] = {}
        self._samples: dict[str, dict[str, dict]] = {}
        self._last_ids: dict[tuple[str, str], str] = {}
        self._expiry_timer: threading.Timer | None = None
        self._expiry_deadline: float | None = None
        self._expiry_generation = 0

    def _schedule_expiry_locked(self) -> None:
        if not self.auto_expire:
            return
        deadlines = [lease["expires_at"] for leases in self._leases.values() for lease in leases.values()]
        deadlines.extend(sample["_expires_at"] for samples in self._samples.values() for sample in samples.values())
        earliest = min(deadlines) if deadlines else None
        if earliest is None:
            if self._expiry_timer is not None:
                self._expiry_generation += 1
                self._expiry_timer.cancel()
                self._expiry_timer = None
                self._expiry_deadline = None
            return
        if self._expiry_timer is not None and self._expiry_timer.is_alive() and self._expiry_deadline <= earliest:
            return
        if self._expiry_timer is not None:
            self._expiry_timer.cancel()
        self._expiry_generation += 1
        generation = self._expiry_generation
        self._expiry_deadline = earliest
        self._expiry_timer = threading.Timer(max(0.001, earliest - self.clock()), self._expire, args=(generation,))
        self._expiry_timer.daemon = True
        self._expiry_timer.start()

    def _expire(self, generation: int) -> None:
        with self._lock:
            if generation != self._expiry_generation:
                return
            self._expiry_timer = None
            self._expiry_deadline = None
            self._purge_expired_locked()

    def _purge_expired_locked(self, booking_id: str | None = None) -> None:
        now = self.clock()
        bookings = [booking_id] if booking_id is not None else list(self._leases)
        for bid in bookings:
            leases = self._leases.get(bid, {})
            samples = self._samples.get(bid, {})
            for user_id, lease in list(leases.items()):
                if lease["expires_at"] <= now:
                    leases.pop(user_id, None)
                    samples.pop(user_id, None)
            for user_id, sample in list(samples.items()):
                if sample["_expires_at"] <= now:
                    samples.pop(user_id, None)
            if not leases:
                self._leases.pop(bid, None)
            if not samples:
                self._samples.pop(bid, None)
            else:
                for user_id in list(samples):
                    if user_id not in leases:
                        samples.pop(user_id, None)
                if not samples:
                    self._samples.pop(bid, None)
        self._schedule_expiry_locked()

    def start(self, booking_id: str, user_id: str, *, consent_phase: str = "pickup") -> dict:
        with self._lock:
            self._purge_expired_locked(booking_id)
            leases = self._leases.setdefault(booking_id, {})
            current = leases.get(user_id)
            if current and current.get("consent_phase", "pickup") == consent_phase:
                current["expires_at"] = self.clock() + LOCATION_TTL_SECONDS
                return {"booking_id": booking_id, "sharing_id": current["sharing_id"], "expires_after_seconds": LOCATION_TTL_SECONDS}
            sharing_id = secrets.token_urlsafe(32)
            leases[user_id] = {"sharing_id": sharing_id, "expires_at": self.clock() + LOCATION_TTL_SECONDS, "consent_phase": consent_phase}
            self._last_ids[(booking_id, user_id)] = sharing_id
            while len(self._last_ids) > _MAX_REMEMBERED_SHARING_IDS:
                self._last_ids.pop(next(iter(self._last_ids)))
            self._schedule_expiry_locked()
            return {"booking_id": booking_id, "sharing_id": sharing_id, "expires_after_seconds": LOCATION_TTL_SECONDS}

    def _lease_locked(self, booking_id: str, user_id: str, sharing_id: str) -> dict:
        self._purge_expired_locked(booking_id)
        lease = self._leases.get(booking_id, {}).get(user_id)
        if not sharing_id or not lease or not secrets.compare_digest(lease["sharing_id"], sharing_id):
            raise LiveLocationError("Sharing session expired or stopped. Start sharing again to continue.", code="sharing_expired")
        return lease

    def require_lease(self, booking_id: str, user_id: str, sharing_id: str, *, consent_phase: str = "pickup") -> None:
        with self._lock:
            lease = self._lease_locked(booking_id, user_id, sharing_id)
            if lease.get("consent_phase", "pickup") != consent_phase:
                self._remove_user_locked(booking_id, user_id)
                raise LiveLocationError("Start sharing again to share after boarding.", code="sharing_expired")

    def restrict_actor(self, booking_id: str, user_id: str, *, allowed: bool, consent_phase: str) -> None:
        with self._lock:
            lease = self._leases.get(booking_id, {}).get(user_id)
            if lease and (not allowed or lease.get("consent_phase", "pickup") != consent_phase):
                self._remove_user_locked(booking_id, user_id)
                self._schedule_expiry_locked()

    def is_known_sharing_id(self, booking_id: str, user_id: str, sharing_id: str) -> bool:
        with self._lock:
            latest = self._last_ids.get((booking_id, user_id), "")
            return bool(sharing_id and latest and secrets.compare_digest(latest, sharing_id))

    def stop(self, booking_id: str, user_id: str, sharing_id: str) -> None:
        with self._lock:
            self._purge_expired_locked(booking_id)
            lease = self._leases.get(booking_id, {}).get(user_id)
            last = self._last_ids.get((booking_id, user_id))
            if not sharing_id or not (lease and secrets.compare_digest(lease["sharing_id"], sharing_id)):
                if not last or not secrets.compare_digest(last, sharing_id):
                    raise LiveLocationError("Sharing session expired or stopped. Start sharing again to continue.", code="sharing_expired")
            self._remove_user_locked(booking_id, user_id)
            self._schedule_expiry_locked()

    def _remove_user_locked(self, booking_id: str, user_id: str) -> None:
        leases = self._leases.get(booking_id)
        samples = self._samples.get(booking_id)
        if leases:
            leases.pop(user_id, None)
            if not leases:
                self._leases.pop(booking_id, None)
        if samples:
            samples.pop(user_id, None)
            if not samples:
                self._samples.pop(booking_id, None)

    def update(self, booking_id: str, user_id: str, sharing_id: str, *, lat: float, lon: float, accuracy: float, updated_at: str) -> dict:
        with self._lock:
            lease = self._lease_locked(booking_id, user_id, sharing_id)
            if accuracy > ARRIVAL_ACCURACY_METERS:
                self._remove_user_locked(booking_id, user_id)
                self._schedule_expiry_locked()
                return {"ok": True, "sharing_allowed": False, "stopped_reason": "poor_accuracy"}
            lease["expires_at"] = self.clock() + LOCATION_TTL_SECONDS
            self._samples.setdefault(booking_id, {})[user_id] = {
                "user_id": user_id, "lat": lat, "lon": lon, "accuracy": accuracy,
                "updated_at": updated_at, "_expires_at": lease["expires_at"],
            }
            return {"ok": True, "sharing_allowed": True, "expires_after_seconds": LOCATION_TTL_SECONDS}

    def snapshot(self, booking_id: str, viewer_id: str, participants: dict[str, str], *, ended_reason: str | None = None) -> dict:
        with self._lock:
            self._purge_expired_locked(booking_id)
            if ended_reason:
                self._revoke_booking_locked(booking_id)
                return {"booking_id": booking_id, "viewer_id": viewer_id, "sharing_allowed": False,
                        "viewer_sharing": False, "viewer_sharing_id": None,
                        "stopped_reason": ended_reason, "locations": [],
                        "expires_after_seconds": LOCATION_TTL_SECONDS}
            leases = self._leases.get(booking_id, {})
            samples = self._samples.get(booking_id, {})
            locations = []
            for user_id, sample in samples.items():
                if user_id == viewer_id or user_id not in participants:
                    continue
                if sample["_expires_at"] <= self.clock() or user_id not in leases:
                    continue
                locations.append({key: sample[key] for key in ("user_id", "lat", "lon", "accuracy", "updated_at")} | {"name": participants[user_id]})
            return {"booking_id": booking_id, "viewer_id": viewer_id, "sharing_allowed": True,
                    "viewer_sharing": viewer_id in leases,
                    "viewer_sharing_id": leases.get(viewer_id, {}).get("sharing_id"),
                    "locations": locations, "expires_after_seconds": LOCATION_TTL_SECONDS}

    def revoke_booking(self, booking_id: str) -> None:
        with self._lock:
            self._revoke_booking_locked(booking_id)

    def _revoke_booking_locked(self, booking_id: str) -> None:
        self._leases.pop(booking_id, None)
        self._samples.pop(booking_id, None)
        self._schedule_expiry_locked()

    def stop_actor(self, user_id: str) -> None:
        with self._lock:
            for booking_id, leases in list(self._leases.items()):
                if user_id in leases:
                    self._remove_user_locked(booking_id, user_id)
            self._schedule_expiry_locked()

    def purge_except(self, active_booking_ids: set[str]) -> None:
        with self._lock:
            self._purge_expired_locked()
            for booking_id in list(self._leases):
                if booking_id not in active_booking_ids:
                    self._revoke_booking_locked(booking_id)
            self._schedule_expiry_locked()
