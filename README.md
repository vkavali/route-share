# SeatPal — route sharing beta

An India intercity route-sharing beta with a Flask/SQLite API, a browser client, and an Expo/React Native mobile client. Private vehicle owners publish trips they already planned; passengers find compatible routes and request a seat. The server saves booking decisions and enforces segment capacity, current driver approval, participant permissions and temporary foreground location sharing.

Current source includes public phone-OTP signup/sign-in, required profile and policy consent, private driver-document applications and staff review, participant contribution/payment acknowledgements, and completed-trip reviews. Members can enroll a saved recovery code, recover to a new verified phone, or request account deletion after resolving active travel/payment blockers and reauthenticating. Owner-declared expense budgets reserve contributions across the trip and require a positive owner share. Phone ownership is separate from driver approval; direct UPI records are manual acknowledgements, not bank settlement verification.

Phone signup is implemented but **live activation is not configured or verified**: the MSG91 account/widget contract, real SMS delivery, stable private identity key, explicit message allowance and real operator contact must pass the gates in [docs/phone-auth-release.md](docs/phone-auth-release.md). `PHONE_AUTH_ENABLED` and `DIRECT_UPI_ENABLED` default off. SeatPal is the current display name; `APP_DISPLAY_NAME` controls the public policy-page label, not native identifiers or store metadata.

Hosted web beta: https://route-share-beta.up.railway.app. Check the dated release evidence for the deployed source snapshot and activation status; the URL alone does not establish that this checkout is deployed or public signup is active.

## Run locally

Use Python 3.11 or newer. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 server.py
```

Open http://127.0.0.1:5000. The development server only accepts loopback binding. Local fixture usernames are `driver`, `passenger`, `passenger2`, and `admin`; their default password is `local-beta-only`. These are local development fixtures and are separate from hosted credentials.

`.env.example` documents optional environment variables. The Python server reads the process environment; it does not automatically load `.env` files. To change the local fixture password, start with `BETA_PASSWORD='your-local-password' python3 server.py` against a new development database. Local data is stored under ignored `work/` by default.

```sh
python3 -m pytest -q tests
```

The optional `python3 scripts/live_e2e.py` contacts the public routing service and writes separate local evidence under `work/`.

## Mobile client

See [mobile/README.md](mobile/README.md) for API configuration, local setup, and native build prerequisites. With Node 20.19 or newer:

```sh
cd mobile
npm ci
npm run sync:shared
npm run typecheck
npm run start
```

iOS and Android JavaScript exports are available through the npm scripts. An export is not a signed app binary. Existing TestFlight build 3 predates the current account/phone changes; they require a fresh native build and device verification. This README does not assert current Apple processing/review status or a production App Store release; see the dated evidence in [mobile/BUILD_EVIDENCE.md](mobile/BUILD_EVIDENCE.md).

## Hosted runtime

`Dockerfile` starts the validated Gunicorn entry point in `hosted.py`. It requires a persistent `/data` volume and environment variables `ROUTE_SHARE_HOSTED=1`, `PUBLIC_ORIGIN`, `BETA_DATABASE`, `BETA_SECRET_FILE`, and `BETA_ACCOUNT_PASSWORDS`. Database and secret-file paths must be separate absolute paths beneath `/data`. Configure account passwords through the hosting provider's secret settings; never commit them. The hosted runtime fails closed when required configuration is missing.

## Scope and limits

The public phone-account implementation is separate from the existing password-protected development and staff identities. New payment collections require active, individually phone-verified non-development participants and a currently human-reviewed owner with the listed vehicle; shared demo approvals cannot unlock real UPI collection. Authorized reconciliation of earlier agreements remains separate. Local tests use an injected provider; they do not prove real SMS delivery or authorize production activation. New phone members receive no driving/staff privileges. Driver evidence review records a human decision, not government authentication, police clearance or insurance approval.

Map search, routes and tiles depend on external services; their availability is not guaranteed. Location sharing is explicit, foreground-only, temporary, and is not emergency dispatch. Expense budgets enforce a declared aggregate ceiling; they do not verify receipts, calculate a fair segment allocation or prove actual costs. Automatic bank settlement/refunds remain absent. Recovery requires a previously saved code; it does not protect ordinary OTP sign-in from reassigned phone numbers. Deletion retains disclosed terminal transaction/safety records and an abuse-prevention phone reservation. Chat views exclude messages older than 90 days, with bounded primary-store cleanup; backup and provider retention are separate. A staffed review/support process and settled operating policy remain launch requirements. No real-ride or customer-demand validation is claimed.

Private SQLite snapshot and new-destination restore commands are documented in [docs/backup-restore.md](docs/backup-restore.md). A verified same-volume pre-deployment snapshot is a protective copy, not off-host disaster recovery.

Current account behavior is documented in [docs/account-flows-contract.md](docs/account-flows-contract.md), [docs/phone-auth-contract.md](docs/phone-auth-contract.md), [docs/account-lifecycle-contract.md](docs/account-lifecycle-contract.md) and [docs/phone-auth-release.md](docs/phone-auth-release.md). Existing behavior and privacy decisions remain in [docs/feature-behavior.md](docs/feature-behavior.md) and [docs/beta-permission-contract.md](docs/beta-permission-contract.md). [docs/adr-001-closed-beta.md](docs/adr-001-closed-beta.md) and dated pilot-readiness research record earlier scope/findings; they do not supersede approved public signup/direct UPI or establish current launch readiness.

Source, reproducible dependency lockfiles, and required runtime assets belong in this repository. Credentials, environment files, databases, dependency installs, local evidence/screenshots, generated exports, signing material, and agent caches are excluded. Bundled fonts/icons/vendor libraries retain their license and provenance files.
