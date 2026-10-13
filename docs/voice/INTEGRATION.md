# Native voice integration and release runbook

Status: 2026-10-07. The user approved temporary microphone-audio upload to their RouteShare server. The authenticated HTTP integration and offline local-model inference are implemented and locally validated. The earlier upload-authorization block is historical. The user subsequently approved deployment for testing. Railway deployment `12f42891-2454-4174-b0f3-11c90de5452d` reached SUCCESS at `2026-10-07T17:33:53.675Z`, with public hosted health HTTP 200. This deployed service uses 2 vCPU / 3 GiB, `VOICE_ENABLED=1`, and `VOICE_DAILY_LIMIT=100`. Actual hosted backend smoke passed 42 checks, including repeated English/Telugu public-clip transcription, cancellation, responsive health and exact quota debit. Browser EN/TE navigation/picker checks and seven deployed asset hashes passed, with a gray home-preview-map exception; the web has no native recording controls. Private container cleanup/resource inspection is not yet verified in this evidence record. Source defaults remain voice disabled; this is not a TestFlight or physical-microphone claim.

## User behavior and guarantees

Voice helps a signed-in member enter an English or Telugu trip draft. It does not book a ride. The native client checks server capability before asking for microphone permission or recording. A missing native recorder, disabled server, unavailable language, exhausted daily allowance, permission denial, or failed request leaves typed trip entry available. A known zero allowance disables Listen; the fresh pre-recording check also stops before permission/capture if the allowance is zero. Missing or malformed quota data fails closed as unavailable. Hindi UI offers an explicitly labelled English voice fallback; Hindi ASR is outside this slice.

1. **Listen:** starts one foreground recording after permission and capability checks. Spoken playback stops first. The interface explains that a clip goes to the RouteShare server and is deleted after processing or cancellation. The recording is bounded to 45 seconds and 2 MiB; the server independently checks decoded duration and bytes.
2. **Stop:** finalizes the local AAC/M4A clip and uploads it with the signed-in member's bearer token and a unique request ID. The server runs the selected local model and returns editable text. It does not resolve a place or write a trip/booking from that request.
3. **Cancel, Back, background, language/account change, or leaving the component:** stops local recording/playback, rejects stale results, aborts the client request, and, if an upload was actually submitted, attempts owner-scoped server cancellation. Capability-only checks and cancelled recordings that were never submitted abort locally without a cancel POST. Cancellation transport is bounded and best effort; server upload/job deadlines and logout revocation remain independent controls. Local file cleanup is feature-scoped, including marked leftovers recovered after an interrupted app run.
4. **Review:** the user can edit the transcript or enter each place separately. Parsed locations are queries, not verified coordinates. The user must choose actual places, date/time and seats, explicitly search, review the offered route/meeting points, and explicitly confirm a request. Empty or incomplete details do not automatically search or book. A spoken ride ordinal selects a draft choice; it cannot authorize a booking.
5. **Spoken replies:** use the installed device text-to-speech voice. If no matching voice is available, replies remain visible as text. Telugu playback quality and real-phone audio behavior still need device validation.

The voice service does not write audio or transcripts to the application database or application logs. Audio exists transiently in bounded memory and a private temporary job directory; normal success, failure, cancellation, timeout and shutdown remove that directory. Startup cleans only matching dead-process voice roots. A hard process/device termination can leave a temporary file until that cleanup runs; this is not a guarantee of instantaneous deletion after a crash. User-approved trip fields can later be saved by the separate normal trip/booking flow.

## Authenticated HTTP contract

All three routes require a signed-in member. Native requests use `Authorization: Bearer …`; existing browser same-origin/CSRF rules remain in force. Staff/nonmember access is rejected. Authentication and admission happen before upload parsing.

| Action | Request | Result |
|---|---|---|
| Capability | `GET /api/voice/capabilities` | `{available, languages, max_seconds, max_bytes, daily_remaining, reset_at}`; languages are available `en`/`te` models only. Bounds are 45 and 2097152. `daily_remaining` is a nonnegative integer; `reset_at` is UTC RFC3339 exactly `YYYY-MM-DDTHH:mm:ssZ`. Availability checks runtime/model support separately from the allowance, so the client must also check the remaining count. It is not an accuracy or load guarantee. |
| Transcribe | `POST /api/voice/transcribe`; `multipart/form-data` with exactly `audio`, `language`, `request_id`; matching UUID in `X-Voice-Request-ID` | `{request_id, text, language, duration_ms}`. Duplicate fields, unsupported language, malformed IDs, empty audio or extra parts are rejected. The client validates the response before applying it. |
| Cancel | `POST /api/voice/cancel`; JSON `{request_id}` | `{request_id, cancelled: true}` scoped to the authenticated owner. A cancellation tombstone also prevents a delayed upload for that request from starting. |

Do not manually supply a multipart boundary in the native client; `FormData` supplies it. Clips must be no more than 2 MiB, and the entire multipart body has a 2 MiB + 16 KiB limit. The decoder enforces the 45-second limit independently of client metadata. WAV and AAC/M4A decoding have local validation evidence; an arbitrary file extension is not evidence of valid audio.

