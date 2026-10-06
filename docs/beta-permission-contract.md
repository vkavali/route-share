# Closed-beta permission and data contract

This contract fixes the intended beta boundary. A feature is not considered
implemented merely because a prototype screen or development record exists.
All sensitive reads and mutations must be enforced by the server, scoped to
the current authenticated actor, and audited where staff action is involved.

## Accounts, roles, and approval

| Actor | Allowed | Explicitly excluded |
| --- | --- | --- |
| Member | Create personal one-seat requests, manage their own bookings, use eligible participant features, and view their own account data. | Acting as an approved driver without current approval; seeing another member's phone or data outside a permitted booking flow. |
| Approved driver | Member actions plus publish/operate trips only while `driver_approved` is true and unexpired. | Treating submitted documents or development fixtures as approval. |
| Staff | Only the assigned capability: `ops.read`, `verify.review`, or `safety.act`. | Implicit access to GPS, phones, chats, or broad account data from a staff role alone. |
| Owner | `staff.manage`, including grant/revoke of staff capabilities. | Delegating owner-only authority. |
| Trusted-link holder | Read the limited public trip snapshot while the token is active. | Account access, member eligibility, GPS, phone numbers, chat, or staff capabilities. |

The adult gate is a birthdate attestation. Driver approval is a separate
reviewed decision and must expire; an expired or revoked approval stops new
driver actions. Driver licence and vehicle registration certificate (RC)
reviews must both be current through their review expiries.
Development-only approval values are fixtures and must never be interpreted as
real identity or licence verification.

Staff actions require capability checks per endpoint, actor ownership checks,
and an audit record that identifies the staff actor, target, action, and time.
`ops.read` does not grant case access; `verify.review` does not grant safety
case action; `safety.act` does not grant account administration. Only
`staff.manage` may assign or revoke these capabilities.

## Booking and cancellation

- One personal booking reserves exactly one seat. A booking cannot reserve
  seats for companions or create a group booking.
- Cancellation remains available at any time. Cancellation at least two hours
  before pickup is not late; cancellation less than two hours before pickup is
  recorded as late. Late cancellation has no monetary penalty. Do not collect
  or imply a fee.
- A no-show counts only after a confirmed no-show event, not simply because a
  person is late or GPS is absent. Three confirmed no-shows create a human
  review case. No automatic ban or account suspension follows from the count.
- Inventory-changing booking operations must execute atomically in SQLite
  using `BEGIN IMMEDIATE`, rechecking capacity and lifecycle conditions within
  the transaction. Do not rely on a UI check or use nonexistent
  `SELECT FOR UPDATE` semantics.

## Location and map permissions

Live GPS is shared only with the specified counterpart, only in the selected
direction, and only after explicit consent where required:

- **Driver to passenger:** sharing begins at the earlier of actual trip start
  and 30 minutes before that passenger's pickup; it ends at that passenger's
  segment end.
- **Passenger to driver:** sharing may begin 15 minutes before pickup and ends
  at boarding. Any later continuation requires a fresh opt-in.
- **Staff and trusted links:** no live GPS access in this contract.
- **End of segment:** precise location is purged. The hard expiry is the
  earliest of actual segment end/arrival, scheduled dropoff plus a two-hour
  delay grace, or trip departure plus 24 hours. No further polling or map
  access may reveal the ended segment's live coordinates.

The current arbitrary map-pin behavior is a known policy gap. Before a beta
claiming this contract, pickup and dropoff must be public meeting points
selected on the map and explicitly agreed by the driver as part of the request.
Do not describe arbitrary pins as satisfying that requirement.

Detour is the non-negative difference, in raw seconds, between the routed
driving duration for the original itinerary and the itinerary including all
accepted stops. Compare the raw result against the selected 0/5/10/15-minute
limit (converted to seconds); round only the displayed value to minutes.
Distance is secondary. This estimate has no live-traffic input and is not a
promised arrival time or maximum delay guarantee.

## Trusted links and emergency actions

A trusted-link token is a bearer capability: it can be forwarded, can be
revoked, and expires at the earlier of the booking's scheduled dropoff or 24
hours after creation. It may be renewed while the booking remains accepted.
Treat possession as
permission to view only the defined public trip snapshot, never as proof of
identity or membership. The snapshot may label the vehicle; it must exclude
live location, phone numbers, chat, and account-only details. No account
creation or authentication bypass is implied. Users may manually share the
snapshot through the device OS share sheet. Automatic trusted-contact push is
not available; it requires a separate provider, explicit consent, and delivery
acknowledgement. Neither path promises emergency response or delivery time.

The emergency 112 action opens the device dialer; it does not call automatically
and the app does not dispatch responders. A separate trip-snapshot share needs
an external delivery provider plus explicit consent and a delivery
acknowledgement. Until that provider path exists, do not represent snapshot
delivery as completed or guaranteed. Do not promise an emergency response time.

## Retention and review

| Data | Required disposition |
| --- | --- |
| Precise live location | Purge at segment end; hard expiry is earlier of actual segment end, scheduled dropoff + 2 hours, or trip departure + 24 hours. |
| Chat messages | Retain for 90 days, then delete. |
| Verification documents | Delete at document expiry plus 30 days. |
| Late-cancellation record | Retain as a non-monetary operational record under a separately approved retention policy. |
| No-show review | Preserve the confirmed event and human-review outcome under a separately approved retention policy. |

The periods above are product requirements, not evidence that deletion jobs or
legal retention obligations are currently satisfied. Verify deletion across
primary storage, backups, exports, logs, and vendor systems before relying on
them. Legal counsel must confirm applicable India and state-specific privacy,
transport, consumer, and insurance duties. The final DPDP Rules are phased;
check current commencement and applicability with counsel rather than treating
all obligations as already effective.

## Features not authorized as shipped behavior

Women-only matching is opt-in and based on a user's self-declaration only. A
candidate is eligible only if the driver and every already accepted member
meet the selected rule. Never infer gender from a name, photo, or document.
This feature remains pending until the eligibility policy, consent, revocation,
and server-side matching checks exist; do not market it before then.

Adult birthdate attestation, retention/deletion, no-show case creation and
human review, licence expiry enforcement, and public-meeting-point enforcement
are also launch requirements that must be separately verified. Current
development fixtures are not proof of those controls. Before inviting real
beta participants, define legal review for Telangana and Andhra Pradesh,
insurance coverage, human support hours and escalation, phone/contact
verification, and emergency snapshot delivery.
