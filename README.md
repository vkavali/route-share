# RouteShare

An India intercity route-sharing beta with a Flask/SQLite API, a browser client, and an Expo/React Native mobile client. Drivers publish planned trips; passengers search compatible routes and request seats. The server enforces booking decisions, segment capacity, permissions, and temporary foreground location-sharing rules.

Hosted web beta: https://route-share-beta.up.railway.app

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

iOS and Android JavaScript exports are available through the npm scripts. An export is not a signed app binary. No completed TestFlight upload, native device journey, or App Store release is claimed; see [mobile/BUILD_EVIDENCE.md](mobile/BUILD_EVIDENCE.md).

## Hosted runtime

`Dockerfile` starts the validated Gunicorn entry point in `hosted.py`. It requires a persistent `/data` volume and environment variables `ROUTE_SHARE_HOSTED=1`, `PUBLIC_ORIGIN`, `BETA_DATABASE`, `BETA_SECRET_FILE`, and `BETA_ACCOUNT_PASSWORDS`. Database and secret-file paths must be separate absolute paths beneath `/data`. Configure account passwords through the hosting provider's secret settings; never commit them. The hosted runtime fails closed when required configuration is missing.

## Scope and limits

This is an invited beta, with public registration and payments disabled. Identity-provider behavior is a mock boundary. Map search, routes, and tiles depend on external services; their availability is not guaranteed. Location sharing is explicit, foreground-only, temporary, and is not emergency dispatch. No real-ride or customer-demand validation is claimed.

Behavior and privacy decisions are in [docs/feature-behavior.md](docs/feature-behavior.md), [docs/beta-permission-contract.md](docs/beta-permission-contract.md), and [docs/adr-001-closed-beta.md](docs/adr-001-closed-beta.md).

Source, reproducible dependency lockfiles, and required runtime assets belong in this repository. Credentials, environment files, databases, dependency installs, local evidence/screenshots, generated exports, signing material, and agent caches are excluded. Bundled fonts/icons/vendor libraries retain their license and provenance files.
