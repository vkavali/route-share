# Private identity and driver-document review contract

Status: locally implemented, 11 October 2026. The current full Python suite passed **757 tests with 4 skipped** (optional PyAV voice-decoder cases). The [sequential-checklist QA report](../output/playwright/staff-review-checklist-20261011/report.md) records **82 browser assertions and 18 loopback HTTP checks** passing with synthetic evidence. Native TypeScript typecheck, shared-translation parity and the identity/driver component test harness pass; native APIs and preview components are mocked in that harness. Earlier [protected-preview QA](../output/playwright/document-view-only-20261011/report.md) separately covered page rendering, export controls and wider viewport sizes. **This feature is not deployed. No native device build or physical-device verification was completed. This document does not mean it is externally verified or ready for public activation.**

## Product and job

This is for an adult about to join or offer a planned intercity trip with someone they do not know, initially on the Hyderabad–Mahabubnagar corridor. Today, confidence may depend on exchanging documents outside the app, repeated explanations and unclear screenshots. That exposes private information and gives neither person a dependable current status.

The job is to collect the minimum supported evidence privately, produce an accountable human decision, and enforce its current validity before a new ride commitment. The one thing that must remain trustworthy on a second visit is the meaning and freshness of the displayed review status. Without that, an attractive badge would make the product less trustworthy.

The review is **private human document review**. It is not government authentication, automated KYC, biometric liveness, police clearance or a guarantee of safety.

## Separate evidence phases

| Phase | What a completed phase means | What it never implies automatically |
|---|---|---|
| Phone verification | A successful configured OTP flow established control of a phone number at that time. | Legal identity, adulthood, a valid licence or ownership of a vehicle. |
| Human identity review | An authorized reviewer inspected every page in the current submitted evidence through the confidential, watermarked preview, checked readability/name/photo/adult evidence and recorded a decision with an expiry. | Authenticity confirmed by an issuing authority, automated face matching, liveness or police clearance. |
| Driver-document review | An authorized reviewer inspected every page of the named driver's current licence, listed vehicle RC, insurance and selfie in the confidential, watermarked preview under the driver application contract. | Government-record validation, permission for every transport business model, insurer coverage of this particular service, or safety. |
| Government-record validation | Reserved for a configured, authorized provider returning a verified result tied to the actual submitted record. | Face/liveness matching or a background check. Not connected by this manual-review slice. |
| Face/liveness | Reserved for a supported consented provider process with a completed result. | A matching government record or absence of criminal history. A selfie upload is not liveness. |
| Background/police check | Reserved for the accepted process and completed evidence appropriate to the operator's jurisdiction. | A guarantee against future misconduct. Not performed by this slice. |
| Boarding PIN/challenge | A separate trip-scoped confirmation, if subsequently implemented, can associate boarding with an accepted booking. | Identity verification, account login or consent to location sharing. No boarding PIN is added by this contract. |

A general database field such as `verification.identity = verified` must not be rendered as an unqualified government-verified badge. The UI must interpret the approval kind, source and expiry, and label it **Identity documents reviewed** or equivalent natural Telugu. An explicit reviewer `rejected` or `revoked` decision overrides an independent driver-backed identity approval and blocks current identity eligibility. Ordinary member withdrawal removes approval derived from that identity application while preserving an independent valid source. The distinction is server-enforced and must remain covered by tests.

## Roles and evidence

- **Member travelling as a passenger:** verified phone plus a current identity approval for new non-development bookings. Identity application: legal name, selected document type, adult attestation, explicit private-review consent, one identity-document upload and a selfie. A passenger need not hold a driving licence; it is only one supported identity option.
- **Member offering a trip:** the same current identity requirement plus current manual driver approval tied to the listed vehicle, licence, RC, insurance and selfie. Passenger identity approval alone cannot unlock publishing or driving.
- **Reviewer:** an active staff account with explicit `verify.review` capability. Staff status without this capability is insufficient. Reviewers cannot approve their own application.
- **Development/demo accounts:** isolated synthetic evidence and development approvals remain visibly distinct. They do not acquire real-person verified status and cannot establish production collection/ride eligibility.

Supported identity types are `driving_licence`, `passport` and `voter_id`. Do not request or accept raw Aadhaar or PAN in this workflow. Client copy and server validation must agree. Licence/passport expiry is required; voter ID may lack a printed expiry but its review is still time-bounded. Accepted identity evidence is PDF/JPEG/PNG; selfie is JPEG/PNG. Limits and actual content validation are server-authoritative.

## Member actions and state guarantees

