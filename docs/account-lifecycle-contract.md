# Account lifecycle API contract

Real, non-development phone members only. Staff and seeded demo accounts cannot self-delete or enroll recovery here. Ordinary sign-in remains phone OTP only: a saved recovery code does **not** protect ordinary OTP sign-in against a recycled phone number. No proof-free support override exists when both the old phone and recovery code are lost.

## Authenticated routes

- `GET /api/account/lifecycle` returns `{deletion_allowed,blockers:[],recovery_key_configured,recently_reauthenticated_until,retained_categories:[]}`. The timestamp is null if no current unused proof exists. Blockers are `{code:'active_trip',trip_id}`, `{code:'active_booking',booking_id}` or `{code:'unresolved_payment',booking_id}`. They must be resolved with the actual trip/payment controls; this API never silently cancels a ride or moves money.
- `POST /api/account/reauth/start`: `{purpose:'delete'|'recovery_key',flow_token,request_id}`. Sends only to the account's persisted sign-in phone. Response `{challenge_id,expires_at,resend_at,masked_phone}`. Use the same start endpoint with a new UUID for deliberate resend after cooldown.
- `POST /api/account/reauth/verify`: `{challenge_id,flow_token,code}`. Response `{action_token,expires_at,purpose}`. Proof expires in five minutes, is single-use and bound to the account, captured authentication epoch and this exact live session. Normal sign-in OTP challenges cannot provide this proof.
- `POST /api/account/recovery-key`: `{action_token,recovery_secret,saved:true}`. The client generates the secret as 32 CSPRNG bytes encoded as 43 base64url characters, shows it and requires an explicit saved acknowledgment BEFORE submission. Response `{recovery_key_configured:true}`. Replacing the key invalidates the old key. The server stores only a keyed digest and never returns the supplied plaintext secret.
- `POST /api/account/delete`: `{action_token,confirm:true,idempotency_key:UUID}`. Response `{deleted:true,retained_categories:[...]}`. Requires delete-purpose proof. Revokes all sessions immediately; client clears account state. Root transport clears cookies and stops voice/GPS after commit. A repeated request cannot repeat destructive side effects.

## Lost-phone recovery

Unauthenticated browser `POST /api/account/recovery/start` and `/verify`; native `POST /api/mobile/account/recovery/start` and `/verify`. Root applies existing browser CSRF/origin protection and native cookie/origin rejection.

- Start `{recovery_secret,new_phone,flow_token,request_id}`. The old saved code must be valid BEFORE any SMS is requested. Response is the standard challenge object. Deliberate resend uses start with a new request UUID. Code and phone-account matching details are never disclosed on failure.
- Verify `{challenge_id,flow_token,code,recovery_secret,new_recovery_secret,saved:true}`. The client generates and saves the replacement recovery secret before committing. The account stays the same; its old phone reservation is tombstoned, new phone must not belong to another account, all old sessions/challenges and recovery code are invalidated atomically, and contact sharing becomes false. Existing restrictions are never lifted. Response `{user,onboarding_required}`; native additionally `{token,expires_at}`, web additionally root-supplied rotated `csrf_token`. No recovery code is returned: the client already saved the submitted replacement. A lost response can be recovered through ordinary sign-in to the now verified new phone.

## Deletion boundary

Deletion is blocked by published/started owner trips, pending/accepted bookings, and unresolved agreed/reported/disputed/refund payments. Unpaid agreements require the actual owner's explicit `void_unpaid` transition with a reason; no bank settlement is inferred. Current profile/contact/approval/evidence, payout account, authored chat and ratings, searches/previews, notifications, recovery keys and session material are removed or minimized from primary storage. Terminal counterpart trip/booking history, settled payment facts, restricted safety/audit records and a keyed phone abuse reservation remain. These are named retained categories, not a promise of all-data deletion or a legal retention determination. Database journals, backups and provider records are separate operational retention obligations.

## Error codes

Existing phone challenge/rate/provider errors remain unchanged. Lifecycle errors include `account_unavailable` (401/403), `reauth_required` (401), `invalid_action_proof` (400), `reauth_expired` (410), `invalid_recovery_code` (400), `recovery_save_required` (400), `recovery_unavailable` (400/409), and `account_deletion_blocked` (409, with `blockers`). Secrets/OTP/provider details are never echoed. All responses use no-store.

## Internal integration

`AccountLifecycleService(store, phone_auth, *, mobile_auth=None, clock=None)`. Methods `status(actor,session_binding)`, `reauth_start(actor,payload,session_binding,ip)`, `reauth_verify(actor,payload,session_binding,ip)`, `set_recovery_key(actor,payload,session_binding)`, `delete(actor,payload,session_binding)`, `recovery_start(payload,ip)`, `recovery_verify(payload,ip,native=False)`.

Captured actor includes integer `auth_epoch`. Binding is server-derived `native:<token hash>` or `web:<hash of auth_session_id>`, never taken from a request body. Web sessions are persisted and checked on every authenticated request. Lifecycle final transactions recheck binding liveness and epoch. Root clears current cookie on delete and creates a new epoch-bound cookie/session on recovery. After successful deletion/recovery call the existing `live_locations.stop_actor(user_id)` and `voice_service.cancel_owner(user_id)`; no cleanup callback runs before the database commit.
