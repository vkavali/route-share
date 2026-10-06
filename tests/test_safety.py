"""Safety controls preserve privacy while changing only the intended bookings."""

import pytest

from app.domain import DomainError
from test_lifecycle import (
    ADDAKAL,
    KONDAPUR,
    KOTHakota,
    NANDIGAMA,
    SURYAPET,
    VIJAYAWADA,
    act,
    booking_for,
    future_departure,
    make_service,
    publish,
    search,
)


def _report(service, actor, booking_id, *, key="report-123", details="The driver repeatedly used a phone while driving."):
    return act(service, "report_safety", actor, booking_id=booking_id,
               category="unsafe_driving", details=details, idempotency_key=key)


def test_safety_report_is_participant_private_validated_idempotent_and_keeps_details_out_of_events(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, _ = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, booking = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)

    report = _report(service, users["passenger"], booking["id"])["report"]
    assert report["reporter_id"] == "passenger"
    assert report["subject_id"] == "driver"
    assert _report(service, users["passenger"], booking["id"])["report"] == report

    with pytest.raises(DomainError) as conflict:
        _report(service, users["passenger"], booking["id"], details="A different report body with enough characters.")
    assert conflict.value.status == 409
    with pytest.raises(DomainError) as outsider:
        _report(service, users["other"], booking["id"])
    assert outsider.value.status == 403
    with pytest.raises(DomainError) as admin:
        _report(service, users["admin"], booking["id"])
    assert admin.value.status == 403
    with pytest.raises(DomainError):
        act(service, "report_safety", users["passenger"], booking_id=booking["id"],
            category="made_up", details="A sufficiently long report description.", idempotency_key="report-456")
    with pytest.raises(DomainError):
        act(service, "report_safety", users["passenger"], booking_id=booking["id"],
            category="other", details="too short", idempotency_key="report-456")

    with store.read() as tx:
        events = tx.list("events")
        persisted_report = tx.get("safety_reports", report["id"])
    event = next(row for row in events if row["kind"] == "safety_report_created")
    assert event["actor_id"] == "passenger"
    assert event["details"] == {"category": "unsafe_driving"}
    assert persisted_report["details"] == report["details"]
    assert report["id"] in {row["id"] for row in act(service, "state", users["passenger"])["safety_reports"]}
    assert report["id"] not in {row["id"] for row in act(service, "state", users["driver"])["safety_reports"]}
    with pytest.raises(DomainError) as unknown:
        act(service, "booking_view", users["passenger"], booking_id=booking["id"])
    assert unknown.value.status == 404


def test_only_admin_resolves_report_and_reporter_sees_immutable_resolution(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, booking = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    report = _report(service, users["passenger"], booking["id"])["report"]

    with pytest.raises(DomainError) as forbidden:
        act(service, "resolve_report", users["driver"], report_id=report["id"],
            resolution="Reviewed and referred to the appropriate safety team.")
    assert forbidden.value.status == 403
    resolved = act(service, "resolve_report", users["admin"], report_id=report["id"],
                   resolution="Reviewed and referred to the appropriate safety team.")["report"]
    repeated = act(service, "resolve_report", users["admin"], report_id=report["id"],
                   resolution="A replacement resolution must not overwrite the first.")["report"]
    assert resolved["status"] == "resolved"
    assert repeated == resolved
    visible = next(row for row in act(service, "state", users["passenger"])["safety_reports"]
                   if row["id"] == report["id"])
    assert visible["resolution"] == resolved["resolution"]
    assert report["id"] not in {row["id"] for row in act(service, "state", users["driver"])["safety_reports"]}


def test_block_cancels_only_pair_bookings_releases_capacity_and_filters_both_search_directions(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    first_departure, second_departure = future_departure(4), future_departure(5)
    _, first_trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, first_departure, seats=1)
    reverse_departure = future_departure(6)
    publish(service, users["driver2"], KONDAPUR, VIJAYAWADA, reverse_departure)
    _, blocked_booking = booking_for(service, users["driver2"], SURYAPET, NANDIGAMA, first_departure)
    _, unrelated_booking = booking_for(service, users["passenger2"], SURYAPET, NANDIGAMA, first_departure)
    act(service, "accept", users["driver"], booking_id=blocked_booking["id"])

    # A stale search/match must not be usable to create a booking after the block.
    _, second_trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, second_departure)
    stale = search(service, users["driver2"], SURYAPET, NANDIGAMA, second_departure)
    assert stale["matches"]
    _, pending_pair = booking_for(service, users["driver2"], SURYAPET, NANDIGAMA, second_departure)
    _, unrelated_trip = publish(service, users["driver2"], KONDAPUR, VIJAYAWADA, second_departure)
    # Keep an unrelated pair booking pending as a guard against broad cancellation.
    _, unrelated_pair_booking = booking_for(service, users["other"], SURYAPET, NANDIGAMA, second_departure)

    outcome = act(service, "block_person", users["driver"], booking_id=blocked_booking["id"])
    assert outcome["block"]["blocked_id"] == "driver2"
    assert outcome["active_journey_unchanged"] is False
    with store.read() as tx:
        bookings = {row["id"]: row for row in tx.list("bookings")}
        trips = {row["id"]: row for row in tx.list("trips")}
    assert bookings[blocked_booking["id"]]["status"] == "cancelled"
    assert bookings[pending_pair["id"]]["status"] == "cancelled"
    assert bookings[unrelated_booking["id"]]["status"] == "pending"
    assert bookings[unrelated_pair_booking["id"]]["status"] == "pending"
    assert trips[first_trip["id"]]["version"] > first_trip["version"]
    assert trips[second_trip["id"]]["version"] > second_trip["version"]

    with pytest.raises(DomainError) as stale_denied:
        act(service, "request", users["driver2"], match_id=stale["matches"][0]["id"])
    assert stale_denied.value.status == 409
    with pytest.raises(DomainError) as accept_denied:
        act(service, "accept", users["driver"], booking_id=pending_pair["id"])
    assert accept_denied.value.status == 409

    # Capacity from the blocked accepted segment is available to another person.
    assert act(service, "accept", users["driver"], booking_id=unrelated_booking["id"])["booking"]["status"] == "accepted"
    assert search(service, users["driver2"], SURYAPET, NANDIGAMA, first_departure)["matches"] == []
    reverse_search = search(service, users["driver"], SURYAPET, NANDIGAMA, reverse_departure)
    assert reverse_search["matches"] == []


def test_block_during_started_journey_preserves_accepted_booking_and_marks_live_sharing_ended(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure)
    _, booking = booking_for(service, users["passenger"], SURYAPET, NANDIGAMA, departure)
    act(service, "accept", users["driver"], booking_id=booking["id"])
    act(service, "start_trip", users["driver"], trip_id=trip["id"])

    outcome = act(service, "block_person", users["passenger"], booking_id=booking["id"])
    assert outcome["active_journey_unchanged"] is True
    with store.read() as tx:
        saved = tx.get("bookings", booking["id"])
        saved_trip = tx.get("trips", trip["id"])
    assert saved["status"] == "accepted"
    assert saved["live_location_ended_reason"] == "blocked"
    assert saved["live_location_ended_at"]
    assert saved_trip["status"] == "started"

    # Blocking state applies in either direction, including stale matches.
    assert search(service, users["passenger"], SURYAPET, NANDIGAMA, departure)["matches"] == []