| Action | Saved change and result | Empty, invalid, slow or conflicting state |
|---|---|---|
| Open identity review | Return the member's own application, requirements, service availability and current state. No application is a normal empty state. | Missing encryption configuration yields an honest unavailable state, not a sample approval or provider success. |
| Save/reopen a draft | Save legal name, type and strict boolean declarations; increment version. A material edit returns the application to `draft` and invalidates approval derived from that application. | Submitted applications cannot be silently edited: withdraw first. Invalid type, empty name or malformed consent is rejected without a partial save. |
| Upload/replace evidence | Validate content and expiry; encrypt bytes before storage; attach a new document identifier and deletion deadline; increment version. Replacement invalidates the previous evidence's review eligibility. | Unsupported/oversized/expired evidence or a stale version fails explicitly. A progress indicator is not successful storage. Retrying after an uncertain result must first reconcile the current version. |
| Submit | Require both current readable evidence objects, adult declaration and review consent. `draft → submitted`; make the application eligible for staff review. | Missing, deleted or expired evidence blocks submission. There is no automatic approval and no guaranteed turnaround claim. |
| Read a decision | Return `needs_changes`, `rejected`, `approved` or `revoked`, an appropriate private reason and current expiry. | A decision on stale evidence cannot silently apply to replacement evidence. Changes/rejection can be corrected through a fresh draft and resubmission. |
| Withdraw | Delete the application's primary evidence, remove its private submitted fields as specified by the service, set `withdrawn`, increment version and invalidate the approval derived from it. | A pending reviewer must receive a conflict when attempting a stale approval. Withdrawal does not cancel trips, erase unpaid obligations or imply a refund. |
| Expire | At the earlier of document expiry or approval limit, approval is no longer current; maintenance records `expired`. | Gates evaluate current time, not only a cached green UI badge. Re-review needs current evidence. |

States: no application, `draft`, `submitted`, `needs_changes`, `rejected`, `approved`, `revoked`, `expired`, `withdrawn`. Explicit actions and server state determine available controls; the UI must not infer permission from a locally stored status.

## Reviewer actions and concurrency

The queue and staff previews are accessible only through the authorized reviewer path. Native clients require both staff status and the `verify.review` capability before loading or rendering driver review data; losing the capability or receiving an explicit `identity_forbidden`/`verification_forbidden` response from checklist or preview requests clears the selected application, page receipts and preview. Staff inspect page-by-page, server-watermarked JPEG previews returned in authenticated JSON. Native staff review keeps each `data:` image in component memory, offers page navigation and zoom/scroll, and has no original-file download, save or share control. The client records a page as inspected only after its image loads; approval requires every page of every current document and remains server-authoritative. A receipt proves preview delivery, not that the reviewer understood the content; the reviewer must separately affirm the checks. The member's own protected original-document retrieval remains available through the owner path. The app cannot guarantee prevention of operating-system screenshots or screen recording.

Submitted staff review is a sequential checklist, not one bulk checkbox form. The reviewer opens one current document at a time, marks only that step's checks, saves them with the current application version and progress revision, and advances only after the save succeeds. A saved completed step can be revisited or continued without a second preview; a changed/unchecked step must be saved again. Saving a false check invalidates later steps. The selfie step provides a protected link back to the licence/identity document for comparison without losing the selfie draft. A final summary links back through completed steps. A stale revision preserves unsaved local checks and offers an explicit reload that discards them. Request-changes and rejection remain available with a reason even when checklist loading fails; their payload contains the exact required check keys, defaulting unavailable checks to false.

For approval, every step must be complete in server progress for the current application version, no local checks may be dirty, the reviewer must provide an explanatory reason, and the backend must confirm every page of every current document was previewed. The decision also supplies `expected_version`, `idempotency_key` and the exact decision check booleans (`document_readable`, `name_matches`, `photo_matches`, `adult_confirmed` for identity; `dl`, `rc`, `insurance`, `identity_match` for driver review). Approval cannot reuse page receipts or progress from replaced evidence or a stale application version. Approve/request changes/reject applies only to submitted applications; revocation applies to an approved application.

The decision and approval update are atomic and retain actor, time, evidence IDs, checks and result version. Replaying an identical staff idempotency key must not create a second decision; using it for different details is a conflict. Stale versions produce a conflict and require a fresh review, not implicit resubmission. Private reasons are not copied into public trip events.

## Data protection and policy defaults

