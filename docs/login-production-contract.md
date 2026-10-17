# Individual accounts and launch contract

Updated 2026-10-16. This is the intended behavior and release boundary, not a declaration that production activation has passed.

## Customer job

Passengers need an available seat on their actual route; drivers need to publish and manage matching trips. Public passengers and drivers create individual phone-verified accounts. The repeat-use requirement is a dependable search, booking and trip outcome with an upfront total. Shared demo accounts do not satisfy that requirement.

The user has requested profitable driver trips and in-app payments. Existing expense-only contribution rules and manual UPI acknowledgements do not establish either commercial operating authority or a complete payment integration. Resolve that model before enabling paid rides.

## Authentication behavior

- Phone signup verifies the provider result, creates one persistent identity, obtains current policy consent and completes a profile. Returning verified numbers resolve to the same account. OTP delivery errors must remain errors; no production test codes or demo fallback.
- Web and native sessions are separate, revocable credentials. Each request rechecks the current account and session. A user's private bookings, evidence and recovery details must not appear in another user's account.
- Configured staff/development passwords are checked against the saved hash at startup. An unchanged password preserves sessions; a changed password increments the account version and revokes that user's web and native sessions.
- Password checks are followed by a transactional account/version/credential recheck before a session is issued. A concurrent password change or account restriction rejects the stale login.
- Password login attempts share a durable, atomic per-IP limit across web/native endpoints and restarts. Stored scopes contain keyed hashes and timestamps, not raw IPs or submitted account names. Expired scopes are pruned; active-scope capacity is bounded and fails closed.
- A stale browser tab must not submit an operation under a different newly signed-in account. Logout must make its former session unusable. A normal server restart must preserve valid persistent accounts and sessions.
- Concurrent requests for the last available seat must not oversell it. Passenger state must remain scoped to that passenger throughout acceptance, cancellation and retry.

## Booking and routing behavior

- Acceptance calculates the road itinerary outside the database writer lock. Before committing, it rechecks the current account, eligibility, booking, trip, passenger request, accepted inventory, baggage capacity and quoted price. A changed snapshot is recalculated within a bounded retry budget; a stale or unavailable offer returns a conflict rather than accepting altered terms.
- Retrying an already accepted booking returns its existing result. Concurrent acceptances cannot create extra seats. Provider failure produces no partial acceptance writes.
- Search has elapsed-time, provider-call and candidate limits. If only part of the candidates could be evaluated, the result is explicitly incomplete; it does not claim that its first result is the best across all available trips.
- Provider responses and cached routes have size and retention limits. Invalid coordinates, distances and durations are rejected; failure is not replaced by an invented driving route.

## Browser session behavior

- Account changes notify other tabs without storing identity or credentials in browser storage. A new session invalidates responses still in flight from the old one and clears its private views and drafts.
- Sign-out masks private data immediately, retains the original account binding for a retry, and confirms server state before announcing completion. If a different account has since signed in, it requires an explicit continuation instead of signing that account out.
- Returning to a signed-in tab checks the session before showing private content again. Anonymous OTP entry is preserved when the user switches to the SMS app and returns.

## Evidence required before public activation

Real MSG91 signup and returning login, an accurate operator name/support address, current consent, account recovery, reviewed driver/passenger eligibility, gateway-confirmed checkout and refunds, production routing, tested backups and a supported operating area must pass. A test provider proves application wiring only. A local concurrency run is not a production load test.

The first release should be one supported corridor with public signup and recruited driver availability, then expand after successful completed rides. The corridor and applicable state approvals remain to be chosen/confirmed. Keep one deployed application process while live-location leases are in memory; do not add replicas without moving shared live state into a suitable shared store.

Do not enable signup or payment configuration flags merely to make a readiness screen look complete. External credentials and provider verification belong in protected deployment configuration, never source control or reports.
