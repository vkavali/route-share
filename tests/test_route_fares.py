"""Focused distance-based route-fare contracts using synthetic routing only."""
from datetime import datetime, timedelta

import pytest

from app.domain import DomainError
from test_lifecycle import (
    FixtureRoadProvider,
    KONDAPUR,
    NANDIGAMA,
    SURYAPET,
    VIJAYAWADA,
    act,
    future_departure,
    make_service,
)
from test_account_isolation import reviewed_real_driver


RATE_FIELD = "seat_rate_paise_per_km"


class FareLegRouter(FixtureRoadProvider):
    """Return controlled, visibly non-chainage passenger road legs."""

    name = "FIXTURE ONLY - controlled passenger route legs"

    def __init__(self, *, include_legs=True, segment_m=47_000):
        super().__init__()
        self.include_legs = include_legs
        self.segment_m = segment_m

    def route(self, points):
        result = super().route(points)
        result["calculation_id"] = f"fixture-route-{len(points)}-{points[0]['label']}-{points[-1]['label']}"
        if self.include_legs:
            if len(points) == 4:
                # [driver origin, passenger pickup, passenger drop, driver destination]
                passenger_leg = self.segment_m
                if points[2].get("label") == VIJAYAWADA["label"] and self.segment_m == 47_000:
                    passenger_leg = 83_000
                result["leg_distances_m"] = [8_000, passenger_leg, 6_000]
            else:
                result["leg_distances_m"] = [12_000] * (len(points) - 1)
        return result


def _rate_payload(*, rate=1_250, departure=None, flat=None, **extra):
    payload = {
        "origin": KONDAPUR,
        "destination": VIJAYAWADA,
        "departure": departure or future_departure(),
        "seats": 3,
        "max_detour_minutes": 15,
        RATE_FIELD: rate,
    }
    if flat is not None:
        payload["seat_price_paise"] = flat
    payload.update(extra)
    return payload


def _publish_rate(service, driver, *, rate=1_250, departure=None, flat=None, **extra):
    preview = act(service, "preview", driver,
                  **_rate_payload(rate=rate, departure=departure, flat=flat, **extra))["preview"]
    return preview, act(service, "publish", driver, preview_id=preview["id"])["trip"]


def _search(service, passenger, departure, origin=SURYAPET, destination=NANDIGAMA):
    start = datetime.fromisoformat(departure)
    return act(
        service,
        "search",
        passenger,
        origin=origin,
        destination=destination,
        window_start=start.isoformat(),
        window_end=(start + timedelta(hours=8)).isoformat(),
        seats=1,
    )


def _expected_v2_quote(*, rate, distance_m, provider, route_id, calculated_at):
    # The test inputs below yield integral paise after half-up rounding.
    fare = (rate * distance_m + 500) // 1_000
    return {
        "amount_paise": fare,
        "currency": "INR",
        "basis": "passenger_route_per_seat",
        "version": 2,
        "fare_paise": fare,
        "platform_fee_paise": 0,
        "tax_paise": 0,
        "driver_net_paise": fare,
        "rate_paise_per_km": rate,
        "distance_m": distance_m,
        "tolls_included": True,
        "baggage_included": True,
        "fee_policy": "local_preview_zero_fees_v1",
        "route_calculation_id": route_id,
        "route_provider": provider,
        "calculated_at": calculated_at,
    }


def test_rate_quote_uses_only_passenger_route_legs_and_persists_through_accept(tmp_path):
    service, _, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    preview, trip = _publish_rate(service, users["driver"], departure=departure)
    assert preview[RATE_FIELD] == trip[RATE_FIELD] == 1_250

    result = _search(service, users["passenger"], departure)
    match = result["matches"][0]
    assert match["passenger_route_distance_m"] == 47_000
    assert match["passenger_route_distance_m"] != trip["route"]["distance_m"]
    assert match["passenger_route_distance_m"] != match["end_m"] - match["start_m"]
    quote = _expected_v2_quote(
        rate=1_250,
        distance_m=47_000,
        provider=match["price_quote"]["route_provider"],
        route_id=match["price_quote"]["route_calculation_id"],
        calculated_at=match["price_quote"]["calculated_at"],
    )
    assert match["price_quote"] == quote
    assert quote["fare_paise"] == 58_750
    assert quote["amount_paise"] == quote["driver_net_paise"] + quote["platform_fee_paise"] + quote["tax_paise"]

    booking = act(service, "request", users["passenger"], match_id=match["id"])["booking"]
    assert booking["price_quote"] == quote
    accepted = act(service, "accept", users["driver"], booking_id=booking["id"])["booking"]
    assert accepted["price_quote"] == quote