New identity evidence uses **Fernet authenticated encryption**, including private document blobs and sensitive application text handled by the identity service. The server reads the stable Fernet key from the `IDENTITY_EVIDENCE_KEY` environment setting. The key is checked against a persisted encrypted sentinel; missing or wrong keys make the identity service unavailable, and decryption failure returns an unavailable error without falling back to plaintext. There is no autogenerated production key or fallback plaintext mode. Changing the key is not key rotation: the service has no re-encryption or rotation procedure, and a different key fails the sentinel check, leaving retained ciphertext unreadable until the correct key is restored or a separately designed migration is performed.

This encryption applies only to evidence handled by the new identity service. It does **not** retrofit or re-encrypt existing driver-document blobs in `driver_document_blobs`; those remain under the older storage implementation. Do not describe all identity and driver documents as encrypted at rest based only on `IDENTITY_EVIDENCE_KEY`.

Only the applicant may retrieve the original through the owner document route. An authorized `verify.review` reviewer receives only authenticated, watermarked page previews; other members and trip participants receive only the appropriate status/expiry and necessary identity/vehicle display information, never raw ID/selfie files. These routes are not public asset URLs. Page access and review decisions are auditable without exposing document contents or unredacted secrets in routine logs. In-memory display reduces native export paths but cannot prevent OS screenshots, screen recording or external capture.

**Engineering defaults requiring operator review:** primary uploaded evidence retention is **30 days**; approval lasts no more than **365 days**, capped earlier by the identity document's expiry. A non-expiring voter ID still receives at most 365 days. These numbers are not Rapido policy, statutory requirements or legal advice.

Evidence deletion after retention does not itself extend or renew an approval, and does not imply secure erasure from SQLite WAL, backups, logs or replicas. The identity service runs its maintenance routine during service access and also exposes `maintenance()` through `app.extensions["identity_verification_service"]`; this slice does not configure a background scheduler. Operators must schedule or invoke that operation and monitor failures so deletion and expiry updates happen promptly. An already completed review can retain its bounded decision record while primary upload bytes are deleted. Re-review cannot approve evidence that has already been deleted. Operators must define backup retention, deletion jobs, failure monitoring and access-log/decision-record retention before activation. Withdrawal invalidates the approval tied to the withdrawn application immediately; any independent evidence source remains explicit and valid only under its own current approval.

## Eligibility and existing journeys

- New real/non-development booking requests require verified phone control and current identity approval.
- Publishing a real trip requires current identity approval and current driver approval matching the listed vehicle. Approval is a server authorization condition, not merely a UI badge.
- A legacy driver's prior human-review flag is not enough to silently mint a new identity approval. Only a **new qualifying review** can establish a bounded identity approval from driver evidence; its source, review time and expiry must be recorded. It remains human review.
- Expiry, revocation, material replacement and withdrawal must remove the corresponding new-action eligibility. A second tab or stale session cannot bypass those gates.
- Existing cancellation, safe trip completion, payment reconciliation/refund reporting and support remain available according to their existing participant rules. Identity gating must not trap someone in a trip or obstruct resolving an earlier obligation.
- Identity review does not start GPS, grant contact access outside an eligible booking, charge money, publish a trip, accept a request or approve a payment. Existing consent and trip lifecycle rules remain separate.

## Service/API integration boundary

The current HTTP routes are:

| Method and path | Purpose |
|---|---|
| `GET /api/identity_application` | Read the signed-in member's application and requirements. |
| `POST /api/identity_application` | Save or reopen the member's application. |
| `POST /api/identity_documents` | Upload one identity document or selfie using authenticated multipart form data. |
| `POST /api/submit_identity_application` | Submit a complete draft for review. |
| `POST /api/withdraw_identity_application` | Withdraw the member's application and its uploads. |
| `GET /api/identity_verification_queue` | Read the review queue; requires `verify.review`. |
| `GET /api/identity_review_progress?application_id=…` | Read the authorized identity checklist for a submitted application and its current version/revision. |
| `POST /api/identity_review_progress` | Save exactly one identity checklist step with exact boolean keys and optimistic application-version/progress-revision checks. |
| `GET /api/driver_review_progress?application_id=…` | Read the authorized driver checklist for a submitted application and its current version/revision. |
| `POST /api/driver_review_progress` | Save exactly one driver checklist step with exact boolean keys and optimistic application-version/progress-revision checks. |
| `POST /api/review_identity_application` | Record a reviewer decision; requires `verify.review`. |
| `GET /api/identity_document?document_id=…` | Retrieve the original evidence file for its owner. Staff native review does not call this route. |
| `GET /api/identity_document_preview?document_id=…&page=…` | Return one authenticated, watermarked JPEG page and its page count to an authorized reviewer. |
| `GET /api/driver_document_preview?document_id=…&page=…` | Return one authenticated, watermarked JPEG page from current driver evidence to an authorized reviewer. |
| `GET /api/driver_document?document_id=…` | Retrieve the original driver evidence file for its owner; staff native review does not call this route. |

