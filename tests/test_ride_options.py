"""End-to-end contracts for declared baggage, fixed quotes, and ride ranking."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import DomainError
from app.ride_options import rank_matches
from test_lifecycle import (
    KONDAPUR,
    NANDIGAMA,
    SURYAPET,
    VIJAYAWADA,
    act,
    booking_for,
    future_departure,
    make_service,
    publish,
    search,
    search_between,
)


def _bags(small=0, large=0):
    return {"small_bags": small, "large_suitcases": large}


def _preview(service, driver, *, departure=None, seats=3, capacity=None, price=None,
             ac="yes", notes="", detour=10):
    payload = {
        "origin": KONDAPUR,
        "destination": VIJAYAWADA,
        "departure": departure or future_departure(),
        "seats": seats,
        "max_detour_minutes": detour,
        "comfort": {"air_conditioning": ac},
        "baggage_notes": notes,
    }
    if capacity is not None:
        payload["baggage_capacity"] = capacity
    if price is not None:
        payload["seat_price_paise"] = price
    return act(service, "preview", driver, **payload)["preview"]


def _publish(service, driver, *, departure=None, seats=3, capacity=None,
             price=None, ac="yes", notes="", detour=10):
    preview = _preview(service, driver, departure=departure, seats=seats,
                       capacity=capacity, price=price, ac=ac, notes=notes, detour=detour)
    trip = act(service, "publish", driver, preview_id=preview["id"])["trip"]
    return preview, trip


def _search(service, passenger, departure, *, origin=SURYAPET, destination=NANDIGAMA,
            bags=None, notes="", arrive_by=None, window_end=None):
    at = datetime.fromisoformat(departure)
    payload = {
        "origin": origin,
        "destination": destination,
        "window_start": at.isoformat(),
        "window_end": window_end or (at + timedelta(hours=8)).isoformat(),
        "seats": 1,
        "baggage": bags if bags is not None else _bags(),
        "baggage_notes": notes,
    }
    if arrive_by is not None:
        payload["arrive_by"] = arrive_by
    return act(service, "search", passenger, **payload)


def _request(service, passenger, match):
    return act(service, "request", passenger, match_id=match["id"])["booking"]


def test_offer_and_passenger_options_survive_the_entire_booking_flow(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    preview, trip = _publish(
        service,
        users["driver"],
        departure=departure,
        capacity=_bags(2, 1),
        price=0,
        ac="yes",
        notes="One suitcase in the boot",
    )

    assert preview["baggage_capacity"] == _bags(2, 1)
    assert trip["baggage_capacity"] == _bags(2, 1)
    assert trip["seat_price_paise"] == 0
    assert trip["comfort"] == {"air_conditioning": "yes"}
    assert trip["baggage_notes"] == "One suitcase in the boot"

    arrive_by = (datetime.fromisoformat(departure) + timedelta(hours=8)).isoformat()
    result = _search(service, users["passenger"], departure, bags=_bags(1, 1),
                     notes="One fragile item", arrive_by=arrive_by)
    match = result["matches"][0]
    assert match["passenger_baggage"] == _bags(1, 1)
    assert match["passenger_baggage_notes"] == "One fragile item"
    assert match["trip_baggage_notes"] == "One suitcase in the boot"
    assert match["arrive_by"] == arrive_by
    assert match["price_quote"] == {
        "amount_paise": 0,
        "currency": "INR",
        "basis": "flat_per_seat",
        "version": 1,
    }

    booking = _request(service, users["passenger"], match)
    assert booking["baggage"] == _bags(1, 1)
    assert booking["baggage_notes"] == "One fragile item"
    assert booking["arrive_by"] == arrive_by
    assert booking["price_quote"] == match["price_quote"]
    accepted = act(service, "accept", users["driver"], booking_id=booking["id"])["booking"]
    assert accepted["status"] == "accepted"
    assert accepted["price_quote"] == match["price_quote"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("small_bags", True),
        ("small_bags", 1.5),
        ("small_bags", -1),
        ("small_bags", 13),
        ("large_suitcases", False),
    ],
)
def test_preview_rejects_invalid_baggage_capacity_counts(tmp_path, field, value):
    service, _, users, _ = make_service(tmp_path)
    capacity = _bags()
    capacity[field] = value
    with pytest.raises(DomainError):
        _preview(service, users["driver"], capacity=capacity)


@pytest.mark.parametrize("value", [True, 1.5, -1, 13])
def test_search_rejects_invalid_passenger_baggage_counts(tmp_path, value):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, capacity=_bags(12, 12))
    with pytest.raises(DomainError):
        _search(service, users["passenger"], departure, bags=_bags(value, 0))


@pytest.mark.parametrize("field,value", [("seat_price_paise", True), ("seat_price_paise", 1.5),
                                           ("seat_price_paise", -1), ("seat_price_paise", 10_000_001)])
def test_preview_rejects_invalid_prices(tmp_path, field, value):
    service, _, users, _ = make_service(tmp_path)
    with pytest.raises(DomainError):
        act(service, "preview", users["driver"], origin=KONDAPUR, destination=VIJAYAWADA,
            departure=future_departure(), seats=3, max_detour_minutes=10, **{field: value})


@pytest.mark.parametrize("notes", ["x" * 301, "hello\x00world"])
def test_baggage_notes_reject_overlength_and_control_characters(tmp_path, notes):
    service, _, users, _ = make_service(tmp_path)
    with pytest.raises(DomainError):
        _preview(service, users["driver"], notes=notes)


@pytest.mark.parametrize("comfort", [[], "yes", {"air_conditioning": True},
                                      {"air_conditioning": "sometimes"}, {"heated_seats": "yes"}])
def test_preview_rejects_malformed_or_unknown_comfort_values(tmp_path, comfort):
    service, _, users, _ = make_service(tmp_path)
    with pytest.raises(DomainError):
        act(service, "preview", users["driver"], origin=KONDAPUR, destination=VIJAYAWADA,
            departure=future_departure(), seats=3, max_detour_minutes=10, comfort=comfort)


def test_unknown_legacy_capacity_allows_zero_bags_but_excludes_positive_bags(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA, departure, seats=3)
    with store.transaction() as tx:
        legacy = tx.get("trips", trip["id"])
        legacy.pop("baggage_capacity", None)
        tx.put("trips", legacy["id"], legacy)

    zero = _search(service, users["passenger"], departure, bags=_bags())
    assert len(zero["matches"]) == 1
    positive = _search(service, users["passenger2"], departure, bags=_bags(0, 1))
    assert positive["matches"] == []


def test_pending_requests_do_not_reserve_baggage_and_acceptance_does(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=3, capacity=_bags(1, 0))
    first_match = _search(service, users["passenger"], departure, bags=_bags(1, 0))["matches"][0]
    assert first_match["baggage_remaining"] == _bags(1, 0)
    first_booking = _request(service, users["passenger"], first_match)
    second_match = _search(service, users["passenger2"], departure, bags=_bags(1, 0))["matches"][0]
    second_booking = _request(service, users["passenger2"], second_match)

    assert first_booking["status"] == second_booking["status"] == "pending"
    act(service, "accept", users["driver"], booking_id=first_booking["id"])
    with pytest.raises(DomainError) as unavailable:
        act(service, "accept", users["driver"], booking_id=second_booking["id"])
    assert unavailable.value.status == 409


def test_parallel_acceptance_cannot_overbook_last_baggage_slot(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=3, capacity=_bags(1, 0))
    bookings = []
    for passenger in (users["passenger"], users["passenger2"]):
        match = _search(service, passenger, departure, bags=_bags(1, 0))["matches"][0]
        bookings.append(_request(service, passenger, match))

    def accept(booking):
        try:
            return act(service, "accept", users["driver"], booking_id=booking["id"])["booking"]["status"]
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(accept, bookings))
    assert outcomes.count("accepted") == 1
    assert outcomes.count(409) == 1


def test_adjacent_segments_reuse_baggage_capacity_and_completed_segment_stays_occupied(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure, seats=3,
                       capacity=_bags(1, 0))
    west = _search(service, users["passenger"], departure, origin=SURYAPET,
                   destination=NANDIGAMA, bags=_bags(1, 0))["matches"][0]
    west_booking = _request(service, users["passenger"], west)
    act(service, "accept", users["driver"], booking_id=west_booking["id"])

    east = _search(service, users["passenger2"], departure, origin=NANDIGAMA,
                   destination=VIJAYAWADA, bags=_bags(1, 0))["matches"][0]
    east_booking = _request(service, users["passenger2"], east)
    act(service, "accept", users["driver"], booking_id=east_booking["id"])
    act(service, "start_trip", users["driver"], trip_id=trip["id"])
    act(service, "complete_segment", users["driver"], booking_id=west_booking["id"])

    overlapping = _search(service, users["other"], departure, origin=SURYAPET,
                          destination=VIJAYAWADA, bags=_bags(1, 0))["matches"]
    assert overlapping == []


def test_candidate_spanning_adjacent_accepted_bookings_uses_peak_not_sum_bags(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=3, capacity=_bags(2, 0), detour=15)

    west = _search(service, users["passenger"], departure, origin=SURYAPET,
                   destination=NANDIGAMA, bags=_bags(1, 0))["matches"][0]
    west_booking = _request(service, users["passenger"], west)
    act(service, "accept", users["driver"], booking_id=west_booking["id"])

    east = _search(service, users["passenger2"], departure, origin=NANDIGAMA,
                   destination=VIJAYAWADA, bags=_bags(1, 0))["matches"][0]
    east_booking = _request(service, users["passenger2"], east)
    act(service, "accept", users["driver"], booking_id=east_booking["id"])

    spans_both = _search(service, users["other"], departure, origin=SURYAPET,
                         destination=VIJAYAWADA, bags=_bags(1, 0))
    assert len(spans_both["matches"]) == 1
    candidate = _request(service, users["other"], spans_both["matches"][0])
    assert act(service, "accept", users["driver"], booking_id=candidate["id"])["booking"]["status"] == "accepted"


def test_cancellation_releases_baggage_capacity(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=3, capacity=_bags(1, 0))
    match = _search(service, users["passenger"], departure, bags=_bags(1, 0))["matches"][0]
    booking = _request(service, users["passenger"], match)
    act(service, "accept", users["driver"], booking_id=booking["id"])
    act(service, "cancel_booking", users["passenger"], booking_id=booking["id"], reason="Change of plans")

    result = _search(service, users["passenger2"], departure, bags=_bags(1, 0))
    assert len(result["matches"]) == 1


def test_arrival_deadline_is_preserved_when_new_stop_is_added(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=3, capacity=_bags(3, 0), detour=15)
    unconstrained = _search(service, users["passenger"], departure, origin=SURYAPET,
                            destination=VIJAYAWADA, bags=_bags())
    first_deadline = unconstrained["matches"][0]["dropoff_at"]
    first = _search(service, users["passenger"], departure, origin=SURYAPET,
                    destination=VIJAYAWADA, bags=_bags(), arrive_by=first_deadline)
    assert len(first["matches"]) == 1
    first_booking = _request(service, users["passenger"], first["matches"][0])
    act(service, "accept", users["driver"], booking_id=first_booking["id"])

    # A later requested stop must not make the already accepted passenger miss their deadline.
    later_deadline = (datetime.fromisoformat(departure) + timedelta(hours=8)).isoformat()
    second = _search(service, users["passenger2"], departure, origin=SURYAPET,
                     destination=NANDIGAMA, bags=_bags(), arrive_by=later_deadline)
    assert second["matches"] == []


def test_search_rank_distinguishes_free_from_unknown_price_and_ranks_by_arrival(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    base = datetime.fromisoformat(future_departure())
    earlier = base.isoformat()
    later = (base + timedelta(minutes=30)).isoformat()
    _publish(service, users["driver"], departure=earlier, seats=2,
             capacity=_bags(2, 0), price=None, ac="unknown")
    _publish(service, users["driver2"], departure=later, seats=2,
             capacity=_bags(2, 0), price=0, ac="yes")

    result = _search(service, users["passenger"], earlier, bags=_bags())
    unknown = next(match for match in result["matches"] if match["price_quote"] is None)
    free = next(match for match in result["matches"] if match["price_quote"] is not None
                and match["price_quote"]["amount_paise"] == 0)
    assert free["ride_ranks"]["cheapest"] == 1
    assert unknown["ride_ranks"]["cheapest"] is None
    assert free["ride_ranks"]["comfort"] == 1
    assert unknown["ride_ranks"]["comfort"] is None
    fastest = min(result["matches"], key=lambda match: match["dropoff_at"])
    assert fastest["ride_ranks"]["fastest"] == 1
    assert result["ranking_context"]["best_basis"] == "earliest_dropoff"
    assert unknown["ride_ranks"]["best"] == 1
    assert free["ride_ranks"]["best"] == 2


def test_arrival_deadline_uses_lowest_known_price_as_best_basis(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    base = datetime.fromisoformat(future_departure())
    earlier = base.isoformat()
    later = (base + timedelta(minutes=30)).isoformat()
    _publish(service, users["driver"], departure=earlier, seats=2,
             capacity=_bags(2, 0), price=2_000)
    _publish(service, users["driver2"], departure=later, seats=2,
             capacity=_bags(2, 0), price=1_000)
    arrive_by = (base + timedelta(hours=8)).isoformat()
    result = _search(service, users["passenger"], earlier, bags=_bags(), arrive_by=arrive_by)

    assert result["ranking_context"]["best_basis"] == "lowest_price_before_deadline"
    cheapest = min(result["matches"], key=lambda match: match["price_quote"]["amount_paise"])
    assert cheapest["ride_ranks"]["best"] == 1


def test_stale_quote_cannot_change_after_search_and_request_retry_is_idempotent(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure, seats=2,
                       capacity=_bags(2, 0), price=1_000)
    match = _search(service, users["passenger"], departure, bags=_bags())["matches"][0]
    quote = match["price_quote"]

    with store.transaction() as tx:
        row = tx.get("trips", trip["id"])
        row["seat_price_paise"] = 2_000
        tx.put("trips", row["id"], row)
    with pytest.raises(DomainError) as stale:
        _request(service, users["passenger"], match)
    assert stale.value.status == 409

    # Restore the exact offer; request retries should reuse one active booking and its frozen quote.
    with store.transaction() as tx:
        row = tx.get("trips", trip["id"])
        row["seat_price_paise"] = quote["amount_paise"]
        tx.put("trips", row["id"], row)
    first = _request(service, users["passenger"], match)
    second = _request(service, users["passenger"], match)
    assert first["id"] == second["id"]
    assert first["price_quote"] == second["price_quote"] == quote


def test_latest_search_is_persisted_for_its_owner_only_and_preserves_ranks(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=2,
             capacity=_bags(2, 0), price=1_000)

    assert act(service, "state", users["passenger"])["latest_search"] is None
    result = _search(service, users["passenger"], departure, bags=_bags())
    saved = act(service, "state", users["passenger"])["latest_search"]
    assert saved["saved_search"] is True
    assert saved["request"]["id"] == result["request"]["id"]
    assert saved["ranking_context"] == result["ranking_context"]
    assert saved["matches"][0]["ride_ranks"] == result["matches"][0]["ride_ranks"]

    other = act(service, "state", users["passenger2"])["latest_search"]
    assert other is None
    assert all(match["id"] != saved["matches"][0]["id"] for match in (other or {}).get("matches", []))


def test_state_retains_expired_search_but_request_deadline_still_applies(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=2,
             capacity=_bags(2, 0), price=1_000)
    result = _search(service, users["passenger"], departure, bags=_bags())
    match = result["matches"][0]
    with store.transaction() as tx:
        old = tx.get("matches", match["id"])
        old["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat()
        tx.put("matches", old["id"], old)

    saved = act(service, "state", users["passenger"])["latest_search"]
    assert saved["matches"][0]["id"] == match["id"]
    with pytest.raises(DomainError) as expired:
        _request(service, users["passenger"], match)
    assert expired.value.status == 409


def test_legacy_saved_match_without_baggage_fields_requests_as_zero_bags(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure, seats=2,
             capacity=_bags(2, 0), price=0)
    match = _search(service, users["passenger"], departure, bags=_bags())["matches"][0]
    with store.transaction() as tx:
        saved_match = tx.get("matches", match["id"])
        saved_match.pop("passenger_baggage", None)
        saved_match.pop("passenger_baggage_notes", None)
        saved_match.pop("arrive_by", None)
        tx.put("matches", saved_match["id"], saved_match)
        request = tx.get("requests", saved_match["request_id"])
        request.pop("baggage", None)
        request.pop("baggage_notes", None)
        request.pop("arrive_by", None)
        tx.put("requests", request["id"], request)

    booking = _request(service, users["passenger"], match)
    assert booking["baggage"] == _bags()
    assert booking["baggage_notes"] == ""
    assert booking["arrive_by"] is None
    assert booking["price_quote"] == match["price_quote"]


def test_accept_rejects_quote_changed_after_request_without_changing_booking_quote(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure, seats=2,
                       capacity=_bags(2, 0), price=1_000)
    match = _search(service, users["passenger"], departure, bags=_bags())["matches"][0]
    booking = _request(service, users["passenger"], match)
    with store.transaction() as tx:
        row = tx.get("trips", trip["id"])
        row["seat_price_paise"] = 2_000
        tx.put("trips", row["id"], row)

    with pytest.raises(DomainError) as stale:
        act(service, "accept", users["driver"], booking_id=booking["id"])
    assert stale.value.status == 409
    state = act(service, "state", users["driver"])
    persisted = next(row for row in state["bookings"] if row["id"] == booking["id"])
    assert persisted["status"] == "pending"
    assert persisted["price_quote"] == booking["price_quote"]


def test_empty_search_with_arrival_deadline_has_no_price_basis():
    rows, context = rank_matches([], arrive_by="2030-01-01T12:00:00+05:30")
    assert rows == []
    assert context == {"best_basis": "earliest_dropoff"}


def test_latest_search_match_count_tracks_current_trip_eligibility(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, first_trip = _publish(service, users["driver"], departure=departure,
                             capacity=_bags(2, 0), price=1_000)
    _publish(service, users["driver2"], departure=departure,
             capacity=_bags(2, 0), price=2_000)
    result = _search(service, users["passenger"], departure, bags=_bags())
    assert len(result["matches"]) == 2

    with store.transaction() as tx:
        trip = tx.get("trips", first_trip["id"])
        trip["status"] = "cancelled"
        tx.put("trips", trip["id"], trip)

    saved = act(service, "state", users["passenger"])["latest_search"]
    assert len(saved["matches"]) == 1
    assert saved["metrics"]["route_aware_match_count"] == 1
    assert saved["metrics_source"] == "saved_search_with_current_match_eligibility"
