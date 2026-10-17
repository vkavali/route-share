# Synthetic Gunicorn journey check

`scripts/gunicorn_journey_check.py` runs a bounded synthetic HTTP replay through the repository's actual Gunicorn process configuration. It creates a fresh private temporary directory and SQLite database, starts one Gunicorn process on loopback, exercises phone signup and profile over HTTP with a fake OTP provider, publishes and completes a booking, checks a pre-start cancellation, and sends twenty concurrent acceptance requests for one remaining seat. It then stops and restarts Gunicorn against the same database, snapshots that live database with the online backup CLI, restores to a new path, and reads the completed and cancelled records through a second Gunicorn process.

The journey registers 23 synthetic phone members over HTTP: one driver, two journey passengers, and twenty distinct last-seat contenders. The 20 contenders are not 100 registered users. It uses the existing deterministic `FixtureRoadProvider` and `SMSFixture`; rate counters are raised only in this isolated fixture so the bounded run does not trip the production defaults. The script seeds synthetic development permissions directly into its disposable database so synthetic phone accounts can search, request, and drive. That shortcut does not exercise identity or driver document review. It verifies a flat seat quote and baggage capacity through HTTP and restored storage. It does not call SMS, email, UPI, bank, voice, or live routing providers; payment settlement is not claimed.

The harness imports the ordinary `create_app` factory and overrides Gunicorn's bind to `127.0.0.1`. It still loads `gunicorn.conf.py`, and checks the effective settings are one `gthread` worker with eight threads. It does not use `hosted.py`, so it does not verify Railway's `/data` mount/path checks, hosted HTTPS/origin checks, Railway proxy behavior, or the deployment image. Run it from the intended Linux checkout and virtual environment. The current chatwork Linux test venv is Python 3.10.12; Railway's Docker runtime is pinned to Python 3.12.12, so this process check does not establish runtime parity.

Example from WSL/Linux (replace the checkout and output locations with the current chatwork paths):

```sh
cd /path/to/portable-seatpal
/path/to/seatpal-linux-test-venv/bin/python scripts/gunicorn_journey_check.py \
  --output /path/to/chatwork/work/outputs/seatpal-gunicorn-journey-2026-10-16.json
```

The script deliberately gives the Gunicorn child process a minimal environment rather than inheriting shell provider credentials. It uses only a fresh temporary database and removes that directory on completion. Evidence contains step outcomes, status counts, runtime settings, and database integrity, not cookies, phone numbers, secret values, or raw request/response bodies. A failed run still writes partial sanitized JSON evidence and exits nonzero. The adjacent `.gunicorn.log` contains process startup diagnostics and is created with owner-only permissions.

This is local process evidence only. It does not demonstrate production approval quality, bank transfers, live provider behavior, or disaster recovery from an off-host backup.
