# Verified backup email recovery

For a real SeatPal member who still controls their current phone, Account can
verify a backup email before they lose phone access. Someone who later loses
that phone can verify the saved email, then verify a different Indian mobile
number and regain the same account. Ordinary sign-in remains phone OTP only.
The useful repeat behavior is returning to the same rides/history after phone
replacement. This does not claim protection against recycled phone numbers.

## Behavior

- Adding or replacing an address requires current-phone reauthentication with
  purpose `backup_email`, followed by a code delivered to the new address.
  Unverified addresses cannot recover an account; a pending replacement keeps
  the existing verified address until successful verification.
- Removing it requires a new current-phone action proof. The saved address and
  outstanding email recovery proofs/challenges are deleted immediately.
- Signed-out recovery verifies the saved email first. The resulting opaque
  proof only authorizes verifying a new phone; email alone creates no session.
- Final phone verification atomically changes the existing account's phone,
  rotates its auth epoch, revokes all old browser/mobile sessions, action
  proofs, saved recovery keys and in-progress recovery flows. It retains the
  verified backup email and current account permissions. The old phone remains
  reserved as replaced; an already reserved new phone cannot be taken over.
- A missing/unknown email receives the same generic response and code message.
  It cannot obtain a recovery proof. Sending the same message also avoids using
  email delivery or provider latency as an account-existence signal.
- Only the authenticated account lifecycle response exposes a masked address.
  Public/user DTOs do not include email address, address hash, or verification
  metadata. There is no demo/admin recovery or support proof bypass.

One account has one verified address; an address cannot back multiple accounts.
Addresses use bounded ASCII mailbox syntax, trim outer whitespace and lowercase
both parts. Provider-specific dot/plus alias rewriting is deliberately absent.

## API

`GET /api/phone/capabilities` and bootstrap `phone_auth` add
`backup_email_enabled`. `GET /api/account/lifecycle` adds
`backup_email: {enabled, configured, masked_email, verified_at}`.

All bodies are JSON. `flow_token` is canonical base64url for 32 random bytes;
`request_id` is a UUID. Preserve the flow token for the whole recovery. Resends
call the relevant start endpoint with a new request ID after `resend_at`.

| Auth | POST endpoint | Body | Result |
| --- | --- | --- | --- |
| Member | `/api/account/reauth/start` | Existing phone flow plus `purpose: "backup_email"` | Phone challenge |
| Member | `/api/account/reauth/verify` | Existing phone verification | `action_token`, expiry |
| Member | `/api/account/backup-email/start` | `email`, `action_token`, `flow_token`, `request_id` | `challenge_id`, `expires_at`, `resend_at`, `masked_email` |
| Member | `/api/account/backup-email/verify` | `challenge_id`, `flow_token`, `code` | `backup_email` status |
| Member | `/api/account/backup-email/remove` | `action_token` | `backup_email` status |
| Signed out | `/api/account/recovery/email/start` | `email`, `flow_token`, `request_id` | `challenge_id`, `expires_at`, `resend_at`, generic `message` |
| Signed out | `/api/account/recovery/email/verify` | `challenge_id`, `flow_token`, `code` | `recovery_token`, `expires_at` |
| Signed out | `/api/account/recovery/phone/start` | `recovery_token`, `new_phone`, `flow_token`, `request_id` | Existing phone challenge |
| Signed out | `/api/account/recovery/phone/verify` | `recovery_token`, `challenge_id`, `flow_token`, `code` | Existing authenticated user and browser CSRF token |

The four signed-out routes also exist under `/api/mobile/account/recovery/`;
final verification returns the existing native bearer response. Native public
recovery rejects browser Cookie/Origin headers. Web POSTs retain CSRF protection.
Enrollment routes also accept the existing authenticated native bearer session.

## Failure and concurrency guarantees

- Email OTP: six random digits, five-minute expiry, five attempts maximum,
  60-second resend delay. Resending invalidates the old code. Enrollment also
  remains bounded by its five-minute phone action proof.
- Email recovery proof: ten-minute expiry, bound to the flow, user, auth epoch
  and exact saved email version. It is removed at completed recovery. Old,
  changed, deleted or replayed email/phone proof chains cannot complete.
- Sender admission: 5/hour and 10/day per normalized address; 10/ten minutes
  and 50/day per IP; 20/minute globally plus the configured daily cap.
  Verification has 30/ten minutes per IP and 5,000/day globally. Counters and
  challenge state survive service restarts and are updated atomically.
- Codes and bearer proofs are HMAC-only at rest. Addresses in saved/pending
  records are Fernet encrypted. Neither code nor provider error detail is
  returned/logged by this service. Changing a configured encryption key fails
  startup rather than silently stranding saved addresses.
- Provider calls run outside SQLite write locks. Current session/epoch/email
  version is checked before use and after delivery/provider verification.
- Slow duplicate sends return a busy error. Failed delivery produces no usable
  challenge; after 60 seconds retry with a new request ID. Missing runtime
  configuration fails closed. Deletion removes saved and pending email material.

## Runtime configuration and evidence boundary

Required: the existing configured/ready phone provider and phone HMAC key,
`BACKUP_EMAIL_ENABLED=1`, a stable Fernet `BACKUP_EMAIL_ENCRYPTION_KEY`, bounded
integer `BACKUP_EMAIL_DAILY_LIMIT`, `HOSTINGER_MAIL_API_TOKEN`, and
`HOSTINGER_MAILBOX_RESOURCE_ID`. The application uses its own mail API
credential; a connected Codex mailbox does not give the deployed app access.
`BACKUP_EMAIL_PROVIDER` injection is accepted only for isolated tests.

Automated tests exercise real Flask cookies/bearers and SQLite with fake SMS/mail
transports, including repeat recovery, stale epochs, guessed/replayed/expired
proofs, reserved phones, concurrent verification, replacement/removal, deletion,
resend limits, provider failure and logout during delivery. They do not establish
live SMS/email delivery or inbox placement. Keep the feature disabled until both
providers and persistent secrets are configured and a real delivery path is
validated.
