"""Safe, one-shot diagnostic for the configured MSG91 native REST adapter.

Default operation checks only whether required process environment values have
valid shape. ``--send-test`` probes an unverified provider adapter with one
authorized phone number and one OTP. It is deliberately not an account/signup
test and never changes application configuration or persistent state.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import warnings
import uuid
from collections.abc import Mapping, Sequence
from typing import Callable, TextIO


REQUIRED_NAMES = (
    "MSG91_WIDGET_ID",
    "MSG91_TOKEN_AUTH",
    "MSG91_AUTH_KEY",
    "PHONE_AUTH_HMAC_KEY",
)
PHONE_PATTERN = re.compile(r"\+91[6-9][0-9]{9}\Z")
OTP_PATTERN = re.compile(r"[0-9]{6}\Z")


def _credential_checks(environ: Mapping[str, str]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for name in REQUIRED_NAMES:
        value = environ.get(name)
        if not isinstance(value, str) or not value.strip():
            checks[name] = False
        elif name == "PHONE_AUTH_HMAC_KEY":
            checks[name] = len(value.encode("utf-8")) >= 32
        else:
            checks[name] = len(value) <= 1024
    return checks


def _emit(out: TextIO, **fields: object) -> None:
    out.write(json.dumps(fields, separators=(",", ":"), sort_keys=True) + "\n")
    out.flush()


def _hidden_input(prompt: str, reader: Callable[[str], str]) -> str:
    # getpass can warn and fall back to echoed input. Treat that as refusal.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return reader(prompt)


def run_diagnostic(
    *,
    send_test: bool = False,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., object] | None = None,
    hidden_input: Callable[[str], str] = getpass.getpass,
    tty_check: Callable[[], bool] | None = None,
    out: TextIO = sys.stdout,
) -> int:
    """Run configuration-only mode, or an explicitly requested one-shot probe.

    ``provider_factory``, ``hidden_input`` and ``tty_check`` are injectable only
    to test this wrapper; normal CLI operation uses the production adapter,
    getpass, and the process TTY check.
    """
    values = os.environ if environ is None else environ
    checks = _credential_checks(values)
    if not send_test:
        _emit(out, **checks)
        return 0 if all(checks.values()) else 1

    if not all(checks.values()):
        _emit(out, stage="configuration", ok=False, **checks)
        return 2

    is_tty = tty_check or (
        lambda: sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()
    )
    try:
        if not is_tty():
            _emit(out, stage="tty", ok=False)
            return 2
    except Exception:
        _emit(out, stage="tty", ok=False)
        return 2

    try:
        phone = _hidden_input("Test phone (+91XXXXXXXXXX), hidden input: ", hidden_input)
    except (Exception, KeyboardInterrupt):
        _emit(out, stage="phone_input", ok=False)
        return 2
    if not isinstance(phone, str) or not PHONE_PATTERN.fullmatch(phone):
        _emit(out, stage="phone_input", ok=False)
        return 2

    try:
        code = None
        factory = provider_factory
        if factory is None:
            # The diagnostic must instantiate the real adapter with its gate
            # true to probe it; this setting is local to this process only.
            from app.sms_provider import MSG91Provider

            factory = MSG91Provider
        provider = factory(
            widget_id=values["MSG91_WIDGET_ID"],
            token_auth=values["MSG91_TOKEN_AUTH"],
            auth_key=values["MSG91_AUTH_KEY"],
            handle_secret=values["PHONE_AUTH_HMAC_KEY"],
            contract_verified=True,
        )
        handle = provider.send(phone, challenge_id=str(uuid.uuid4()), expires_in=300)
    except (Exception, KeyboardInterrupt):
        _emit(out, stage="send", ok=False)
        return 1

    try:
        code = _hidden_input("Six-digit SMS code, hidden input: ", hidden_input)
    except (Exception, KeyboardInterrupt):
        _emit(out, stage="otp_input", ok=False)
        return 2
    if not isinstance(code, str) or not OTP_PATTERN.fullmatch(code):
        _emit(out, stage="otp_input", ok=False)
        return 2

    try:
        verified = provider.verify(handle, code)
    except (Exception, KeyboardInterrupt):
        verified = False
    _emit(out, stage="verify", ok=verified is True)
    return 0 if verified is True else 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == []:
        return run_diagnostic(out=sys.stdout)
    if arguments == ["--send-test"]:
        return run_diagnostic(send_test=True, out=sys.stdout)
    # Avoid argparse echoing an unexpected token that a caller might have
    # mistakenly supplied as a secret command-line argument.
    _emit(sys.stdout, stage="arguments", ok=False)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt):
        # Never surface provider exception text or a traceback that might
        # contain credentials, phone numbers, OTPs, handles or access tokens.
        _emit(sys.stdout, stage="diagnostic", ok=False)
        raise SystemExit(1)
