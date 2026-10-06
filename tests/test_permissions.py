from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import DomainError, now
from app.permissions import access_summary, can_drive
from test_lifecycle import KONDAPUR, VIJAYAWADA, act, future_departure, make_service, publish, search


def _valid_approval(expires=None):
    return {"kind": "development", "expires_at": (expires or datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}


def _seed_match(store, index, *, passenger_id="passenger", status="published"):
    timestamp = datetime.now(timezone.utc)
    departure = (timestamp + timedelta(days=3)).isoformat()
    trip_id = f"limit-trip-{index}"
    request_id = f"limit-request-{index}"
    match_id = f"limit-match-{index}"
    origin = {"label": "A", "lat": 17.0, "lon": 78.0}
    destination = {"label": "B", "lat": 17.3, "lon": 78.3}
    with store.transaction() as tx:
        tx.put("trips", trip_id, {"id": trip_id, "driver_id": "driver", "driver_name": "Fixture Driver",
                                   "status": status, "departure": departure})
        tx.put("requests", request_id, {"id": request_id, "passenger_id": passenger_id,
                                         "passenger_name": "Fixture Passenger", "origin": origin,
                                         "destination": destination, "seats": 1,
                                         "window_start": departure, "window_end": departure})
        tx.put("matches", match_id, {"id": match_id, "request_id": request_id, "trip_id": trip_id,
                                     "created_at": timestamp.isoformat(), "start_m": 0, "end_m": 1000})
    return match_id, trip_id


def test_access_summary_requires_current_approval_and_verified_reviewed_documents(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver = users["driver"]
    assert access_summary(driver)["can_drive"] is True

    reviewed = {**driver, "driver_approval": {"kind": "reviewed", "expires_at": _valid_approval()["expires_at"]},
                "verification": {"dl": "verified", "rc": "verified"}}
    assert can_drive(reviewed)
    reviewed["verification"] = {"dl": "verified", "rc": "not_checked"}
    assert not can_drive(reviewed)
    not_development = {**driver, "development": False}
    assert not can_drive(not_development)
    expired = {**driver, "driver_approval": _valid_approval(datetime.now(timezone.utc) - timedelta(seconds=1))}
    assert not can_drive(expired)


def test_dispatch_reloads_persisted_approval_instead_of_trusting_stale_snapshot(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    stale_user = users["driver"]
    with store.transaction() as tx:
        current = tx.get("users", "driver")
        current.update(driver_approved=False, driver_approval=_valid_approval(datetime.now(timezone.utc) - timedelta(days=1)))
        tx.put("users", "driver", current)
    with pytest.raises(DomainError) as denied:
        act(service, "preview", stale_user, origin=KONDAPUR, destination=VIJAYAWADA,
            departure=future_departure(), seats=1, max_detour_minutes=10)
    assert denied.value.status == 403
    with store.read() as tx:
        assert tx.list("previews") == []

    with store.transaction() as tx:
        current = tx.get("users", "driver")
        current.update(driver_approved=True, driver_approval=_valid_approval())
        tx.put("users", "driver", current)
    stale_user = {**stale_user, "driver_approved": False, "driver_approval": None}
    assert act(service, "preview", stale_user, origin=KONDAPUR, destination=VIJAYAWADA,
               departure=future_departure(), seats=1, max_detour_minutes=10)["preview"]


def test_staff_capabilities_are_explicit_and_staff_cannot_take_travel_actions(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    staff = users["admin"]
    with store.transaction() as tx:
        record = tx.get("users", "admin")
        record["staff_capabilities"] = ["ops.read", "verify.review", "safety.act", "staff.manage"]
        record["driver_approved"] = True
        record["driver_approval"] = _valid_approval()
        tx.put("users", "admin", record)
    state = act(service, "state", staff)
    assert state["access"] == {"is_staff": True, "can_drive": False,
                               "staff_capabilities": ["ops.read", "safety.act", "staff.manage", "verify.review"]}
    assert act(service, "operations", staff)["metrics"]["development_data_only"] is True
    with pytest.raises(DomainError) as denied:
        act(service, "search", staff, origin=KONDAPUR, destination=VIJAYAWADA,
            window_start=future_departure(), window_end=future_departure(), seats=1)
    assert denied.value.status == 403
    with pytest.raises(DomainError) as denied:
        act(service, "preview", staff, origin=KONDAPUR, destination=VIJAYAWADA,
            departure=future_departure(), seats=1, max_detour_minutes=10)
    assert denied.value.status == 403
    with store.transaction() as tx:
        tx.put("safety_reports", "staff-report", {"id": "staff-report", "status": "open"})
    resolved = act(service, "resolve_report", staff, report_id="staff-report",
                    resolution="Reviewed the reported issue and recorded the outcome.")
    assert resolved["report"]["status"] == "resolved"


def test_admin_role_alone_does_not_grant_staff_capabilities(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    legacy_admin = {"id": "legacy-admin", "name": "Legacy Admin", "role": "admin", "development": True,
                    "driver_approved": True, "driver_approval": _valid_approval(),
                    "staff_capabilities": ["ops.read", "safety.act"]}
    with store.transaction() as tx:
        tx.put("users", legacy_admin["id"], legacy_admin)
        tx.put("safety_reports", "report", {"id": "report", "status": "open"})
    assert access_summary(legacy_admin) == {"is_staff": False, "can_drive": False, "staff_capabilities": []}
    with pytest.raises(DomainError) as denied:
        act(service, "operations", legacy_admin)
    assert denied.value.status == 403
    with pytest.raises(DomainError) as denied:
        act(service, "resolve_report", legacy_admin, report_id="report", resolution="Reviewed and closed safely.")
    assert denied.value.status == 403


def test_driver_approval_expiry_blocks_new_trip_start_but_allows_safe_cancellation(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver = users["driver"]
    _preview, trip = publish(service, driver, KONDAPUR, VIJAYAWADA)
    with store.transaction() as tx:
        record = tx.get("users", "driver")
        record["driver_approval"] = _valid_approval(datetime.now(timezone.utc) - timedelta(seconds=1))
        tx.put("users", "driver", record)
    with pytest.raises(DomainError) as denied:
        act(service, "start_trip", driver, trip_id=trip["id"])
    assert denied.value.status == 403
    cancelled = act(service, "cancel_trip", driver, trip_id=trip["id"], reason="Approval expired before departure.")
    assert cancelled["trip"]["status"] == "cancelled"


def test_driver_can_finish_an_already_started_journey_after_approval_expires(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver, passenger = users["driver"], users["passenger"]
    departure = future_departure()
    _preview, trip = publish(service, driver, KONDAPUR, VIJAYAWADA, departure)
    search_result = search(service, passenger, KONDAPUR, VIJAYAWADA, departure)
    booking = act(service, "request", passenger, match_id=search_result["matches"][0]["id"])["booking"]
    act(service, "accept", driver, booking_id=booking["id"])
    act(service, "start_trip", driver, trip_id=trip["id"])
    with store.transaction() as tx:
        record = tx.get("users", "driver")
        record["driver_approval"] = _valid_approval(datetime.now(timezone.utc) - timedelta(seconds=1))
        tx.put("users", "driver", record)
    completed_segment = act(service, "complete_segment", driver, booking_id=booking["id"])
    assert completed_segment["booking"]["status"] == "segment_completed"
    completed_trip = act(service, "complete_trip", driver, trip_id=trip["id"])
    assert completed_trip["trip"]["status"] == "completed"


def test_passenger_only_boarding_is_persisted_and_idempotent(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver, passenger, outsider = users["driver"], users["passenger"], users["passenger2"]
    departure = future_departure()
    _preview, trip = publish(service, driver, KONDAPUR, VIJAYAWADA, departure)
    result = search(service, passenger, KONDAPUR, VIJAYAWADA, departure)
    booking = act(service, "request", passenger, match_id=result["matches"][0]["id"])["booking"]
    with pytest.raises(DomainError) as too_early:
        act(service, "board_segment", passenger, booking_id=booking["id"])
    assert too_early.value.status == 409
    act(service, "accept", driver, booking_id=booking["id"])
    act(service, "start_trip", driver, trip_id=trip["id"])
    with pytest.raises(DomainError) as driver_denied:
        act(service, "board_segment", driver, booking_id=booking["id"])
    assert driver_denied.value.status == 403
    with pytest.raises(DomainError) as outsider_denied:
        act(service, "board_segment", outsider, booking_id=booking["id"])
    assert outsider_denied.value.status == 403

    boarded = act(service, "board_segment", passenger, booking_id=booking["id"])["booking"]
    retried = act(service, "board_segment", passenger, booking_id=booking["id"])["booking"]
    assert boarded["boarded_at"] and boarded["boarded_by"] == "passenger"
    assert retried["boarded_at"] == boarded["boarded_at"]
    with store.read() as tx:
        assert len([event for event in tx.list("events") if event["kind"] == "seat_boarded"]) == 1


def test_late_accepted_cancellation_is_only_an_audit_flag(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    driver, passenger = users["driver"], users["passenger"]
    departure = future_departure()
    _preview, _trip = publish(service, driver, KONDAPUR, VIJAYAWADA, departure)
    result = search(service, passenger, KONDAPUR, VIJAYAWADA, departure)
    booking = act(service, "request", passenger, match_id=result["matches"][0]["id"])["booking"]
    accepted = act(service, "accept", driver, booking_id=booking["id"])["booking"]
    with store.transaction() as tx:
        saved = tx.get("bookings", accepted["id"])
        saved["match"]["pickup_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        tx.put("bookings", saved["id"], saved)
    cancelled = act(service, "cancel_booking", passenger, booking_id=booking["id"], reason="Plans changed.")
    assert cancelled["booking"]["late_cancellation"] is True
    assert cancelled["booking"]["late_cancellation_at"]
    assert not any(key in cancelled["booking"] for key in ("penalty", "payment", "fine"))


def test_passenger_search_is_one_seat_and_repeat_request_reuses_active_trip_booking(tmp_path):
    service, _store, users, _ = make_service(tmp_path)
    driver, passenger = users["driver"], users["passenger"]
    departure = future_departure()
    publish(service, driver, KONDAPUR, VIJAYAWADA, departure)
    with pytest.raises(DomainError):
        search(service, passenger, KONDAPUR, VIJAYAWADA, departure, seats=2)

    first_search = search(service, passenger, KONDAPUR, VIJAYAWADA, departure, seats=1)
    first = act(service, "request", passenger, match_id=first_search["matches"][0]["id"])["booking"]
    second_search = search(service, passenger, KONDAPUR, VIJAYAWADA, departure, seats=1)
    retry = act(service, "request", passenger, match_id=second_search["matches"][0]["id"])["booking"]
    assert retry["id"] == first["id"]


def test_pending_and_hourly_seat_request_limits_are_transactional(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    passenger = users["passenger"]
    # Fill five pending requests: the sixth new trip request must be rejected.
    pending_match = None
    for index in range(5):
        match_id, _trip_id = _seed_match(store, index)
        if index == 0:
            pending_match = match_id
        else:
            # Create unique passenger/trip pending records without needing route math.
            with store.transaction() as tx:
                tx.put("bookings", f"pending-{index}", {"id": f"pending-{index}", "passenger_id": "passenger",
                                                          "driver_id": "driver", "trip_id": f"other-{index}",
                                                          "request_id": f"other-request-{index}", "status": "pending"})
    assert act(service, "request", passenger, match_id=pending_match)["booking"]["status"] == "pending"
    sixth_match, _ = _seed_match(store, 6)
    with pytest.raises(DomainError) as denied:
        act(service, "request", passenger, match_id=sixth_match)
    assert denied.value.status == 429

    # Retire each generated booking while retaining the persisted hourly counter.
    with store.transaction() as tx:
        for row in tx.list("bookings"):
            if row.get("passenger_id") == "passenger":
                row["status"] = "declined"
                tx.put("bookings", row["id"], row)
    with store.transaction() as tx:
        limit = tx.get("seat_request_limits", "passenger")
        assert len(limit["timestamps"]) == 1
        limit["timestamps"] = [now().timestamp() - 30] * 10
        tx.put("seat_request_limits", "passenger", limit)
    rate_match, _ = _seed_match(store, 7)
    with pytest.raises(DomainError) as rate_limited:
        act(service, "request", passenger, match_id=rate_match)
    assert rate_limited.value.status == 429


def test_request_cap_serializes_concurrent_new_requests(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    matches = [_seed_match(store, index)[0] for index in range(7)]

    def request(match_id):
        try:
            return act(service, "request", users["passenger"], match_id=match_id)["booking"]["id"]
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(request, matches))
    assert sum(isinstance(value, str) for value in results) == 5
    assert results.count(429) == 2
    with store.read() as tx:
        assert len([row for row in tx.list("bookings") if row.get("passenger_id") == "passenger" and row.get("status") == "pending"]) == 5
        assert len(tx.get("seat_request_limits", "passenger")["timestamps"]) == 5
