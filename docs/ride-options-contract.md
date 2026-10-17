# Ride options and baggage contract

This contract documents the current local prototype for declared baggage capacity, an optional destination arrival deadline, per-seat quote comparison, and honest search ranks in the existing preview/publish/search/request/accept flow. The newer rate-based quote is an upfront per-seat calculation for the passenger's actual routed segment, enabled only for local development accounts. Its zero platform fee and tax fields are a local preview policy, not a production tariff, tax determination, or approval to collect payment. Production fee/pricing policy remains unconfigured. No payment collection is enabled or driver declaration verified. Existing illustrative contribution calculations remain separate from either quote.

## Offer fields

Trip preview may include:

- `baggage_capacity`: `{ "small_bags": 0..12, "large_suitcases": 0..12 }`. Omission means unknown legacy capacity (`null`), never unlimited. A supplied object must contain valid integer counts; unknown fields are rejected.
- `baggage_notes`: optional trimmed text, at most 300 characters, with control characters rejected.
- `seat_price_paise`: optional integer from 0 to 10,000,000 inclusive. It is the driver's fixed, all-inclusive, per-seat amount for every searched segment. Zero is a declared free ride; omission is unknown. Price does not initiate or record payment.
- `seat_rate_paise_per_km`: optional integer from 0 to 10,000,000 inclusive. It is a driver's all-inclusive per-seat rate for local development comparison only. It cannot be supplied together with non-null `seat_price_paise`. The server uses validated provider-reported route-leg distances between this passenger's pickup and dropoff, including shared stops between them. The rate includes tolls and ordinary declared baggage. Passenger fare is `ROUND_HALF_UP(rate_paise_per_km × distance_m / 1000)` in integer paise. Rate-based offers are unavailable to non-development accounts.
- `comfort.air_conditioning`: `yes`, `no`, or `unknown`; omission defaults to `unknown`. This is a driver declaration, not verification.

Publishing preserves these fields. They are fixed by publication in this slice; no edit-price action is added.

## Passenger request fields

Search may include `baggage` with `small_bags` and `large_suitcases`, each an integer from 0 to 12; omission defaults both to zero. `baggage_notes` follows the same text limits. `arrive_by` is optional, timezone-aware, future-dated, within 90 days, and no earlier than `window_start`. It may be earlier than `window_end`, which is a pickup-window bound.

Requests, matches, and bookings carry the passenger baggage counts and notes, `arrive_by`, and the match's `price_quote` snapshot. A legacy flat quote remains `{ "amount_paise": integer, "currency": "INR", "basis": "flat_per_seat", "version": 1 }`. A new route-rate quote is `{ "amount_paise", "currency": "INR", "basis": "passenger_route_per_seat", "version": 2, "fare_paise", "platform_fee_paise": 0, "tax_paise": 0, "driver_net_paise", "rate_paise_per_km", "distance_m", "tolls_included": true, "baggage_included": true, "fee_policy": "local_preview_zero_fees_v1", "route_calculation_id", "route_provider", "calculated_at" }`; `amount_paise` is the final total and equals fare under this local zero-fee policy. The match also stores `passenger_route_distance_m` and the route calculation provenance. Distances and provenance come from server routing only; absent or invalid provider leg distances mean the route-rate offer cannot match or be requested. Flat v1 stored rows are not reinterpreted.

## Capacity and acceptance

Only `accepted` and `segment_completed` bookings consume seat or baggage capacity, on their half-open route segment. `baggage_remaining` reports the minimum actually available across the candidate segment before counting the current passenger's request, just like `available_seats`; it is not a reservation. Pending requests do not reserve either. Cancellation releases capacity; a completed segment stays in historical inventory. For a legacy trip with unknown baggage capacity, zero-bag requests remain eligible, while any positive baggage request is incompatible. Unknown is not treated as unlimited. Existing legacy bookings with no baggage declaration conservatively consume the listed capacity.

Search evaluates baggage and arrival deadlines against the proposed itinerary. Acceptance repeats route, seat, baggage, pickup-window, and arrival-deadline checks inside the existing SQLite write transaction before changing the booking to accepted. Concurrent acceptance must not oversubscribe any segment. The accepted booking stores the requested bag counts and locked quote. A rate quote is validated on request against the published rate and the original stored search route evidence, then copied verbatim to the booking. Acceptance validates against that authoritative saved match and published rate; it never recalculates the fare using a later route. The original quote evidence stays intact even when shared-stop changes alter the acceptance route. Tampered or stale snapshots fail with conflict; no amount silently changes. Existing accepted bookings keep their stored deadline and are rechecked when another request changes the itinerary. Requests continue to use the existing 20-minute match expiry.

## Ranks

Each match has `ride_ranks` with one-based ranks: `best`, `fastest`, and nullable `cheapest` and `comfort`. Rank criteria use only persisted match fields:

- `fastest`: estimated `dropoff_at`, then `pickup_at`, then stable trip ID. This is routing-provider time, without traffic or walking estimates.
- `cheapest`: known quoted amount ascending, then arrival and stable trip ID. Unknown prices receive `null`, not a zero rank; a declared free quote is zero and ranks first.
- `comfort`: only driver-declared A/C=`yes` qualifies; order by estimated arrival, then known price, then stable trip ID. `no` and `unknown` receive `null`.
- `best`: with an arrival deadline and at least one known quote, known lower prices rank first, then arrival, then stable trip ID (`lowest_price_before_deadline`). Otherwise use earliest estimated arrival, then known lower price, then stable trip ID (`earliest_dropoff`). No opaque weighted or safety score is used.

Search returns `ranking_context.best_basis` and each match's `ride_ranks`; default match order is ascending `best` rank. Legacy saved matches remain readable and can receive ranks calculated only from their stored arrival, quote, and declaration fields; missing quotes remain unknown, and the selected basis is explicit in `ranking_context`.

Authenticated state also returns the current user's most recent saved search as `latest_search: { saved_search: true, saved_at, request, matches, metrics, metrics_source, ranking_context }`, or `null` if the user has no search. Only matches belonging to that request are returned. Existing rank fields are used when present; legacy saved matches may be ranked from their stored arrival/quote/declaration fields using the same deterministic helper. Matches for trips that are no longer future, published, eligible, or unblocked are filtered out; known match-count metrics are recalculated from the visible set and `metrics_source` identifies this saved-search/current-eligibility view. This is a saved result, not fresh inventory: accepting still rechecks eligibility and capacity, and the match's existing 20-minute request window still applies.

All baggage, price, and comfort values are driver/passenger declarations. They are not independently inspected or verified. The existing payment implementation remains unchanged and separate.