@pytest.mark.parametrize(
    ("distance_m", "expected_distance_m", "expected_fare"),
    [(499.4, 499, 0), (499.5, 500, 1), (1_499.5, 1_500, 2)],
)
def test_distance_and_paise_round_half_up(distance_m, expected_distance_m, expected_fare, tmp_path):
    service, _, users, _ = make_service(
        tmp_path, router=FareLegRouter(segment_m=distance_m)
    )
    departure = future_departure()
    _publish_rate(service, users["driver"], rate=1, departure=departure)
    match = _search(service, users["passenger"], departure)["matches"][0]
    quote = match["price_quote"]
    assert match["passenger_route_distance_m"] == expected_distance_m
    assert quote["distance_m"] == expected_distance_m
    assert quote["fare_paise"] == quote["amount_paise"] == expected_fare


def test_same_offer_charges_short_and_long_passenger_segments_separately(tmp_path):
    service, _, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    _, trip = _publish_rate(service, users["driver"], rate=1_000, departure=departure)
    short = _search(service, users["passenger"], departure, SURYAPET, NANDIGAMA)["matches"][0]
    long = _search(service, users["passenger2"], departure, SURYAPET, VIJAYAWADA)["matches"][0]

    # The route provider is the fare-distance authority, not the driver's full-trip distance.
    assert short["trip_id"] == long["trip_id"] == trip["id"]
    assert short["price_quote"]["distance_m"] == short["passenger_route_distance_m"]
    assert long["price_quote"]["distance_m"] == long["passenger_route_distance_m"]
    assert short["price_quote"]["distance_m"] != long["price_quote"]["distance_m"]
    assert short["price_quote"]["fare_paise"] != long["price_quote"]["fare_paise"]


@pytest.mark.parametrize(
    "value",
    [True, 1.5, float("nan"), float("inf"), -1, 10_000_001],
)
def test_rate_rejects_non_integer_nonfinite_negative_and_over_cap_values(value, tmp_path):
    service, _, users, _ = make_service(tmp_path)
    with pytest.raises(DomainError):
        act(service, "preview", users["driver"],
            **_rate_payload(rate=value))


