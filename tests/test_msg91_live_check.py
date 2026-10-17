"""Safety tests for the optional MSG91 live adapter diagnostic; no provider calls."""

import io
import getpass
import uuid
import warnings

import pytest

from scripts.verify_msg91_contract import main, run_diagnostic


VALID_ENV = {
    "MSG91_WIDGET_ID": "widget-fixture",
    "MSG91_TOKEN_AUTH": "private-token-auth-fixture",
    "MSG91_AUTH_KEY": "private-auth-key-fixture",
    "PHONE_AUTH_HMAC_KEY": "h" * 32,
}


class FakeProvider:
    def __init__(self, *, widget_id, token_auth, auth_key, handle_secret, contract_verified):
        self.constructor = (widget_id, token_auth, auth_key, handle_secret, contract_verified)
        self.send_calls = []
        self.verify_calls = []

    def send(self, phone, *, challenge_id, expires_in):
        self.send_calls.append((phone, challenge_id, expires_in))
        return "PRIVATE_PROVIDER_HANDLE"

    def verify(self, handle, code):
        self.verify_calls.append((handle, code))
        return True


def test_default_only_reports_names_and_booleans_and_never_constructs_provider():
    out = io.StringIO()
    inputs = []

    def forbidden_factory(**kwargs):
        pytest.fail("default diagnostic must not construct or call a provider")

    result = run_diagnostic(
        environ=VALID_ENV,
        provider_factory=forbidden_factory,
        hidden_input=lambda prompt: inputs.append(prompt),
        tty_check=lambda: pytest.fail("default diagnostic must not require a TTY"),
        out=out,
    )

    assert result == 0
    assert inputs == []
    output = out.getvalue()
    assert '"MSG91_WIDGET_ID":true' in output
    assert '"MSG91_TOKEN_AUTH":true' in output
    assert '"MSG91_AUTH_KEY":true' in output
    assert '"PHONE_AUTH_HMAC_KEY":true' in output
    for secret in VALID_ENV.values():
        assert secret not in output


def test_non_tty_live_mode_refuses_before_private_input_or_provider():
    out = io.StringIO()
    requested = []

    def forbidden_factory(**kwargs):
        pytest.fail("must refuse before constructing provider")

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=forbidden_factory,
        hidden_input=lambda prompt: requested.append(prompt),
        tty_check=lambda: False,
        out=out,
    )

    assert result == 2
    assert requested == []
    assert out.getvalue() == '{"ok":false,"stage":"tty"}\n'


def test_missing_live_configuration_refuses_before_tty_or_private_input():
    out = io.StringIO()
    requested = []
    result = run_diagnostic(
        send_test=True,
        environ={"MSG91_WIDGET_ID": "widget-fixture"},
        provider_factory=lambda **kwargs: pytest.fail("must refuse before provider construction"),
        hidden_input=lambda prompt: requested.append(prompt),
        tty_check=lambda: pytest.fail("must refuse before TTY input"),
        out=out,
    )
    assert result == 2
    assert requested == []
    assert '"MSG91_WIDGET_ID":true' in out.getvalue()
    assert '"MSG91_TOKEN_AUTH":false' in out.getvalue()
    assert '"MSG91_AUTH_KEY":false' in out.getvalue()
    assert '"PHONE_AUTH_HMAC_KEY":false' in out.getvalue()


def test_unexpected_command_line_values_are_not_echoed(monkeypatch, capsys):
    sentinel = "PRIVATE_AUTH_KEY_COMMAND_LINE_SENTINEL"
    assert main([sentinel]) == 2
    captured = capsys.readouterr()
    assert captured.out == '{"ok":false,"stage":"arguments"}\n'
    assert sentinel not in captured.out
    assert captured.err == ""


def test_live_flow_calls_adapter_once_per_stage_with_private_values_hidden():
    out = io.StringIO()
    provider = None
    inputs = iter(["+919876543210", "123456"])
    prompts = []

    def factory(**kwargs):
        nonlocal provider
        provider = FakeProvider(**kwargs)
        return provider

    def hidden(prompt):
        prompts.append(prompt)
        return next(inputs)

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=factory,
        hidden_input=hidden,
        tty_check=lambda: True,
        out=out,
    )

    assert result == 0
    assert provider is not None
    assert provider.constructor == (
        VALID_ENV["MSG91_WIDGET_ID"],
        VALID_ENV["MSG91_TOKEN_AUTH"],
        VALID_ENV["MSG91_AUTH_KEY"],
        VALID_ENV["PHONE_AUTH_HMAC_KEY"],
        True,
    )
    assert len(provider.send_calls) == 1
    phone, challenge_id, expires_in = provider.send_calls[0]
    assert phone == "+919876543210"
    assert str(uuid.UUID(challenge_id)) == challenge_id
    assert 1 <= expires_in <= 300
    assert provider.verify_calls == [("PRIVATE_PROVIDER_HANDLE", "123456")]
    assert len(prompts) == 2
    output = out.getvalue()
    for private in [phone, "123456", "PRIVATE_PROVIDER_HANDLE", *VALID_ENV.values()]:
        assert private not in output
    assert output == '{"ok":true,"stage":"verify"}\n'


