"""Synthetic Flask app imported by the bounded Gunicorn journey check.

This module is test-only. It deliberately constructs the ordinary app factory
with an isolated SQLite path, fake OTP delivery, and deterministic routing.
It never imports the hosted WSGI entry point or reads ambient provider secrets.
"""

from __future__ import annotations

import os

from app import create_app
from test_lifecycle import FixtureRoadProvider
from test_phone_http import SMSFixture


database_path = os.environ["SEATPAL_JOURNEY_DB"]

app = create_app({
    "TESTING": True,
    "HOSTED_MODE": False,
    "DATABASE_PATH": database_path,
    "SECRET_KEY": "isolated-gunicorn-journey-signing-key-only",
    "BETA_PASSWORD": "isolated-gunicorn-journey-seed-password",
    "PHONE_AUTH_ENABLED": True,
    "PHONE_AUTH_PROVIDER": SMSFixture(),
    "PHONE_AUTH_HMAC_KEY": "synthetic-gunicorn-phone-key-" * 2,
    "PHONE_AUTH_DAILY_LIMIT": 1000,
    "DEMO_PASSWORD_ENABLED": False,
    "DIRECT_UPI_ENABLED": False,
    "BACKUP_EMAIL_ENABLED": False,
    "VOICE_ENABLED": False,
    "PUBLIC_OPERATOR_NAME": "Synthetic journey operator",
    "PUBLIC_SUPPORT_EMAIL": "journey@example.test",
})

app.extensions["beta_service"].router = FixtureRoadProvider()
# This isolated fixture creates 23 accounts through the public phone endpoints
# in one bounded run. Relax only its local synthetic admission counters; the
# deployed rate-limit defaults and provider controls are not being evaluated.
app.extensions["phone_auth"].limits = {
    name: 1000 for name in app.extensions["phone_auth"].limits
}