The service-wide daily allowance defaults to **100 admitted clips per UTC day**, shared across all members and both languages. An atomic transaction in the existing SQLite database consumes a slot before body parsing. A subsequently invalid, failed, timed-out or cancelled admitted job still counts; there is no refund. Capability reads, cancellation alone, unauthenticated/staff requests, busy admission and requests cancelled before admission do not consume a slot. Day/count records persist across app restarts, with no account/session/request ID/audio/transcript fields. A quota storage failure fails closed as `VOICE_UNAVAILABLE`. `daily_remaining` is a snapshot, so a later upload can still receive `VOICE_DAILY_LIMIT`. The next UTC midnight starts a new date bucket; the UI shows its explicit UTC reset and typed fallback, with no automatic recording/retry. SQLite serialization protects the last quota slot when sharing that same database; it does not make other process-local voice/live-location state safe for multi-replica deployment.

The service admits one job at a time in the existing single-process backend, with at most six starts per owner in 60 seconds. It maintains at most one inference child, switching models rather than loading English and Telugu children concurrently. Upload reads have a 15-second bound; the whole admitted job has a 75-second deadline. Idle inference exits after 60 seconds. Cancellation IDs are retained for 120 seconds to reject late/replayed work. These controls are process-local; keep the current one Gunicorn worker / eight threads and one service replica until shared admission and lifecycle state are designed.

Native network bounds are 15 seconds for capabilities, 90 seconds for transcription, and 5 seconds for best-effort cancellation. Logout revokes authentication and cancels the owner's active work. The HTTP handler rechecks authentication and cancellation before returning text, so a completed late inference cannot restore a cancelled draft.

| Response | Meaning and recovery |
|---|---|
| `400 VOICE_INVALID_AUDIO` | Invalid form, ID, language or decoded audio; record again or type. |
| `413 VOICE_INVALID_AUDIO` | Recording/body exceeds the size limit; use a shorter clip. |
| `422 VOICE_NO_SPEECH` | No clear speech; retry or edit/type. |
| `429 VOICE_DAILY_LIMIT` | Daily service allowance exhausted; response includes `daily_remaining: 0` and `reset_at`. Client blocks further microphone starts, shows the UTC reset and offers typing; retry only through a later explicit user action. |
| `429 VOICE_BUSY` | Admission/rate bound reached; retry later or type. |
| `503 VOICE_UNAVAILABLE` | Disabled/missing runtime/model or failed worker; typed entry remains available. |
| `504 VOICE_TIMEOUT` | Upload/job exceeded its bound; retry explicitly with a new request ID. |
| `409 VOICE_CANCELLED` | Cancelled or stale/replayed request; discard its result. |
| `401` / `403` | Missing/revoked authentication or insufficient role; do not retry with another account's request. |

Device permission, unsupported-language and network errors are also shown in the native UI. Cancellation is not shown as a transcription failure. No error path automatically creates a ride, searches, or retries audio indefinitely.

## Models and configuration

English uses the pinned Systran multilingual Whisper-small conversion with explicit English; Telugu uses the pinned AI4Bharat IndicWhisper Telugu model converted to CPU INT8. Exact sources, hashes, licenses and preparation commands are in [README.md](README.md) and [models.json](models.json). The runtime uses local model files only: no external inference service, API key, or request-time model download. The image build may download the pinned model inputs; that is separate from processing a user's recording.

| Variable | Configuration |
|---|---|
| `VOICE_ENABLED` | Defaults to `0`/false. Set `1` only in an approved release configuration. |
| `VOICE_DAILY_LIMIT` | Default `100`; integer from 1 to 1000. Limits admitted service-wide clips per UTC day, not the hosting invoice. Increasing it is a release/configuration decision. |
| `VOICE_MODEL_PATH_EN` | Absolute verified English model directory; image path `/opt/route-share-models/en`. |
| `VOICE_MODEL_PATH_TE` | Absolute verified Telugu model directory; image path `/opt/route-share-models/te`. |
| `HF_HUB_OFFLINE` | Image sets `1`; local-only loading also applies inside the worker. |
| `HF_HUB_DISABLE_IMPLICIT_TOKEN` | Image sets `1`; model acquisition does not need user account credentials. |
| `EXPO_PUBLIC_API_URL` | Native app's authenticated RouteShare API origin; HTTPS required except loopback development. |

Existing hosted secrets and `/data` persistence requirements are unchanged. Model files belong in the image/model directory, not the application database or source repository. Keep recordings, benchmark audio, model weights, signing keys, credentials and generated app exports out of Git and source uploads.

## Validation and release sequence

Completed local and hosted evidence:

- Hosted exact-deployment backend smoke: **42 checks passed**. English public-clip timings were 4.132 / 3.919 seconds; Telugu 16.136 / 14.936 seconds. All four transcripts returned 200 with matching request/language and no-store headers. Active-job cancellation returned in 518 ms and ended the job with 409/no text; busy admission, health, logout/revocation and 100→95 quota debit passed. Only one public clip per language was repeated; this does not validate general recognition quality or a real microphone. The HTTP-only run did not inspect server files. See local `work/free-voice-deployment-evidence.md` for the evidence path and final deployment checks.