@pytest.mark.parametrize("phone", ["", "9876543210", "+915123456789", "+919876543210 "])
def test_invalid_phone_stops_before_any_provider_call(phone):
    out = io.StringIO()
    factory_calls = []
    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=lambda **kwargs: factory_calls.append(kwargs),
        hidden_input=lambda prompt: phone,
        tty_check=lambda: True,
        out=out,
    )
    assert result == 2
    assert factory_calls == []
    assert out.getvalue() == '{"ok":false,"stage":"phone_input"}\n'
    if phone:
        assert phone not in out.getvalue()


@pytest.mark.parametrize("code", ["", "12345", "1234567", "１２３４５６"])
def test_invalid_code_never_calls_verify_or_retries(code):
    out = io.StringIO()
    provider = None
    inputs = iter(["+919876543210", code])

    def factory(**kwargs):
        nonlocal provider
        provider = FakeProvider(**kwargs)
        return provider

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=factory,
        hidden_input=lambda prompt: next(inputs),
        tty_check=lambda: True,
        out=out,
    )
    assert result == 2
    assert len(provider.send_calls) == 1
    assert provider.verify_calls == []
    assert out.getvalue() == '{"ok":false,"stage":"otp_input"}\n'
    if code:
        assert code not in out.getvalue()


def test_getpass_warning_refuses_phone_input_without_send_or_warning_leak(capsys):
    sentinel = "PRIVATE_FALLBACK_INPUT_SENTINEL"
    out = io.StringIO()
    factory_calls = []

    def echoed_fallback(prompt):
        warnings.warn(sentinel, getpass.GetPassWarning)
        return "+919876543210"

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=lambda **kwargs: factory_calls.append(kwargs),
        hidden_input=echoed_fallback,
        tty_check=lambda: True,
        out=out,
    )
    captured = capsys.readouterr()
    assert result == 2
    assert factory_calls == []
    assert out.getvalue() == '{"ok":false,"stage":"phone_input"}\n'
    assert sentinel not in captured.out + captured.err


def test_getpass_warning_refuses_otp_input_without_verify_or_warning_leak(capsys):
    sentinel = "PRIVATE_OTP_FALLBACK_SENTINEL"
    out = io.StringIO()
    provider = None
    phone_reads = 0

    def phone_then_echoed_fallback(prompt):
        nonlocal phone_reads
        phone_reads += 1
        if phone_reads == 1:
            return "+919876543210"
        warnings.warn(sentinel, getpass.GetPassWarning)
        return "123456"

    def factory(**kwargs):
        nonlocal provider
        provider = FakeProvider(**kwargs)
        return provider

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=factory,
        hidden_input=phone_then_echoed_fallback,
        tty_check=lambda: True,
        out=out,
    )
    captured = capsys.readouterr()
    assert result == 2
    assert len(provider.send_calls) == 1
    assert provider.verify_calls == []
    assert out.getvalue() == '{"ok":false,"stage":"otp_input"}\n'
    assert sentinel not in captured.out + captured.err


@pytest.mark.parametrize("stage", ["send", "verify", "send_interrupt", "verify_interrupt"])
def test_exception_payloads_are_never_printed(stage, capsys):
    sentinel = "PRIVATE_PHONE_OTP_TOKEN_PROVIDER_RESPONSE"
    out = io.StringIO()
    provider = None

    class ExplodingProvider(FakeProvider):
        def send(self, phone, *, challenge_id, expires_in):
            if stage in {"send", "send_interrupt"}:
                raise KeyboardInterrupt(sentinel) if stage == "send_interrupt" else RuntimeError(sentinel)
            return super().send(phone, challenge_id=challenge_id, expires_in=expires_in)

        def verify(self, handle, code):
            if stage in {"verify", "verify_interrupt"}:
                raise KeyboardInterrupt(sentinel) if stage == "verify_interrupt" else RuntimeError(sentinel)
            return super().verify(handle, code)

    def factory(**kwargs):
        nonlocal provider
        provider = ExplodingProvider(**kwargs)
        return provider

    result = run_diagnostic(
        send_test=True,
        environ=VALID_ENV,
        provider_factory=factory,
        hidden_input=lambda prompt: "+919876543210" if "phone" in prompt else "123456",
        tty_check=lambda: True,
        out=out,
    )
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert sentinel not in out.getvalue()
    assert "+919876543210" not in out.getvalue()
    assert "123456" not in out.getvalue()
    assert "PRIVATE_PROVIDER_HANDLE" not in out.getvalue()
    assert out.getvalue().startswith('{"ok":false,"stage":"')


def test_invalid_configuration_reports_only_names_and_booleans():
    env = {**VALID_ENV, "MSG91_AUTH_KEY": "" , "PHONE_AUTH_HMAC_KEY": "short"}
    out = io.StringIO()
    result = run_diagnostic(environ=env, out=out)
    assert result == 1
    assert '"MSG91_AUTH_KEY":false' in out.getvalue()
    assert '"PHONE_AUTH_HMAC_KEY":false' in out.getvalue()
    assert "short" not in out.getvalue()
