"""Development-only external provider interfaces and configuration."""

from typing import Protocol

PUBLIC_REGISTRATION_ENABLED = False
PAID_RIDES_ENABLED = False
IDENTITY_PROVIDER_MODE = "mock"
PAYMENT_PROVIDER_MODE = "sandbox"


class IdentityProvider(Protocol):
    def status(self, user_id: str) -> dict[str, str]: ...


class PaymentProvider(Protocol):
    def status(self) -> dict[str, bool | str]: ...


class MockIdentityProvider:
    def status(self, user_id: str) -> dict[str, str]:
        del user_id
        return {"mode": IDENTITY_PROVIDER_MODE, "status": "not_checked"}


class SandboxPaymentProvider:
    def status(self) -> dict[str, bool | str]:
        return {"mode": PAYMENT_PROVIDER_MODE, "enabled": False}


def public_flags() -> dict[str, bool | str]:
    return {
        "public_registration_enabled": PUBLIC_REGISTRATION_ENABLED,
        "paid_rides_enabled": PAID_RIDES_ENABLED,
        "identity_provider_mode": IDENTITY_PROVIDER_MODE,
        "payment_provider_mode": PAYMENT_PROVIDER_MODE,
    }
