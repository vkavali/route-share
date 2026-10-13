"""Synthetic boundary fixtures, NOT proof of MSG91 live account compatibility."""
import json
import uuid

import pytest

from app.sms_provider import MSG91Provider, SMSProviderUnavailable, _https_post

PHONE = "+919876543210"
CHALLENGE = str(uuid.uuid4())
REQUEST = "synthetic-request-12345"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJmaXh0dXJlIn0.synthetic"


def fixture_provider(responses=None, **kwargs):
    calls = []
    pending = list(responses if responses is not None else [
        {"type": "success", "message": REQUEST},
        {"type": "success", "message": TOKEN},
        {"type": "success", "message": "verified"},
    ])
    def transport(path, body):
        calls.append((path, body))
        result = pending.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    config = dict(widget_id="widget-fixture", token_auth="widget-token-fixture",
                  auth_key="authkey-fixture", handle_secret=b"x" * 32,
                  contract_verified=True, transport=transport, clock=lambda: 1000)
    config.update(kwargs)
    return MSG91Provider(**config), calls


def send(provider):
    return provider.send(PHONE, challenge_id=CHALLENGE, expires_in=300)


def test_request_bound_server_verification_and_restart():
    provider, calls = fixture_provider()
    handle = send(provider)
    assert len(handle) <= 512
    assert provider.verify(handle, "123456") is True
    assert calls == [
        ("sendOtpMobile", {"widgetId": "widget-fixture", "tokenAuth": "widget-token-fixture", "identifier": PHONE[1:]}),
        ("verifyOtp", {"widgetId": "widget-fixture", "tokenAuth": "widget-token-fixture", "reqId": REQUEST, "otp": "123456"}),
        ("verifyAccessToken", {"authkey": "authkey-fixture", "access-token": TOKEN}),
    ]
    restarted, _ = fixture_provider([{"type": "success", "message": TOKEN}, {"type": "success"}])
    assert restarted.verify(handle, "123456") is True


@pytest.mark.parametrize("change", [dict(), {"contract_verified": "true"}, {"contract_verified": False},
    {"widget_id": None}, {"token_auth": " "}, {"auth_key": None}, {"handle_secret": b"short"}])
def test_disabled_without_every_credential_and_explicit_gate(change):
    if not change:
        provider, calls = MSG91Provider(), []
    else:
        provider, calls = fixture_provider(**change)
    assert provider.ready is False
    assert provider.verify("anything", "123456") is False
    with pytest.raises(SMSProviderUnavailable):
        send(provider)
    assert not calls


@pytest.mark.parametrize("response", [None, [], {}, {"type": "error", "message": "invalid"},
    {"type": True, "message": REQUEST}, {"type": "success", "request_id": REQUEST},
    {"type": "success", "message": 123}, {"type": "success", "message": "OTP sent"},
    {"type": "success", "message": REQUEST, "access-token": TOKEN},
    {"type": "success", "message": REQUEST, "invisibleVerified": True}])
def test_send_unknown_or_invisible_contract_fails_closed(response):
    provider, _ = fixture_provider([response])
    with pytest.raises(SMSProviderUnavailable):
        send(provider)


@pytest.mark.parametrize("response", [{}, {"type": "error", "message": "expired"},
    {"type": "error", "message": "invalid"}, {"type": "success", "access-token": TOKEN},
    {"type": "success", "message": "OTP verified success"}, {"type": True, "message": TOKEN}])
def test_otp_semantic_failure_or_unknown_shape_cannot_authenticate(response):
    provider, calls = fixture_provider([{"type": "success", "message": REQUEST}, response])
    assert provider.verify(send(provider), "123456") is False
    assert len(calls) == 2


@pytest.mark.parametrize("response", [{}, {"type": "error"}, {"type": True}, {"success": True}])
def test_valid_looking_jwt_requires_positive_server_verification(response):
    provider, calls = fixture_provider([{"type": "success", "message": REQUEST},
                                       {"type": "success", "message": TOKEN}, response])
    assert provider.verify(send(provider), "123456") is False
    assert calls[-1][0] == "verifyAccessToken"


