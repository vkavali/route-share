"""Private profile, consented contact, chat and notification services."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone


UTC = timezone.utc
CLIENT_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MESSAGE_RATE_PER_MINUTE = 20


class CommunityError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "community_invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _normalized_phone(value) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise CommunityError("Enter a valid Indian mobile number.", code="invalid_phone")
    text = value.strip()
    digits = re.sub(r"[\s-]", "", text)
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if not re.fullmatch(r"[6-9][0-9]{9}", digits):
        raise CommunityError("Enter a valid Indian mobile number.", code="invalid_phone")
    return "+91" + digits


class CommunityService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _verification(user):
        value = user.get("verification") or {}
        allowed = {"not_checked", "pending", "verified", "rejected", "expired"}
        return {
            key: value.get(key) if isinstance(value.get(key), str) and value.get(key) in allowed else "not_checked"
            for key in ("phone", "identity", "dl", "rc", "selfie")
        }

    def profile_for(self, user):
        return {
            "id": user["id"],
            "name": user.get("name", ""),
            "phone": user.get("phone", ""),
            "share_phone": bool(user.get("share_phone", False)),
            "verification": self._verification(user),
        }

    def public_summary(self, user_id):
        with self.store.read() as tx:
            return self.public_summary_in(tx, user_id)

    def public_summary_in(self, tx, user_id):
        user = tx.get("users", user_id)
        if not user:
            return None
        ratings = [row for row in tx.list("ratings") if row.get("subject_id") == user_id]
        trips = tx.list("trips")
        completed_ids = {row["id"] for row in trips if row.get("driver_id") == user_id and row.get("status") == "completed"}
        trip_by_id = {row["id"]: row for row in trips}
        completed_ids.update(
            row.get("trip_id") for row in tx.list("bookings")
            if row.get("passenger_id") == user_id and row.get("status") == "segment_completed"
            and trip_by_id.get(row.get("trip_id"), {}).get("status") == "completed"
        )
        stars = [row.get("stars") for row in ratings
                 if isinstance(row.get("stars"), (int, float)) and not isinstance(row.get("stars"), bool)]
        return {
            "id": user["id"],
            "name": user.get("name", ""),
            "development": bool(user.get("development", True)),
            "verification": self._verification(user),
            "rating_average": round(sum(stars) / len(stars), 2) if len(stars) >= 3 else None,
            "rating_count": len(stars),
            "completed_trip_count": len(completed_ids),
        }

    def dispatch(self, action, user, payload):
        method = getattr(self, "_" + action, None)
        if method is None:
            raise CommunityError("Unknown community action.", 404, "not_found")
        return method(user, payload)

    def _profile(self, user, payload):
        with self.store.read() as tx:
            record = tx.get("users", user["id"])
        if not record:
            raise CommunityError("Profile not found.", 404, "not_found")
        return {"profile": self.profile_for(record)}

    def _update_profile(self, user, payload):
        name = payload.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise CommunityError("Name must contain 1 to 80 characters.", code="invalid_name")
        share_phone = payload.get("share_phone")
        if not isinstance(share_phone, bool):
            raise CommunityError("Choose whether to share your phone number.", code="invalid_share_choice")
        with self.store.transaction() as tx:
            record = tx.get("users", user["id"])
            if not record:
                raise CommunityError("Profile not found.", 404, "not_found")
            old_phone = record.get("phone", "")
            phone = old_phone
            if "phone" in payload:
                raw = payload["phone"]
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    phone = ""
                else:
                    phone = _normalized_phone(raw)
            if share_phone and not phone:
                raise CommunityError("Add a phone number before sharing it.", code="phone_required")
            verification = dict(record.get("verification") or {})
            if phone != old_phone:
                verification["phone"] = "not_checked"
            record.update(name=name.strip(), phone=phone, share_phone=share_phone, verification=verification)
            tx.put("users", record["id"], record)
            own = self.profile_for(record)
            current_user = {key: value for key, value in record.items() if key not in {"password", "password_hash"}}
        return {"profile": own, "user": current_user}

    @staticmethod
    def _pair_blocked(tx, first, second):
        return bool(tx.get("blocks", first + ":" + second) or tx.get("blocks", second + ":" + first))

    @staticmethod
    def _journey_active(booking, trip, at=None):
        if booking.get("status") != "accepted" or trip.get("status") not in {"published", "started"}:
            return False
        if booking.get("live_location_ended_reason") in {"arrival", "blocked"}:
            return False
        at = at or _now()
        match = booking.get("match") or {}
        dropoff = _parse(match.get("dropoff_at"))
        if dropoff is None:
            departure = _parse(trip.get("departure"))
            route = trip.get("current_route") or trip.get("route") or {}
            duration = route.get("duration_s")
            if departure is None or not isinstance(duration, (int, float)):
                return False
            dropoff = departure + timedelta(seconds=max(0, duration) + max(0, trip.get("max_detour_minutes", 0) or 0) * 60)
        return at <= dropoff

    def contact_available(self, booking, trip, viewer_id):
        """Return only whether contact may be offered for this participant's active booking.

        Re-read current records so callers cannot accidentally use stale booking consent,
        trip status, or block state. The counterpart's phone is never returned here.
        """
        if not isinstance(booking, dict) or not isinstance(trip, dict) or not isinstance(viewer_id, str):
            return False
        booking_id = booking.get("id")
        trip_id = booking.get("trip_id")
        if not isinstance(booking_id, str) or not booking_id or trip.get("id") != trip_id:
            return False
        with self.store.read() as tx:
            current_booking = tx.get("bookings", booking_id)
            if not current_booking or current_booking.get("trip_id") != trip_id:
                return False
            driver_id = current_booking.get("driver_id")
            passenger_id = current_booking.get("passenger_id")
            if viewer_id not in {driver_id, passenger_id}:
                return False
            if self._pair_blocked(tx, driver_id, passenger_id):
                return False
            current_trip = tx.get("trips", trip_id)
            if not current_trip or not self._journey_active(current_booking, current_trip):
                return False
            counterpart_id = passenger_id if viewer_id == driver_id else driver_id
            counterpart = tx.get("users", counterpart_id) or {}
            return bool(counterpart.get("share_phone") and counterpart.get("phone"))

    def _participant_booking(self, tx, booking_id, user_id):
        booking = tx.get("bookings", booking_id)
        if not booking or user_id not in {booking.get("driver_id"), booking.get("passenger_id")}:
            raise CommunityError("This conversation is not available to this account.", 403, "not_participant")
        return booking

    def _contact(self, user, payload):
        booking_id = payload.get("booking_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise CommunityError("A booking is required.", code="invalid_booking")
        with self.store.transaction() as tx:
            booking = self._participant_booking(tx, booking_id, user["id"])
            trip = tx.get("trips", booking.get("trip_id"))
            if self._pair_blocked(tx, booking["driver_id"], booking["passenger_id"]):
                raise CommunityError("Contact is unavailable for this booking.", 403, "pair_blocked")
            if not trip or not self._journey_active(booking, trip):
                raise CommunityError("Contact is available only during an accepted active journey.", 409, "journey_inactive")
            counterpart_id = booking["passenger_id"] if user["id"] == booking["driver_id"] else booking["driver_id"]
            counterpart = tx.get("users", counterpart_id)
            if not counterpart or not counterpart.get("share_phone") or not counterpart.get("phone"):
                raise CommunityError("The other participant has not shared a phone number.", 403, "contact_not_shared")
            return {"contact": {"name": counterpart.get("name", ""), "phone": counterpart["phone"]}}

    def _chat_access(self, tx, user, booking_id):
        booking = self._participant_booking(tx, booking_id, user["id"])
        if self._pair_blocked(tx, booking["driver_id"], booking["passenger_id"]):
            raise CommunityError("Chat is unavailable for this booking.", 403, "pair_blocked")
        trip = tx.get("trips", booking.get("trip_id")) or {}
        can_send = self._journey_active(booking, trip)
        counterpart_id = booking["passenger_id"] if user["id"] == booking["driver_id"] else booking["driver_id"]
        counterpart = tx.get("users", counterpart_id) or {}
        return booking, trip, counterpart_id, counterpart, can_send

    def _chat(self, user, payload):
        booking_id = payload.get("booking_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise CommunityError("A booking is required.", code="invalid_booking")
        with self.store.read() as tx:
            booking, trip, _other_id, _other, can_send = self._chat_access(tx, user, booking_id)
            rows = [row for row in tx.list("messages") if row.get("booking_id") == booking_id]
            rows.sort(key=lambda row: (row.get("created_at", ""), row.get("id", "")))
            messages = [self._message_view(row) for row in rows[-100:]]
            return {
                "booking_id": booking_id,
                "booking_status": booking.get("status"),
                "trip_status": trip.get("status"),
                "send_allowed": can_send,
                "can_send": can_send,
                "messages": messages,
            }

    @staticmethod
    def _message_id(booking_id, sender_id, client_message_id):
        source = f"{booking_id}\0{sender_id}\0{client_message_id}".encode("utf-8")
        return hashlib.sha256(source).hexdigest()

    @staticmethod
    def _message_view(row):
        fields = ("id", "booking_id", "sender_id", "sender_name", "text", "client_message_id", "created_at", "read_at")
        return {field: row.get(field) for field in fields}

    def _send_message(self, user, payload):
        booking_id = payload.get("booking_id")
        text = payload.get("text")
        client_id = payload.get("client_message_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise CommunityError("A booking is required.", code="invalid_booking")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
            raise CommunityError("Message must contain 1 to 1000 characters.", code="invalid_message")
        text = text.strip()
        if not isinstance(client_id, str) or not CLIENT_MESSAGE_ID.fullmatch(client_id):
            raise CommunityError("A valid client message identifier is required.", code="invalid_message_id")
        message_id = self._message_id(booking_id, user["id"], client_id)
        with self.store.transaction() as tx:
            booking, trip, counterpart_id, counterpart, can_send = self._chat_access(tx, user, booking_id)
            existing = tx.get("messages", message_id)
            if existing:
                if existing.get("text") != text:
                    raise CommunityError("That message identifier was already used.", 409, "idempotency_conflict")
                return {"message": self._message_view(existing)}
            if not can_send:
                raise CommunityError("Messages are available only during an accepted active journey.", 409, "journey_inactive")
            now = _now()
            limit_record = tx.get("message_limits", user["id"]) or {"id": user["id"], "timestamps": []}
            recent = [value for value in limit_record["timestamps"] if isinstance(value, (int, float)) and value > now.timestamp() - 60]
            if len(recent) >= MESSAGE_RATE_PER_MINUTE:
                raise CommunityError("Too many messages. Wait a minute and try again.", 429, "rate_limited")
            recent.append(now.timestamp())
            limit_record["timestamps"] = recent
            tx.put("message_limits", user["id"], limit_record)
            message = {
                "id": message_id, "booking_id": booking_id, "sender_id": user["id"],
                "sender_name": user.get("name", ""), "recipient_id": counterpart_id,
                "text": text, "client_message_id": client_id, "created_at": now.isoformat(), "read_at": None,
            }
            tx.put("messages", message_id, message)
            self._notification(tx, counterpart_id, "chat_message", booking_id, now=now, message_id=message_id)
            return {"message": self._message_view(message)}

    def _chats(self, user, payload):
        with self.store.read() as tx:
            trips = {row["id"]: row for row in tx.list("trips")}
            messages = tx.list("messages")
            bookings = [row for row in tx.list("bookings") if user["id"] in {row.get("driver_id"), row.get("passenger_id")}]
            output = []
            for booking in bookings:
                other_id = booking["passenger_id"] if user["id"] == booking["driver_id"] else booking["driver_id"]
                if self._pair_blocked(tx, booking["driver_id"], booking["passenger_id"]):
                    continue
                own_messages = [row for row in messages if row.get("booking_id") == booking["id"]]
                if booking.get("status") not in {"accepted", "segment_completed"} and not own_messages:
                    continue
                own_messages.sort(key=lambda row: (row.get("created_at", ""), row.get("id", "")))
                latest = own_messages[-1] if own_messages else None
                unread = sum(row.get("recipient_id") == user["id"] and not row.get("read_at") for row in own_messages)
                output.append({
                    "booking_id": booking["id"],
                    "counterpart_summary": self.public_summary_in(tx, other_id),
                    "latest_message": ({key: latest[key] for key in ("id", "text", "sender_id", "created_at")} if latest else None),
                    "unread_count": unread,
                    "trip_status": trips.get(booking.get("trip_id"), {}).get("status"),
                })
            output.sort(key=lambda row: row["latest_message"]["created_at"] if row["latest_message"] else "", reverse=True)
            return {"chats": output}

    def unread_counts(self, user_id):
        with self.store.read() as tx:
            notifications = sum(row.get("recipient_id") == user_id and not row.get("read_at")
                                for row in tx.list("notifications"))
            blocked = {(row.get("blocker_id"), row.get("blocked_id")) for row in tx.list("blocks")}
            booking_ids = {
                row["id"] for row in tx.list("bookings")
                if user_id in {row.get("driver_id"), row.get("passenger_id")}
                and (row.get("driver_id"), row.get("passenger_id")) not in blocked
                and (row.get("passenger_id"), row.get("driver_id")) not in blocked
            }
            unread_chats = sum(row.get("booking_id") in booking_ids and row.get("recipient_id") == user_id
                               and not row.get("read_at") for row in tx.list("messages"))
        return {"notification_unread_count": notifications, "chat_unread_count": unread_chats}

    def _mark_chat_read(self, user, payload):
        booking_id, upto_id = payload.get("booking_id"), payload.get("upto_message_id")
        if not isinstance(booking_id, str) or not booking_id or len(booking_id) > 128:
            raise CommunityError("A booking is required.", code="invalid_booking")
        if not isinstance(upto_id, str) or not upto_id or len(upto_id) > 128:
            raise CommunityError("A message is required.", code="invalid_message_id")
        with self.store.transaction() as tx:
            self._chat_access(tx, user, booking_id)
            target = tx.get("messages", upto_id)
            if not target or target.get("booking_id") != booking_id:
                raise CommunityError("Message not found in this booking.", 404, "not_found")
            target_stamp = target.get("created_at", "")
            read_time = _stamp()
            read_ids = set()
            for row in tx.list("messages"):
                if (row.get("booking_id") == booking_id and row.get("recipient_id") == user["id"]
                        and not row.get("read_at") and (row.get("created_at", ""), row.get("id", "")) <= (target_stamp, upto_id)):
                    row["read_at"] = read_time
                    tx.put("messages", row["id"], row)
                    read_ids.add(row["id"])
            for notification in tx.list("notifications"):
                if (notification.get("recipient_id") == user["id"] and notification.get("message_id") in read_ids
                        and not notification.get("read_at")):
                    notification["read_at"] = read_time
                    tx.put("notifications", notification["id"], notification)
            return {"read_at": read_time}

    def _notification(self, tx, recipient_id, kind, booking_id, *, now=None, message_id=None):
        row = {
            "id": uuid.uuid4().hex, "recipient_id": recipient_id, "type": kind,
            "booking_id": booking_id, "created_at": _stamp(now), "read_at": None,
        }
        if message_id:
            row["message_id"] = message_id
        tx.put("notifications", row["id"], row)
        return row

    @staticmethod
    def _notification_view(row):
        fields = ("id", "type", "booking_id", "message_id", "created_at", "read_at")
        return {field: row[field] for field in fields if field in row}

    def notify_lifecycle(self, tx, kind, object_id, actor_id, at=None):
        booking_types = {
            "seat_requested": ("ride_request", "driver_id"),
            "seat_accepted": ("ride_accepted", "passenger_id"),
            "booking_declined": ("booking_declined", None),
            "booking_cancelled": ("booking_cancelled", None),
            "segment_completed": ("segment_completed", None),
        }
        if kind in booking_types:
            booking = tx.get("bookings", object_id)
            if not booking:
                return
            notification_type, fixed_recipient = booking_types[kind]
            if fixed_recipient:
                recipient = booking.get(fixed_recipient)
            else:
                recipient = booking.get("passenger_id") if actor_id == booking.get("driver_id") else booking.get("driver_id")
            if recipient and recipient != actor_id:
                self._notification(tx, recipient, notification_type, booking["id"], now=_parse(at) if at else None)
            return
        trip_type = {"trip_started": "trip_started", "trip_completed": "trip_completed"}.get(kind)
        if trip_type:
            trip = tx.get("trips", object_id)
            if not trip:
                return
            for booking in tx.list("bookings"):
                if booking.get("trip_id") != object_id or booking.get("status") not in {"accepted", "segment_completed"}:
                    continue
                for participant in (booking.get("driver_id"), booking.get("passenger_id")):
                    if participant and participant != actor_id:
                        self._notification(tx, participant, trip_type, booking["id"], now=_parse(at) if at else None)

    def _notifications(self, user, payload):
        with self.store.read() as tx:
            rows = [row for row in tx.list("notifications") if row.get("recipient_id") == user["id"]]
        rows.sort(key=lambda row: (row.get("created_at", ""), row.get("id", "")), reverse=True)
        return {"notifications": [self._notification_view(row) for row in rows[:100]]}

    def _mark_notification_read(self, user, payload):
        notification_id = payload.get("notification_id")
        if not isinstance(notification_id, str) or not notification_id or len(notification_id) > 128:
            raise CommunityError("A notification is required.", code="invalid_notification")
        with self.store.transaction() as tx:
            row = tx.get("notifications", notification_id)
            if not row or row.get("recipient_id") != user["id"]:
                raise CommunityError("Notification not found.", 404, "not_found")
            if not row.get("read_at"):
                row["read_at"] = _stamp()
                tx.put("notifications", row["id"], row)
            return {"notification": self._notification_view(row)}
