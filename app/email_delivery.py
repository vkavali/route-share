"""Fail-closed Hostinger Mail API adapter for account verification codes.

Uses Hostinger's HTTPS API so delivery does not depend on Railway SMTP access.
The request host is fixed, redirects and automatic retries are not used, and
provider responses are never exposed to callers.
"""
from __future__ import annotations

import http.client
import json
import re
from collections.abc import Mapping
from typing import Any


_API_HOST = "api.mail.hostinger.com"
_API_PREFIX = "/api/v1/mailboxes/"
_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 4096
_EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z")
_RESOURCE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOKEN_RE = re.compile(r"[\x21-\x7E]{1,4096}\Z")


class MailDeliveryError(Exception):
    """Sanitized delivery failure; never contains provider data or credentials."""


def _https_send(*, path: str, token: str, payload: dict[str, Any]) -> None:
    """POST one message over HTTPS without following redirects or retrying."""
    connection = http.client.HTTPSConnection(_API_HOST, timeout=_TIMEOUT_SECONDS)
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        if response.status != 204:
            raise MailDeliveryError("Email delivery unavailable")
        # Hostinger's documented success response is empty. Bound the read so
        # a broken or unexpected peer cannot make us buffer an arbitrary body.
        if response.read(_MAX_RESPONSE_BYTES + 1):
            raise MailDeliveryError("Email delivery unavailable")
    except MailDeliveryError:
        raise
    except Exception:
        # Do not leak socket details, request headers, or provider response text.
        raise MailDeliveryError("Email delivery unavailable") from None
    finally:
        try:
            connection.close()
        except Exception:
            raise MailDeliveryError("Email delivery unavailable") from None


class HostingerMailSender:
    """Send six-digit SeatPal account codes through a Hostinger mailbox."""

    def __init__(self, token: str | None = None, mailbox_resource_id: str | None = None):
        self._token = token.strip() if isinstance(token, str) else ""
        self._mailbox_resource_id = (
            mailbox_resource_id.strip() if isinstance(mailbox_resource_id, str) else ""
        )
        self.ready = bool(
            _TOKEN_RE.fullmatch(self._token)
            and _RESOURCE_ID_RE.fullmatch(self._mailbox_resource_id)
        )

    def send_code(self, address: str, code: str, purpose: str) -> None:
        """Send an enrollment or account-recovery code, or fail closed."""
        purpose_copy = {
            "backup_email": "confirm your backup email address",
            "account_recovery": "recover access to your SeatPal account",
        }
        if not self.ready:
            raise MailDeliveryError("Email delivery unavailable")
        if (not isinstance(address, str) or len(address) > 254
                or not _EMAIL_RE.fullmatch(address)
                or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code)
                or not isinstance(purpose, str) or purpose not in purpose_copy):
            raise MailDeliveryError("Email delivery unavailable")

        subject = "Your SeatPal verification code"
        text = (
            f"Use {code} to {purpose_copy[purpose]}.\n\n"
            "This code expires in 5 minutes. Only enter it in SeatPal. "
            "Do not share it with anyone."
        )
        payload = {
            "to": [address],
            "subject": subject,
            "text": text,
            "displayName": "SeatPal",
        }
        path = f"{_API_PREFIX}{self._mailbox_resource_id}/send"
        try:
            _https_send(path=path, token=self._token, payload=payload)
        except Exception:
            # Keep the application boundary uniform even if the transport is
            # replaced in tests or a future implementation raises unexpectedly.
            raise MailDeliveryError("Email delivery unavailable") from None


def email_provider_from_config(config: Mapping[str, Any] | None) -> HostingerMailSender:
    """Build an adapter from application config; missing settings stay unready."""
    if not isinstance(config, Mapping):
        return HostingerMailSender()
    return HostingerMailSender(
        token=config.get("HOSTINGER_MAIL_API_TOKEN"),
        mailbox_resource_id=config.get("HOSTINGER_MAILBOX_RESOURCE_ID"),
    )