def test_flat_and_distance_rates_cannot_be_set_together(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    with pytest.raises(DomainError):
        act(service, "preview", users["driver"],
            **_rate_payload(rate=1_250, flat=30_000))


def test_distance_rate_preview_is_limited_to_development_drivers(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    preview = act(service, "preview", users["driver"],
                  **_rate_payload(rate=1_250))["preview"]
    actual_driver = reviewed_real_driver(store, users["driver"]["id"])
    # A preview created while local-dev access was active cannot be published
    # after the persisted account has transitioned to a reviewed real account.
    with pytest.raises(DomainError) as revoked:
        act(service, "publish", actual_driver, preview_id=preview["id"])
    assert revoked.value.status == 403
    with pytest.raises(DomainError) as denied:
        act(service, "preview", actual_driver,
            **_rate_payload(rate=1_250))
    assert denied.value.status == 403


def test_zero_rate_is_free_and_missing_or_unusable_route_distance_is_unknown(tmp_path):
    free_dir = tmp_path / "free"
    free_dir.mkdir()
    free_service, _, free_users, _ = make_service(free_dir, router=FareLegRouter())
    departure = future_departure()
    _publish_rate(free_service, free_users["driver"], rate=0, departure=departure)
    free = _search(free_service, free_users["passenger"], departure)["matches"][0]
    assert free["price_quote"]["amount_paise"] == 0
    assert free["price_quote"]["fare_paise"] == free["price_quote"]["driver_net_paise"] == 0

    unknown_dir = tmp_path / "unknown"
    unknown_dir.mkdir()
    unknown_service, _, unknown_users, _ = make_service(
        unknown_dir, router=FareLegRouter(include_legs=False)
    )
    _publish_rate(unknown_service, unknown_users["driver"], departure=departure)
    unknown = _search(unknown_service, unknown_users["passenger"], departure)
    assert unknown["matches"] == []


def test_rate_quote_missing_evidence_cannot_pass_request_or_accept_as_none_none(tmp_path):
    service, store, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    _, trip = _publish_rate(service, users["driver"], departure=departure)
    match = _search(service, users["passenger"], departure)["matches"][0]

    # Corrupt persisted fare evidence to the exact None==None trap; a failed quote
    # computation must not make an invalid offer requestable.
    with store.transaction() as tx:
        row = tx.get("matches", match["id"])
        row["price_quote"] = None
        row.pop("passenger_route_distance_m", None)
        tx.put("matches", row["id"], row)
    with pytest.raises(DomainError) as invalid_request:
        act(service, "request", users["passenger"], match_id=match["id"])
    assert invalid_request.value.status == 409

    # Acceptance independently validates quote evidence after a booking exists.
    match = _search(service, users["passenger2"], departure)["matches"][0]
    booking = act(service, "request", users["passenger2"], match_id=match["id"])["booking"]
    with store.transaction() as tx:
        saved_match = tx.get("matches", match["id"])
        saved_match["price_quote"] = None
        saved_match.pop("passenger_route_distance_m", None)
        tx.put("matches", saved_match["id"], saved_match)
        saved_booking = tx.get("bookings", booking["id"])
        saved_booking["price_quote"] = None
        saved_booking["match"]["price_quote"] = None
        saved_booking["match"].pop("passenger_route_distance_m", None)
        tx.put("bookings", saved_booking["id"], saved_booking)
    with pytest.raises(DomainError) as invalid_accept:
        act(service, "accept", users["driver"], booking_id=booking["id"])
    assert invalid_accept.value.status == 409


def test_rate_change_invalidates_new_request_and_pending_accept_but_not_idempotent_retry(tmp_path):
    service, store, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    _, trip = _publish_rate(service, users["driver"], departure=departure)
    stale_match = _search(service, users["passenger"], departure)["matches"][0]
    with store.transaction() as tx:
        row = tx.get("trips", trip["id"])
        row[RATE_FIELD] = 2_500
        tx.put("trips", row["id"], row)
    with pytest.raises(DomainError) as stale_request:
        act(service, "request", users["passenger"], match_id=stale_match["id"])
    assert stale_request.value.status == 409

    # A pending booking owns its original request terms; a retry is idempotent.
    changed_preview, changed_trip = _publish_rate(
        service, users["driver2"], rate=1_000, departure=departure
    )
    new_match = _search(service, users["passenger2"], departure)["matches"]
    new_match = next(match for match in new_match if match["trip_id"] == changed_trip["id"])
    booking = act(service, "request", users["passenger2"], match_id=new_match["id"])["booking"]
    with store.transaction() as tx:
        row = tx.get("trips", changed_trip["id"])
        row[RATE_FIELD] = 2_000
        tx.put("trips", row["id"], row)
    retry = act(service, "request", users["passenger2"], match_id=new_match["id"])["booking"]
    assert retry["id"] == booking["id"]
    assert retry["price_quote"] == booking["price_quote"]
    with pytest.raises(DomainError) as stale_accept:
        act(service, "accept", users["driver2"], booking_id=booking["id"])
    assert stale_accept.value.status == 409


def test_passenger_cannot_inject_rate_fee_or_quote_and_legacy_flat_quote_stays_v1(tmp_path):
    service, _, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    # A rate offer's only price terms are the driver's saved rate and server route evidence.
    _, trip = _publish_rate(service, users["driver"], departure=departure)
    match = _search(service, users["passenger"], departure)["matches"][0]
    injected = act(
        service,
        "request",
        users["passenger"],
        match_id=match["id"],
        **{RATE_FIELD: 1, "platform_fee_paise": 1, "tax_paise": 1,
           "price_quote": {"amount_paise": 1}},
    )["booking"]
    assert injected["price_quote"] == match["price_quote"]
    assert injected["price_quote"]["amount_paise"] != 1

    # A previously published flat quote remains a v1 flat amount; it is never treated as a rate.
    flat_service, flat_store, flat_users, _ = make_service(tmp_path / "legacy", router=FareLegRouter())
    flat_departure = future_departure()
    flat_preview = act(flat_service, "preview", flat_users["driver"], **{
        "origin": KONDAPUR, "destination": VIJAYAWADA, "departure": flat_departure,
        "seats": 2, "max_detour_minutes": 15, "seat_price_paise": 30_000,
    })["preview"]
    flat_trip = act(flat_service, "publish", flat_users["driver"], preview_id=flat_preview["id"])["trip"]
    with flat_store.transaction() as tx:
        legacy = tx.get("trips", flat_trip["id"])
        legacy.pop(RATE_FIELD, None)
        tx.put("trips", legacy["id"], legacy)
    legacy_match = _search(flat_service, flat_users["passenger"], flat_departure)["matches"][0]
    assert legacy_match["price_quote"] == {
        "amount_paise": 30_000,
        "currency": "INR",
        "basis": "flat_per_seat",
        "version": 1,
    }


def test_published_rate_and_original_quote_remain_locked_after_another_stop_is_accepted(tmp_path):
    service, store, users, _ = make_service(tmp_path, router=FareLegRouter())
    departure = future_departure()
    _, trip = _publish_rate(service, users["driver"], departure=departure)
    first_match = _search(service, users["passenger"], departure, SURYAPET, NANDIGAMA)["matches"][0]
    first = act(service, "request", users["passenger"], match_id=first_match["id"])["booking"]
    first_accepted = act(service, "accept", users["driver"], booking_id=first["id"])["booking"]
    original_quote = first_accepted["price_quote"]

    later = _search(service, users["passenger2"], departure, NANDIGAMA, VIJAYAWADA)["matches"][0]
    second = act(service, "request", users["passenger2"], match_id=later["id"])["booking"]
    act(service, "accept", users["driver"], booking_id=second["id"])
    state = act(service, "state", users["driver"])
    saved_first = next(row for row in state["bookings"] if row["id"] == first["id"])
    assert saved_first["price_quote"] == original_quote

    # A changed published rate cannot replace the frozen acceptance quote.
    with store.transaction() as tx:
        changed = tx.get("trips", trip["id"])
        changed[RATE_FIELD] = 2_500
        tx.put("trips", changed["id"], changed)
    assert next(row for row in act(service, "state", users["driver"])["bookings"]
                if row["id"] == first["id"])["price_quote"] == original_quote
