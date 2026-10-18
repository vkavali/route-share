from datetime import datetime, timedelta, timezone

import pytest

from app.domain import DomainError, Service
from app.location_policy import sharing_window
from app.store import Store
from test_lifecycle import (
    KONDAPUR, NANDIGAMA, SURYAPET, VIJAYAWADA, act, booking_for,
    future_departure, make_service, publish,
)


def _accepted_trip(tmp_path, passenger="passenger"):
    service, store, users, path = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=2)
    _, booking = booking_for(service, users[passenger], SURYAPET, NANDIGAMA, departure)
    booking = act(service, "accept", users["driver"], booking_id=booking["id"])["booking"]
    return service, store, users, path, trip, booking


@pytest.mark.parametrize("actor", ["passenger", "driver"])
@pytest.mark.parametrize("board", [False, True])
def test_participant_can_cancel_started_or_boarded_booking_and_retries_once(tmp_path, actor, board):
    service, store, users, _, trip, booking = _accepted_trip(tmp_path)
    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    with store.transaction() as tx:
        current = tx.get("bookings", booking["id"])
        current["match"]["pickup_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        tx.put("bookings", current["id"], current)
    if board:
        act(service, "board_segment", users["passenger"], booking_id=booking["id"])

    result = act(service, "cancel_booking", users[actor], booking_id=booking["id"],
                 reason="Passenger needs to leave") ["booking"]
    replay = act(service, "cancel_booking", users[actor], booking_id=booking["id"],
                 reason="Passenger needs to leave") ["booking"]
    assert result["status"] == replay["status"] == "cancelled"
    assert result["cancelled_by"] == users[actor]["id"]
    assert result["cancelled_at"] and result["cancelled_at"] == replay["cancelled_at"]
    assert result["late_cancellation"] is True
    assert result["can_contact"] is False
    with store.read() as tx:
        saved_for_policy = tx.get("bookings", booking["id"])
        saved_trip_for_policy = tx.get("trips", trip["id"])
    assert sharing_window(saved_for_policy, saved_trip_for_policy, users[actor]["id"])["start_allowed"] is False
    with store.read() as tx:
        events = [row for row in tx.list("events")
                  if row.get("kind") == "booking_cancelled" and row.get("object_id") == booking["id"]]
        saved = tx.get("bookings", booking["id"])
        saved_trip = tx.get("trips", trip["id"])
    assert len(events) == 1
    assert saved["status"] == "cancelled"
    assert saved_trip["status"] == "started"
    assert saved_trip["schedule_note"].startswith("Last accepted timetable")
    state = act(service, "state", users["driver"])
    saved_view_trip = next(row for row in state["trips"] if row["id"] == trip["id"])
    assert max(segment["occupied"] for segment in saved_view_trip["inventory"]) == 0


def test_cancel_forbidden_for_stranger_and_completed_segment_and_decline_stays_pending_only(tmp_path):
    service, _, users, _, trip, booking = _accepted_trip(tmp_path)
    with pytest.raises(DomainError) as stranger:
        act(service, "cancel_booking", users["other"], booking_id=booking["id"], reason="No")
    assert stranger.value.status == 403
    with pytest.raises(DomainError) as missing_reason:
        act(service, "cancel_booking", users["passenger"], booking_id=booking["id"])
    assert missing_reason.value.status == 400
    with pytest.raises(DomainError) as stranger_trip_cancel:
        act(service, "cancel_trip", users["other"], trip_id=trip["id"], reason="No")
    assert stranger_trip_cancel.value.status == 403
    with pytest.raises(DomainError) as accepted_decline:
        act(service, "decline", users["driver"], booking_id=booking["id"])
    assert accepted_decline.value.status == 409

    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    act(service, "complete_segment", users["passenger"], booking_id=booking["id"])
    with pytest.raises(DomainError) as completed:
        act(service, "cancel_booking", users["driver"], booking_id=booking["id"], reason="Too late")
    assert completed.value.status == 409


def test_declining_pending_request_does_not_add_cancellation_timestamp(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, pending = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    declined = act(service, "decline", users["driver"], booking_id=pending["id"])["booking"]
    assert declined["status"] == "declined"
    assert "cancelled_at" not in declined
    with store.read() as tx:
        assert "cancelled_at" not in tx.get("bookings", pending["id"])


def test_driver_cancels_started_trip_preserving_completed_segments_and_persisting_actor_time(tmp_path):
    service, store, users, path = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=2)
    _, complete = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    _, unresolved = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, departure)
    for booking in (complete, unresolved):
        act(service, "accept", users["driver"], booking_id=booking["id"])
    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    act(service, "complete_segment", users["passenger"], booking_id=complete["id"])

    cancelled_trip = act(service, "cancel_trip", users["driver"], trip_id=trip["id"],
                         reason="Vehicle issue")["trip"]
    replay = act(service, "cancel_trip", users["driver"], trip_id=trip["id"],
                 reason="Vehicle issue")["trip"]
    assert cancelled_trip["status"] == replay["status"] == "cancelled"
    assert cancelled_trip["cancelled_by"] == users["driver"]["id"]
    assert cancelled_trip["cancelled_at"] == replay["cancelled_at"]
    with store.read() as tx:
        saved_complete = tx.get("bookings", complete["id"])
        saved_unresolved = tx.get("bookings", unresolved["id"])
        trip_events = [row for row in tx.list("events")
                       if row.get("kind") == "trip_cancelled" and row.get("object_id") == trip["id"]]
        booking_events = [row for row in tx.list("events")
                          if row.get("kind") == "booking_cancelled" and row.get("object_id") == unresolved["id"]]
    assert saved_complete["status"] == "segment_completed"
    assert saved_unresolved["status"] == "cancelled"
    assert saved_unresolved["cancelled_by"] == users["driver"]["id"]
    assert saved_unresolved["cancelled_at"]
    assert len(trip_events) == len(booking_events) == 1

    restored = Service(Store(path), service.router)
    saved = act(restored, "state", users["driver"])
    restored_trip = next(row for row in saved["trips"] if row["id"] == trip["id"])
    restored_bookings = {row["id"]: row for row in saved["bookings"]}
    assert restored_trip["cancelled_at"] == cancelled_trip["cancelled_at"]
    assert restored_bookings[complete["id"]]["status"] == "segment_completed"
    assert restored_bookings[unresolved["id"]]["cancelled_at"] == saved_unresolved["cancelled_at"]


def test_completed_trip_cannot_be_cancelled_and_missing_reason_rejected(tmp_path):
    service, _, users, _, trip, booking = _accepted_trip(tmp_path)
    with pytest.raises(DomainError) as missing_reason:
        act(service, "cancel_trip", users["driver"], trip_id=trip["id"])
    assert missing_reason.value.status == 400
    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    act(service, "complete_segment", users["passenger"], booking_id=booking["id"])
    act(service, "complete_trip", users["driver"], trip_id=trip["id"])
    with pytest.raises(DomainError) as completed:
        act(service, "cancel_trip", users["driver"], trip_id=trip["id"], reason="After completion")
    assert completed.value.status == 409
