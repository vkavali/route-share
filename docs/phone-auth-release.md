# Phone signup release and activation

Public signup is for an adult passenger who needs their own account before arranging a shared seat. Provider-confirmed phone control creates or resumes a member account; it does not grant driver approval or verify legal identity. A new member must accept the current terms/privacy notice and adult attestation, then save a name before using travel features.

The current lifecycle/expense-budget candidate passed **600 backend tests**, with four optional local audio-decoder cases skipped because PyAV was unavailable. Local browser evidence includes 14 lifecycle/budget groups, eight further groups after the individual-account collection guard, and three restart-continuity assertions. These are not unit-test counts. Native mounted checks, TypeScript and shared translations passed. The earlier phone-signup milestone's 481 backend passes and 13 browser groups, and the account-only milestone's 360 backend passes and 20 browser groups remain historical evidence. All SMS/account/document fixtures are synthetic: local checks do not establish real SMS delivery, the live MSG91 response contract, production activation or a new native release.

## Configuration

Only placeholder examples belong in `.env.example`. Configure actual values privately on the existing service after review.

| Variable | Required meaning |
| --- | --- |
| `APP_DISPLAY_NAME` | Current display label, `SeatPal`, used on the server-rendered public policy pages. This is not trademark clearance or a change to native identifiers/store metadata. |
| `PUBLIC_OPERATOR_NAME` | Actual accountable operator name; not a placeholder. |
| `PUBLIC_SUPPORT_EMAIL` | Actual monitored operator email with valid syntax. |
| `PHONE_AUTH_HMAC_KEY` | Stable high-entropy secret, at least 32 UTF-8 bytes. Preserve it across replicas, restarts and releases. The persistent fingerprint rejects an incompatible rotation; identity migration is required before changing it. |
| `PHONE_AUTH_DAILY_LIMIT` | Explicit integer from 1 to 100000, chosen for the approved SMS allowance. No unlimited or assumed free allowance. |
| `MSG91_WIDGET_ID` | Identifier for the account's active, six-digit SMS OTP widget. |
| `MSG91_TOKEN_AUTH` | Widget authentication value, kept server-side. |
| `MSG91_AUTH_KEY` | Server credential for access-token verification, kept server-side. |
| `MSG91_CONTRACT_VERIFIED` | Keep `0` until the real configured widget's exact send/verify/server-token-verification contract and failure behavior pass. Then set `1` only for that verified integration. |
| `PHONE_AUTH_ENABLED` | Defaults to `0`. Set `1` only after all activation gates below pass. Missing provider, key, limit or operator configuration keeps signup unavailable. |
| `DEMO_PASSWORD_ENABLED` | Defaults to `1` for existing password-protected development identities and staff access. Keep separate from public phone signup; never migrate or expose demo/staff credentials as customer accounts. |

`DIRECT_UPI_ENABLED` is independent and still defaults off. Enabling phone signup does not authorize collections or a paid SMS purchase. Existing production configuration is unchanged by this source work.

The private operator snapshot and non-overwriting restore commands are documented in [backup-restore.md](backup-restore.md). They preserve the database's phone-key binding but never export the external key. A successful local drill does not establish that hosted or off-host backups are active.

## Activation gates

1. Complete the current phone backend/HTTP, web and native freeze; create a new manifest and archive. Do not deploy the older account-flow milestone as the completed phone-signup release. Both packaging scripts require `app/templates/public-policy.html`; Docker's existing `COPY app/` includes it.
2. Configure the actual MSG91 widget for six-digit SMS delivery. With explicit provider/account authorization, check real delivery and the exact request-bound send → OTP verify → server access-token verification responses. Check wrong/expired codes, resend invalidation and provider failures. Documentation-shaped fixtures do not establish the live account contract; do not bypass `MSG91_CONTRACT_VERIFIED` to make the UI appear enabled.
3. Supply the real operator/support details and review the public `/terms` and `/privacy` pages, including consent versions and current data/retention statements. Configure the stable secret and an approved bounded daily allowance. Do not print provider responses, credentials, codes or phone numbers in release evidence.
4. After the new release is authorized and deployed, inspect `/api/phone/capabilities` and bootstrap: signup must remain unavailable until deliberately enabled and fully configured. Verify the normal Indian-phone (+91) flow, separate browser/mobile sessions, logout, incomplete-profile restriction and returning-account behavior using authorized test numbers. Phone ownership alone must never produce driver/staff approval.
5. Build a fresh native binary from the new frozen source and verify the real phone flow on device before claiming TestFlight readiness. Existing TestFlight build 3 lacks these changes. No current source or package operation sends SMS, deploys, commits or uploads by itself.

Public endpoints are `GET /api/phone/capabilities`, browser `POST /api/phone/{start,resend,verify}`, mobile `POST /api/mobile/phone/{start,resend,verify}`, and authenticated `POST /api/phone/profile`. Policy pages are available without sign-in. The implemented deletion and saved-code phone-recovery endpoints are specified in [account-lifecycle-contract.md](account-lifecycle-contract.md), including fresh purpose/session-bound proof, travel/payment blockers and disclosed retention. They need their own release verification; they do not provide recovery without a saved code or protection against recycled-number OTP sign-in. Staffed support, external retention and approved operating/payment policy remain launch requirements.
