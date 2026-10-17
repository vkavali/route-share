"""Validation and deterministic ranking for declared ride-option fields."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _fail(message):
    # Imported lazily so domain.py can use this module without an import cycle.
    from .domain import DomainError
    raise DomainError(message)


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(f"{name} must be a whole number from {low} to {high}.")
    return value


BAG_KEYS = ("small_bags", "large_suitcases")
MAX_BAGS = 12
MAX_BAG_NOTE = 300
MAX_SEAT_PRICE_PAISE = 10_000_000
MAX_SEAT_RATE_PAISE_PER_KM = MAX_SEAT_PRICE_PAISE


def _note(value, name):
    if value is None:
        return ""
    if not isinstance(value, str):
        _fail(f"{name} must be text of at most {MAX_BAG_NOTE} characters.")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        _fail(f"{name} cannot contain control characters.")
    value = value.strip()
    if len(value) > MAX_BAG_NOTE:
        _fail(f"{name} must be text of at most {MAX_BAG_NOTE} characters.")
    return value


def baggage_counts(value, *, name="Baggage", defaults=False):
    if value is None and defaults:
        value = {}
    if not isinstance(value, dict) or set(value) - set(BAG_KEYS):
        _fail(f"{name} needs small_bags and large_suitcases counts.")
    if not defaults and set(value) != set(BAG_KEYS):
        _fail(f"{name} needs small_bags and large_suitcases counts.")
    result = {}
    for key in BAG_KEYS:
        raw = value.get(key, 0 if defaults else None)
        result[key] = _integer(raw, key, 0, MAX_BAGS)
    return result


def offer_fields(payload):
    """Parse optional driver offer fields; omitted capacity remains unknown."""
    capacity = payload.get("baggage_capacity")
    if capacity is not None:
        capacity = baggage_counts(capacity, name="Baggage capacity")
    note = _note(payload.get("baggage_notes", ""), "Baggage notes")
    raw_price = payload.get("seat_price_paise")
    price = None if raw_price is None else _integer(raw_price, "Seat price", 0, MAX_SEAT_PRICE_PAISE)
    raw_rate = payload.get("seat_rate_paise_per_km")
    rate = None if raw_rate is None else _integer(
        raw_rate, "Seat rate per kilometre", 0, MAX_SEAT_RATE_PAISE_PER_KM
    )
    if price is not None and rate is not None:
        _fail("Choose either a fixed seat price or a per-kilometre seat rate, not both.")
    comfort = payload.get("comfort", {})
    if comfort is None:
        comfort = {}
    if not isinstance(comfort, dict) or set(comfort) - {"air_conditioning"}:
        _fail("Comfort must contain only air_conditioning.")
    ac = comfort.get("air_conditioning", "unknown")
    if not isinstance(ac, str) or ac not in {"yes", "no", "unknown"}:
        _fail("Air conditioning must be yes, no, or unknown.")
    return {
        "baggage_capacity": capacity,
        "baggage_notes": note,
        "seat_price_paise": price,
        "seat_rate_paise_per_km": rate,
        "comfort": {"air_conditioning": ac},
    }


def passenger_fields(payload):
    baggage = baggage_counts(payload.get("baggage", {}), name="Baggage request", defaults=True)
    notes = _note(payload.get("baggage_notes", ""), "Baggage notes")
    return baggage, notes


def price_quote(trip, calculation=None):
    """Return an immutable, searchable quote snapshot (or unknown)."""
    rate = trip.get("seat_rate_paise_per_km")
    if rate is not None:
        if (isinstance(rate, bool) or not isinstance(rate, int)
                or not 0 <= rate <= MAX_SEAT_RATE_PAISE_PER_KM or not isinstance(calculation, dict)):
            return None
        distance_m = calculation.get("passenger_route_distance_m")
        calculation_id = calculation.get("route_calculation_id")
        provider = calculation.get("route_provider")
        calculated_at = calculation.get("route_calculated_at")
        if (isinstance(distance_m, bool) or not isinstance(distance_m, int) or distance_m < 0
                or not all(isinstance(value, str) and value.strip() for value in
                           (calculation_id, provider, calculated_at))):
            return None
        try:
            fare = int((Decimal(rate) * Decimal(distance_m) / Decimal(1000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError, OverflowError):
            return None
        return {
            "amount_paise": fare, "currency": "INR", "basis": "passenger_route_per_seat", "version": 2,
            "fare_paise": fare, "platform_fee_paise": 0, "tax_paise": 0, "driver_net_paise": fare,
            "rate_paise_per_km": rate, "distance_m": distance_m, "tolls_included": True,
            "baggage_included": True, "fee_policy": "local_preview_zero_fees_v1",
            "route_calculation_id": calculation_id, "route_provider": provider,
            "calculated_at": calculated_at,
        }
    amount = trip.get("seat_price_paise")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= MAX_SEAT_PRICE_PAISE:
        return None
    return {"amount_paise": amount, "currency": "INR", "basis": "flat_per_seat", "version": 1}


def same_price_quote(left, right):
    """Compare normalized quote snapshots, including free (zero) vs unknown."""
    return left == right


def baggage_remaining(trip, bookings, start_m, end_m):
    capacity = trip.get("baggage_capacity")
    if not isinstance(capacity, dict) or any(
        isinstance(capacity.get(key), bool)
        or not isinstance(capacity.get(key), int)
        or not 0 <= capacity[key] <= MAX_BAGS
        for key in BAG_KEYS
    ):
        return None
    active = [
        booking for booking in bookings
        if booking.get("status") in ("accepted", "segment_completed")
        and booking.get("start_m", 0) < end_m - .01
        and booking.get("end_m", 0) > start_m + .01
    ]
    boundaries = sorted({
        float(start_m), float(end_m),
        *(max(float(start_m), float(row["start_m"])) for row in active),
        *(min(float(end_m), float(row["end_m"])) for row in active),
    })
    remaining_by_segment = {key: [] for key in BAG_KEYS}
    for segment_start, segment_end in zip(boundaries, boundaries[1:]):
        if segment_end - segment_start < .01:
            continue
        overlapping = [row for row in active if row.get("start_m", 0) < segment_end - .01
                       and row.get("end_m", 0) > segment_start + .01]
        for key in BAG_KEYS:
            used = 0
            for booking in overlapping:
                baggage = booking.get("baggage")
                if not isinstance(baggage, dict) or key not in baggage:
                    # A legacy accepted booking never declared baggage. Conservatively
                    # treat the listed capacity as consumed instead of assuming empty.
                    used += capacity[key]
                    continue
                count = baggage[key]
                if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_BAGS:
                    used += capacity[key]
                else:
                    used += count
            remaining_by_segment[key].append(capacity[key] - used)
    remaining = {}
    for key in BAG_KEYS:
        remaining[key] = min(remaining_by_segment[key]) if remaining_by_segment[key] else capacity[key]
    return remaining


def _timestamp_key(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("inf")


def rank_matches(matches, *, arrive_by=None):
    """Attach 1-based transparent ranks; unknown prices never rank as zero."""
    rows = list(matches)
    if not rows:
        return rows, {"best_basis": "earliest_dropoff"}

    def trip_id(row):
        return str(row.get("trip_id") or "")

    def arrival(row):
        return _timestamp_key(row.get("dropoff_at"))

    def pickup(row):
        return _timestamp_key(row.get("pickup_at"))

    def quote(row):
        item = row.get("price_quote")
        amount = item.get("amount_paise") if isinstance(item, dict) else None
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            return None
        return amount

    def comfort_yes(row):
        comfort = row.get("comfort")
        return isinstance(comfort, dict) and comfort.get("air_conditioning") == "yes"

    def stable(row):
        return (trip_id(row), str(row.get("id") or ""))

    fastest = sorted(rows, key=lambda row: (arrival(row), pickup(row), *stable(row)))
    known_prices = [row for row in rows if quote(row) is not None]
    cheapest = sorted(known_prices, key=lambda row: (quote(row), arrival(row), *stable(row)))
    comfort_rows = [row for row in rows if comfort_yes(row)]
    comfort = sorted(comfort_rows, key=lambda row: (
        arrival(row), quote(row) is None, quote(row) if quote(row) is not None else 0, *stable(row)
    ))

    if arrive_by and known_prices:
        best_basis = "lowest_price_before_deadline"
        best = sorted(rows, key=lambda row: (
            quote(row) is None, quote(row) if quote(row) is not None else 0,
            arrival(row), *stable(row)
        ))
    else:
        best_basis = "earliest_dropoff"
        best = sorted(rows, key=lambda row: (
            arrival(row), quote(row) is None,
            quote(row) if quote(row) is not None else 0, *stable(row)
        ))

    ranks = {
        "best": {row["id"]: index for index, row in enumerate(best, 1)},
        "fastest": {row["id"]: index for index, row in enumerate(fastest, 1)},
        "cheapest": {row["id"]: index for index, row in enumerate(cheapest, 1)},
        "comfort": {row["id"]: index for index, row in enumerate(comfort, 1)},
    }
    for row in rows:
        row["ride_ranks"] = {
            key: ranks[key].get(row["id"])
            for key in ("best", "fastest", "cheapest", "comfort")
        }
    return sorted(rows, key=lambda row: row["ride_ranks"]["best"]), {"best_basis": best_basis}