The routes are registered in `app/__init__.py`; the identity account actions use their exact action names as paths. Application responses contain `{application, requirements}`; queue responses expose authorized applications plus requirements. Applications include ID, user ID, version, status, document type, declarations, approval expiry, private legal name/decision reason and document metadata. Member originals use authenticated owner retrieval; reviewer pixels are generated server-side and returned as `{image_data_url, page, page_count, watermark}`. The identity service encrypts identity evidence as described above; this does not retroactively encrypt driver evidence.

Requirements/availability and server error codes drive clients. Clients preserve non-sensitive form input on recoverable failures, explain expiry/unavailability, refresh after version conflicts, and avoid duplicate decision submissions. Secrets and raw evidence must not appear in analytics or public diagnostics; reviewer screenshots and recordings cannot be technically guaranteed against.

## Activation blockers and acceptance evidence

The current work is a local implementation, not a live verification service. The earlier synthetic browser run covered two member submissions, protected reviewer access, decisions, withdrawal, conflicts, account switching and logout; see the [10 October QA baseline](../output/playwright/identity-review-20261010/report.md). The [11 October protected-preview checks](../output/playwright/document-view-only-20261011/report.md) exercised paginated reviewer previews and their export restrictions, failure recovery, responsiveness and cleanup. The current [11 October sequential-review browser report](../output/playwright/staff-review-checklist-20261011/report.md) records 82 browser assertions and 18 loopback HTTP checks, including identity and driver review at 320px. Current native validation includes TypeScript typecheck, shared-translation parity and mounted identity plus driver reviewer flows for sequential save/resume/back, failed-save preservation, explicit reload, page-gated completion, protected comparison, dirty/false-check approval guards, negative-decision defaults and authorization-denial cleanup, including explicit denial from protected preview requests. The backend full suite is 757 passed and 4 optional PyAV voice-decoder skips; none of those skips are identity-review tests. There is no native device build or physical-device evidence. Before public activation: configure the encryption key and retention operations; establish reviewer staffing, training, access and escalation; approve supported-document/expiry/privacy policy and lawful service eligibility; test the native flow on actual devices; repeat authorization and lifecycle checks in the release environment; and confirm existing trip-resolution paths remain usable.

There is no identity-provider, liveness, face-match, biometric or background-check integration, and no provider call runs in the background. To claim stronger verification requires approved credentials/contracts, a supported consent flow, provider-result authentication, failure/timeout handling, exact identity/vehicle binding and real integration evidence. A mock provider, uploaded screenshot or human review must never be relabelled government validated, liveness checked or police verified. Provider connection is not presumed by shipping this UI.

Required local acceptance paths: empty application → draft → uploads → submission → reviewer previews every page of all evidence → checks/decision → permitted new action; repeat with another account; rejection/changes/resubmission; expired/missing/deleted documents; unavailable encryption; reviewer/self/other-member ACL denial; stale approval after replacement/withdrawal; duplicate decision replay; wrong-key conflict; current approval expiry; back/reload/two tabs; EN/Telugu/Hindi; and retained cancellation/completion/reconciliation/support. Report synthetic fixtures and any absent real provider/device evidence explicitly.

## Research basis

Rapido's public [Captain onboarding](https://www.rapido.bike/become-a-captain) lists licence, RC, profile photo and Aadhaar or PAN. We deliberately do not copy that exact document intake. Its [privacy policy](https://www.rapido.bike/Privacy) describes Captain document/selfie/background information; [customer terms](https://www.rapido.bike/CustomerTerms) reserve requested identity checks but do not prove universal passenger government-ID KYC. Its [current rider listing](https://play.google.com/store/apps/details?id=com.rapido.passenger&hl=en_IN) describes a ride PIN, which is separate from account verification. These are public descriptions, not an authenticated operational audit.

The [Rapido safety PDF](https://www.rapido.bike/RapidoSafetyGuidelines.pdf) is historical (downloaded file metadata dated December 2022), so its detailed checking claims are not evidence of current provider implementation. See [research memo](../output/verification-research-20261010/rapido.md) for source dates and limits. SeatPal's private-owner expense-sharing model must receive its own operating, insurance and verification decisions; commercial Rapido equivalence is not established.
