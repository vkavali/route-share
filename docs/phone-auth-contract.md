# Phone account contract

Implementation contract, 2026-10-08. Real SMS is disabled until a configured provider and explicit message cap are supplied. No local OTP bypass or public demo code exists. Message caps are not a monetary billing guarantee.

## Clients and routes

- `GET /api/phone/capabilities`: `enabled`, `country_code: "+91"`, `otp_length: 6`, `expires_in: 300`, `resend_after: 60`, `terms_version`, `privacy_version`.
- Web `POST /api/phone/start`, `/resend`, `/verify` require existing same-origin and CSRF protection. Native equivalents are `/api/mobile/phone/start`, `/resend`, `/verify`; they do not require an existing account/bearer. Root API integration owns transport guards.
- The client generates a cryptographically random 32-byte base64url `flow_token` (43 characters), stores it only in memory, and includes it on every challenge call. It is not a device fingerprint or an account token. Losing it means starting a new flow, subject to the same phone cooldown.
- Start body: `{phone, flow_token, request_id}`. Accept ten Indian mobile digits beginning 6–9, or their `+91` representation. `request_id` is a fresh UUID per deliberate send, retained for retries. No names, roles or approval flags are accepted as authority.
- Resend body: `{challenge_id, flow_token, request_id}`. Explicit resend replaces the previous challenge. No automatic retries that send new messages.
- Start/resend response: `{challenge_id, expires_at, resend_at, masked_phone}`. A delivery request accepted by the provider is not a delivery guarantee. No account-existence flag is returned.
- Verify body: `{challenge_id, flow_token, code, consent:{terms_version,privacy_version,terms_accepted:true,privacy_accepted:true,adult_attested:true}}`. `code` is exactly six digits. All three acceptance fields must be literal boolean true. Consent versions must match capabilities; adult attestation is a checkbox, not a birthdate. Acceptance means the terms and privacy notice currently shown to the user are accepted.
- Verify response: `{user, onboarding_required}` for web; native additionally receives the existing opaque `token` and `expires_at`. Web integration rotates cookie/CSRF state. The challenge is consumed atomically: replay does not mint another session. A lost successful response requires a fresh OTP flow; the phone still resolves to the same account.
- `POST /api/phone/profile` is authenticated (cookie or bearer), with `{name}`. It returns `{user,onboarding_required:false}` and completes the required profile. Name is 1–80 characters. Before completion and current consent, member mutations are denied except profile/logout. The root API layer owns this gating.

## Identity and permissions

A verified phone identity is independent of the editable contact number. UUID account IDs cannot collide with seeded accounts. New users are non-development members with no staff grants, no driving approval, phone ownership verified, and all identity/document checks unchecked. OTP is not identity, age or driving verification. Repeated verified sign-in resolves to the same unique phone identity. Disabled/suspended identities remain reserved and cannot be re-created. Shared fixture or staff accounts cannot be claimed through phone OTP.

Existing admin/staff password sign-in remains available. Development-member password login is a separate flag. Current active-account checks apply to cookie and native sessions. Self-service deletion and optional saved-code phone recovery are specified in [the account lifecycle contract](account-lifecycle-contract.md). Deletion removes current personal data from primary storage while retaining the named history and restricted records; backup, database-journal and provider retention remain separate operational obligations. Ordinary OTP sign-in does not prevent access by a recycled number’s new owner.

## Limits and failure behavior

Defaults: five-minute code lifetime, five provider verification attempts per challenge, sixty-second resend cooldown, phone five sends/hour and ten/day, trusted IP ten sends/ten minutes and fifty/day, global ten sends/minute plus an explicitly configured daily cap. Verification has a per-IP budget. Buckets and phone identities persist in SQLite across restarts. Only a trusted edge-derived IP may be supplied; client-provided forwarding headers must not become authority.

Every admitted send, including provider failures and uncertain delivery, consumes its message budget. Provider network calls run outside database transactions. A send or verify lease prevents overlapping calls; generation/expiry/flow/identity are rechecked after the provider returns. The code itself is never stored, returned, or logged. Provider response bodies/exceptions are not exposed. Ephemeral challenge and quota rows are purged after their bounded retention; phone identity reservations persist.

Errors are `{error,code}` with optional `retry_after` seconds:

- 400 `invalid_phone`, `invalid_phone_flow`, `phone_auth_invalid_code`, `consent_required`, `invalid_name`.
- 409 `phone_auth_busy` or consumed/stale `invalid_phone_flow`.
- 410 `phone_auth_expired`.
- 429 `phone_auth_rate_limited`.
- 503 `phone_auth_unavailable` (retryable; never reports success).
- 403 `account_unavailable` only after successful proof of phone ownership, or unavailable profile account.

No phone number, OTP, flow token, provider handle or consent record belongs in general public, operations, or application event projections. The account DTO exposes only safe phone verification and onboarding indicators. Actual policy page URLs and transport wiring are supplied by root integration; do not fabricate a linked policy.