- Backend suite: **203 passed, 4 skipped** in 35.76 seconds. The four optional decoder cases were skipped in the base interpreter and separately covered in the installed speech runtime; do not interpret a skip as a pass.
- Pre-quota authenticated real HTTP: public CC-BY-4.0 FLEURS English and Telugu recordings each transcribed twice using actual local model subprocesses. All four returned 200 and left zero temporary recording files. This is a small functional sample, not a language-quality benchmark or microphone test.
- Pre-quota production server configuration locally: Gunicorn 26.2.0 / Python 3.12.12, unchanged one-worker `gthread`/eight-thread configuration. Real public English inference returned 200; slow-upload cancellation and logout returned 409. Health and control requests stayed below one second in these checks; shutdown removed roots and children. This was a local server test, not a Railway deployment.
- Quota validation: **66 focused tests passed, 4 optional decoder skips**; the full final suite above includes the quota changes and actual threaded TCP slow-upload/cancel/logout checks. Covered restart/app recreation, exact UTC midnight, concurrent last-slot consumption, admitted failure/cancel counts, excluded denied/busy/capability requests, storage read/write failure, reservation cleanup, and responsive same-token logout while waiting for quota storage. Source fingerprints were independently checked against `/tmp/route-share-voice-validation/quota-final-evidence.json`. The separate real-model/Gunicorn evidence predates the quota delta.
- Model preparation: **11 integrity tests passed**; verified model hashes, offline English/Telugu loading and audio decoding under Linux x86_64 Python 3.12.12. Runtime had no Torch. The local Docker build was initially blocked by an unavailable engine. The later authorized Railway Docker build succeeded with image SHA-256 `abf0e7645c4c7153908aacfe9c0d8531519a17af4200cc0fae8c3690ac517507`; full deployment reached SUCCESS. Live hosted checks are being recorded separately.

Native source checks and their explicitly dated fingerprints are recorded in [mobile/BUILD_EVIDENCE.md](../../mobile/BUILD_EVIDENCE.md): 44/44 voice unit checks after the quota delta (owner-reported), mounted voice/App fixtures, TypeScript and locale parity passed. The refreshed quota-aware iOS/Android JavaScript exports contain the exact hosted API origin, English/Telugu catalogs and daily-quota contract. Six mounted EN/TE quota cases passed for initial zero, preflight zero and post-Stop 429; these checks preserve typed explicit review without an upload retry. Current hashes are recorded in the build evidence; pre-quota hashes are historical. Earlier exports missing the origin were rejected. They are not signed native binaries. Mounted-component tests mock native audio/API behavior; they cannot establish real microphone or device cleanup behavior.

Before release:

1. Source/type/locale checks and the Railway Docker build/startup have passed. Complete live hosted inspection, memory and functional checks; retain physical-device lifecycle gates separately.
2. The user approved the testing deployment, and the root owner applied only RouteShare beta limits of 2 vCPU / 3 GiB with 100 admitted clips/day. The **$25 monthly hosting budget applies to RouteShare alone**. Monitor actual service spend; model licenses and the daily quota do not establish a fixed hosting invoice.
3. On the approved hosted configuration, measure peak English/Telugu memory and latency, sequential model switching, repeated use, concurrent busy responses, slow upload, cancellation/logout, health responsiveness and recording cleanup. The approved testing deployment has voice enabled on the existing single-replica design. Disable `VOICE_ENABLED` for rollback; typed trip entry must continue working.
4. Produce native **build 2** with the approved recorder dependencies, then test on a real iPhone: grant/deny permission; English and Telugu recording; spoken reply availability; Stop/Cancel; Back/background/reopen; language/account changes; weak/offline network; missing server capability; repeated use; and review-only trip behavior. Confirm the previously reported OS-ASR crash is absent on the device; removal of that source path alone is not proof.
5. Archive/sign/upload build 2 only after those gates and the relevant release authorization. **Quota-aware voice source compiled and installed in the Mac simulator, but no signed build-2 distribution or TestFlight upload is confirmed.** The locked Mac prevented launch/runtime initialization and microphone/UI lifecycle verification. The current simulator build targets `http://127.0.0.1:5059` with no model inference enabled, passed standard simulator ad-hoc signature verification, and must never be uploaded as the production release. Historical build-1 evidence below the latest section in `mobile/BUILD_EVIDENCE.md` does not establish today's App Store Connect state.

## Assumptions and cuts

This slice targets native English/Telugu trip entry, explicit editable review, typed fallback, foreground recording and locally hosted inference. It cuts Hindi ASR, background audio, automatic booking, external inference providers, recording retention and multi-instance inference coordination. Real-phone Telugu recognition/playback quality and sustained hosted resource cost remain unverified. The Railway Docker build/deployment succeeded; actual live functional/capacity evidence is recorded separately.
