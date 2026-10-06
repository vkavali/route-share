# ADR-001: Closed-beta trust and safety boundary

**Status:** Accepted product decisions; implementation and launch gates remain separate.  
**Scope:** India intercity route-sharing closed beta.  

## Context

This product coordinates adults sharing an existing intercity car journey.
Development records, submitted documents, map pins, and trusted links are not
proof of identity or completed safety checks. The beta is invite-only with
human review, not a public ride-hailing launch.

## Decisions

- **Eligibility and roles.** Members must be adults and attest to their
  birthdate. Driver eligibility is a distinct `driver_approved` decision with
  an expiry. Staff permissions are capability-based: `ops.read`,
  `verify.review`, `safety.act`, and `staff.manage`; only the owner can grant
  or change staff capabilities. A trusted link is a revocable, time-limited
  capability, not an account or a way to become a member.
- **Booking and cancellation.** A personal booking consumes one seat. A
  participant may cancel without a late marker until two hours before pickup;
  later cancellation remains possible but is recorded as late, without a fee
  or other monetary consequence. Three confirmed no-shows trigger human review, never an
  automatic ban. Driver approval requires a current, reviewed driver licence
  and vehicle RC.
- **Privacy and retention.** Precise live location is purged at segment end;
  chat is retained for 90 days; verification documents are deleted at their
  expiry plus 30 days. These are required policy outcomes, not claims about
  current prototype behavior. Staff and trusted-link users receive no live
  GPS, phone numbers, or chat in this beta.
- **Directional live location.** Sharing is explicit and directional. A driver
  may share with the passenger from the earlier of actual trip start or 30
  minutes before pickup through that passenger's segment end. A hard expiry is
  the earlier of scheduled dropoff plus two hours and trip departure plus 24
  hours; actual segment end/arrival ends sharing earlier. A passenger may
  share with the driver from 15 minutes before pickup through boarding. Any
  continuation requires fresh passenger opt-in. Sharing never extends to staff
  or trusted links.
- **Pickup points and detours.** Pickup and dropoff must be public meeting
  points selected on the map and agreed to by the driver at request time.
  Arbitrary pins are a known enforcement gap until this policy is implemented.
  The primary detour is `max(0, OSRM driving duration for the itinerary with
  every accepted stop − immutable original OSRM duration)`. Compare raw seconds
  against the selected 0/5/10/15-minute limit; round only the displayed value
  to minutes. Kilometres are secondary. This is a routing
  estimate, not a traffic-aware guarantee. SQLite writes that protect booking
  inventory must use `BEGIN IMMEDIATE`; the existing store does not use
  `SELECT FOR UPDATE`.
- **Women-only matching.** The product direction is opt-in, self-declared
  gender matching. Eligibility includes the driver and every already accepted
  member. Gender must never be inferred from photos or documents. This feature
  is **not shipped** until a specific policy and consent flow are implemented.
- **Emergency and money.** Emergency 112 is a dialer action, not app dispatch.
  A user can manually share the trip snapshot through the device's OS share
  sheet. Automatic trusted-contact delivery is not implemented and requires an
  external provider, explicit consent, and delivery acknowledgement. The closed beta has no
  paid booking or money collection and makes no legal-readiness claim.

## Alternatives considered

Rejected: automatic no-show bans, staff-visible GPS, late fees, and trusted
links bypassing eligibility. Women-only matching awaits consent policy.

## Launch gates and evidence boundary

The current prototype includes role-aware landing, one-seat booking, ratings,
revocable trusted links, and directional GPS mechanics. Its seeded driver's
30-day development approval is not a licence review or real approval. This does not establish
that adult attestation, retention/deletion, no-show review, licence-expiry,
public-meeting-point enforcement, or women-only policy are complete. A paid
beta remains blocked on Telangana and Andhra Pradesh legal/insurance review,
production identity and licence review, deletion verification, contact and
support operations, and emergency snapshot delivery. See [the beta permission
contract](beta-permission-contract.md).

Counsel and the launch operator must confirm current privacy and emergency
requirements. [MeitY says the DPDP Rules 2025 commence in phases](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit);
this ADR does not claim every provision is in force. [112 India](https://112.gov.in)
is the emergency dialer reference, not evidence of app dispatch.