def test_expiry_tampering_cross_account_key_and_invalid_code_do_not_call_provider():
    now = [1000]
    provider, calls = fixture_provider(clock=lambda: now[0])
    handle = send(provider)
    assert provider.verify(handle + "x", "123456") is False
    assert provider.verify(handle, "12345") is False
    assert provider.verify(handle, "１２３４５６") is False
    other, other_calls = fixture_provider(widget_id="another-widget")
    assert other.verify(handle, "123456") is False
    now[0] = 1300
    assert provider.verify(handle, "123456") is False
    assert len(calls) == 1 and not other_calls


def test_expiry_during_remote_verification_fails_closed():
    now = [1000]
    provider, _ = fixture_provider(clock=lambda: now[0])
    handle = send(provider)
    def slow(path, body):
        now[0] = 1300
        return {"type": "success", "message": TOKEN}
    provider._post = slow
    assert provider.verify(handle, "123456") is False


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_timeout_is_sanitized_without_retry(stage):
    responses = [{"type": "success", "message": REQUEST}, {"type": "success", "message": TOKEN}, {"type": "success"}]
    responses[stage] = TimeoutError("secret provider body must not escape")
    provider, calls = fixture_provider(responses)
    with pytest.raises(SMSProviderUnavailable, match="^SMS provider unavailable$"):
        handle = send(provider)
        provider.verify(handle, "123456")
    assert len(calls) == stage + 1


@pytest.mark.parametrize("phone,challenge,ttl", [("9876543210", CHALLENGE, 300),
    (PHONE, "not-a-uuid", 300), (PHONE, CHALLENGE, 301), (PHONE, CHALLENGE, True)])
def test_invalid_challenge_never_sends(phone, challenge, ttl):
    provider, calls = fixture_provider()
    with pytest.raises(ValueError):
        provider.send(phone, challenge_id=challenge, expires_in=ttl)
    assert not calls


@pytest.mark.parametrize("status,body,ok", [(200, b'{"type":"success"}', True),
    (302, b'{"type":"success"}', False), (429, b'{}', False), (200, b'not json', False),
    (200, b'[]', False), (200, b'x' * 16385, False)])
def test_https_transport_fixed_post_body_bounded_no_redirect(monkeypatch, status, body, ok):
    events = []
    class Response:
        def __init__(self): self.status = status
        def read(self, n):
            assert n == 16385
            return body
    class Connection:
        def __init__(self, host, timeout): events.append((host, timeout))
        def request(self, method, path, body, headers):
            events.append((method, path, json.loads(body), headers))
        def getresponse(self): return Response()
        def close(self): events.append("closed")
    monkeypatch.setattr("app.sms_provider.http.client.HTTPSConnection", Connection)
    if ok:
        assert _https_post("verifyAccessToken", {"authkey": "fixture"}) == {"type": "success"}
    else:
        with pytest.raises(SMSProviderUnavailable):
            _https_post("verifyAccessToken", {"authkey": "fixture"})
    assert events[0] == ("control.msg91.com", 10)
    assert events[1][0:2] == ("POST", "/api/v5/widget/verifyAccessToken")
    assert events[1][2] == {"authkey": "fixture"}
    assert events[-1] == "closed"


def test_rewriting_any_bound_handle_field_fails_without_network():
    from app.sms_provider import _decode, _encode
    provider, calls = fixture_provider()
    handle = send(provider)
    body, signature = handle.split(".")
    original = json.loads(_decode(body))
    replacements = ["+919876543211", "different-request-123", str(uuid.uuid4()), 1001, 299]
    for index, replacement in enumerate(replacements):
        changed = original.copy()
        changed[index] = replacement
        tampered = _encode(json.dumps(changed, separators=(",", ":")).encode()) + "." + signature
        assert provider.verify(tampered, "123456") is False
    assert len(calls) == 1


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("malformed", [None, [], "success", True])
def test_malformed_remote_verification_never_authenticates(stage, malformed):
    responses = [{"type": "success", "message": REQUEST}, {"type": "success", "message": TOKEN}, {"type": "success"}]
    responses[stage] = malformed
    provider, calls = fixture_provider(responses)
    with pytest.raises(SMSProviderUnavailable):
        provider.verify(send(provider), "123456")
    assert len(calls) == stage + 1
