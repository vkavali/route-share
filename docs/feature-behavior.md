# Profile, chats and notifications: behavior contract

This document describes the current local prototype behavior. It is not a
claim that the service is ready for public or commercial use.

## Profile and contact sharing

- A signed-in user can save their display name, optional phone number, and a
  separate opt-in that allows an eligible trip counterpart to request their
  number. The saved profile is returned by the server; verification state is
  read-only. Editing a phone number does not verify it.
- Phone sharing defaults to the value saved on the profile. An unchecked box
  means the server will not reveal the number through the contact endpoint.
- A participant can request contact details only from an accepted booking
  whose trip is published or started, where the counterpart has opted in,
  supplied a number, and neither participant has blocked the other. The number
  is fetched only after the user presses the contact button. The UI offers a
  `tel:` link for 15 seconds, then removes it. The prototype does not place a
  call or send an SMS itself.
- Errors leave the profile draft available for correction/retry. A failed
  contact request shows an unavailable message and does not expose a number.

## Chat

- A participant can read the latest 100 messages for their own booking. Opening
  a conversation best-effort marks incoming messages read through the latest
  unread message; failure to save that marker does not hide the conversation.
- Sending is enabled only when the server reports `can_send: true` for an
  accepted booking with a published or started trip and no block. The server
  remains authoritative and enforces participant access, message length,
  rate limits, and idempotency.
- A send uses a client-generated idempotency key. If a request fails after it
  may have reached the server, retrying the same text reuses that key so a
  response timeout does not create a duplicate. The draft is retained on
  failure, including if the user edits while a request is pending.
- A completed booking may have readable history, but the server disables
  sending. Blocked or otherwise ineligible conversations are unavailable or
  read-only according to the server response.
- Chat and notification lists refresh every 20 seconds while their page is
  visible, the account is signed in, and the browser tab is foregrounded.
  Refresh does not replace a focused draft. Polling stops on navigation or
  sign-out. Network errors show a retry action; no message is fabricated.

## Notifications

- The list contains saved server notifications, not local reminders. The
  notification response contains identifiers, type, timestamps and optional
  booking/message IDs; it does not contain contact details, message bodies or
  live location.
- Marking one read is persisted by the server. Opening a notification attempts
  to save its read state, then opens the bookings view even if that save fails.
- Empty accounts show an empty state. Failed loads show an error and retry
  action.

## Data and safety limits

- These flows use the shared server API and persistence layer. Client caches,
  unsent drafts, and any contact link are cleared or invalidated on logout or
  account change. Requests started under an earlier account or page generation
  cannot update the newly mounted view.
- Development accounts remain explicitly unverified. A phone check is not
  presented as identity verification. Ratings, completed-trip counts, and
  route-distance figures are shown only when returned from persisted data;
  route distances are estimates, not environmental-impact claims.
- There is no end-to-end encryption, emergency dispatch, automatic calling,
  SMS, verified identity provider, or human translation review in this slice.
  Before a real pilot, the operator still needs legal/insurance review,
  production authentication and phone verification, operational safety
  handling, and production data/backup controls.
