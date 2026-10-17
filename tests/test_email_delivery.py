"""Synthetic boundary tests; these never send real email."""
import json

import pytest

from app.email_delivery import (
    HostingerMailSender,
    MailDeliveryError,
    _https_send,
    email_provider_from_config,
)


TOKEN = "fixture-mail-token"
MAILBOX = "AC2578e0cc63a36c144e799160ed07"
ADDRESS = "person@example.com"


class Response:
    def __init__(self, status=204, body=b""):
        self.status = status
        self.body = body
        self.read_sizes = []

    def read(self, size):
        self.read_sizes.append(size)
        return self.body


class Connection:
    def __init__(self, host, timeout, *, status=204, response_body=b"", request_error=None):
        self.host = host
        self.timeout = timeout
        self.status = status
        self.response_body = response_body
        self.request_error = request_error
        self.events = []
        self.response = Response(status, response_body)

    def request(self, method, path, body, headers):
        self.events.append((method, path, json.loads(body), headers))
        if self.request_error:
            raise self.request_error

    def getresponse(self):
        self.events.append("getresponse")
        return self.response

    def close(self):
        self.events.append("closed")


def ready_sender():
    return HostingerMailSender(TOKEN, MAILBOX)


def test_sender_uses_fixed_https_request_and_documented_empty_204(monkeypatch):
    connections = []

    def make_connection(host, timeout):
        connection = Connection(host, timeout)
        connections.append(connection)
        return connection

    monkeypatch.setattr("app.email_delivery.http.client.HTTPSConnection", make_connection)
    sender = ready_sender()
    assert sender.ready is True
    assert sender.send_code(ADDRESS, "123456", "backup_email") is None

    connection = connections[0]
    assert (connection.host, connection.timeout) == ("api.mail.hostinger.com", 10)
    assert connection.events == [
        (
            "POST",
            f"/api/v1/mailboxes/{MAILBOX}/send",
            {
                "to": [ADDRESS],
                "subject": "Your SeatPal verification code",
                "text": (
                    "Use 123456 to confirm your backup email address.\n\n"
                    "This code expires in 5 minutes. Only enter it in SeatPal. "
                    "Do not share it with anyone."
                ),
                "displayName": "SeatPal",
            },
            {
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        ),
        "getresponse",
        "closed",
    ]
    assert connection.response.read_sizes == [4097]


@pytest.mark.parametrize("purpose,phrase", [
    ("backup_email", "confirm your backup email address"),
    ("account_recovery", "recover access to your SeatPal account"),
])
def test_supported_purpose_copy_is_action_specific(monkeypatch, purpose, phrase):
    calls = []
    monkeypatch.setattr("app.email_delivery._https_send", lambda **kwargs: calls.append(kwargs))
    ready_sender().send_code(ADDRESS, "654321", purpose)
    payload = calls[0]["payload"]
    assert phrase in payload["text"]
    assert "654321" in payload["text"]
    assert "5 minutes" in payload["text"]


@pytest.mark.parametrize("status,body", [
    (200, b"{}"),
    (202, b""),
    (302, b"redirect body"),
    (429, b"provider body with secret details"),
    (500, b"provider body with secret details"),
    (204, b"unexpected response body"),
])
def test_non_documented_success_is_generic_and_not_retried(monkeypatch, status, body):
    connections = []

    def make_connection(host, timeout):
        connection = Connection(host, timeout, status=status, response_body=body)
        connections.append(connection)
        return connection

    monkeypatch.setattr("app.email_delivery.http.client.HTTPSConnection", make_connection)
    with pytest.raises(MailDeliveryError, match="^Email delivery unavailable$") as error:
        ready_sender().send_code(ADDRESS, "123456", "account_recovery")
    assert TOKEN not in str(error.value)
    assert len(connections) == 1
    assert connections[0].events[-1] == "closed"


def test_network_failure_is_sanitized_and_not_retried(monkeypatch):
    connections = []

    def make_connection(host, timeout):
        connection = Connection(host, timeout, request_error=TimeoutError("secret token and provider body"))
        connections.append(connection)
        return connection

    monkeypatch.setattr("app.email_delivery.http.client.HTTPSConnection", make_connection)
    with pytest.raises(MailDeliveryError, match="^Email delivery unavailable$") as error:
        ready_sender().send_code(ADDRESS, "123456", "account_recovery")
    assert "secret" not in str(error.value)
    assert len(connections) == 1
    assert connections[0].events[-1] == "closed"


@pytest.mark.parametrize("config", [
    None,
    {},
    {"HOSTINGER_MAIL_API_TOKEN": TOKEN},
    {"HOSTINGER_MAILBOX_RESOURCE_ID": MAILBOX},
    {"HOSTINGER_MAIL_API_TOKEN": "bad\r\nheader", "HOSTINGER_MAILBOX_RESOURCE_ID": MAILBOX},
    {"HOSTINGER_MAIL_API_TOKEN": "bad\u0000token", "HOSTINGER_MAILBOX_RESOURCE_ID": MAILBOX},
    {"HOSTINGER_MAIL_API_TOKEN": "токен", "HOSTINGER_MAILBOX_RESOURCE_ID": MAILBOX},
    {"HOSTINGER_MAIL_API_TOKEN": TOKEN, "HOSTINGER_MAILBOX_RESOURCE_ID": "bad/segment"},
])
def test_missing_or_invalid_config_returns_unready_sender(config):
    sender = email_provider_from_config(config)
    assert isinstance(sender, HostingerMailSender)
    assert sender.ready is False
    with pytest.raises(MailDeliveryError, match="^Email delivery unavailable$"):
        sender.send_code(ADDRESS, "123456", "account_recovery")


def test_valid_config_creates_ready_sender():
    sender = email_provider_from_config({
        "HOSTINGER_MAIL_API_TOKEN": TOKEN,
        "HOSTINGER_MAILBOX_RESOURCE_ID": MAILBOX,
    })
    assert sender.ready is True


@pytest.mark.parametrize("address,code,purpose", [
    ("bad address", "123456", "backup_email"),
    ("a@example.com\r\nBcc: victim@example.com", "123456", "backup_email"),
    ("x" * 250 + "@example.com", "123456", "backup_email"),
    (ADDRESS, "１２３４５６", "backup_email"),
    (ADDRESS, "12345", "backup_email"),
    (ADDRESS, "123456\r\n", "backup_email"),
    (ADDRESS, "123456", "unknown"),
    (ADDRESS, "123456", []),
])
def test_invalid_inputs_fail_before_transport(monkeypatch, address, code, purpose):
    calls = []
    monkeypatch.setattr("app.email_delivery._https_send", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(MailDeliveryError, match="^Email delivery unavailable$"):
        ready_sender().send_code(address, code, purpose)
    assert not calls


def test_email_validation_rejects_non_string_values_before_transport(monkeypatch):
    calls = []
    monkeypatch.setattr("app.email_delivery._https_send", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(MailDeliveryError):
        ready_sender().send_code([], "123456", "account_recovery")
    assert not calls
