"""Phone account behavior with an injected provider; never sends real SMS."""
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from werkzeug.security import generate_password_hash

from app.auth import is_active_account
from app.mobile_auth import MobileAuthenticator, MobileAuthError
from app.phone_auth import PhoneAuthError, PhoneAuthService
from app.store import Store


class Provider:
    ready = True

    def __init__(self):
        self.sends = []
        self.verifications = []
        self.fail_send = False
        self.fail_verify = False
        self.result = True
        self.entered = None
        self.release = None

    def send(self, phone, *, challenge_id, expires_in):
        self.sends.append((phone, challenge_id, expires_in))
        if self.fail_send:
            raise RuntimeError("Provider private detail must not escape")
        return "provider-" + challenge_id

    def verify(self, handle, code):
        self.verifications.append((handle, code))
        if self.entered:
            self.entered.set()
            assert self.release.wait(3)
        if self.fail_verify:
            raise RuntimeError("Provider private detail must not escape")
        return self.result


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "phone.sqlite")
    provider = Provider()
    now = [1800000000.0]
    service = PhoneAuthService(store, provider=provider, hmac_key="s" * 48,
                               global_daily_limit=100, clock=lambda: now[0])
    return store, provider, now, service


def start(service, phone="9876543210", flow=None, request_id=None, ip="127.0.0.1"):
    flow = flow or secrets.token_urlsafe(32)
    payload = {"phone": phone, "flow_token": flow, "request_id": request_id or str(uuid.uuid4())}
    return service.start(payload, ip), payload


def verify(service, challenge, payload, **kwargs):
    body = {"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"],
            "code": "194628", "consent": {"terms_version": service.terms_version,
            "privacy_version": service.privacy_version, "adult_attested": True,
            "terms_accepted": True, "privacy_accepted": True}}
    body.update(kwargs.pop("body", {}))
    return service.verify(body, "127.0.0.1", **kwargs)


def error(code, call):
    with pytest.raises(PhoneAuthError) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def test_disabled_until_real_configuration_and_explicit_cap(tmp_path):
    store = Store(tmp_path / "x.db")
    for config in ({}, {"provider": Provider()}, {"provider": Provider(), "hmac_key": "s" * 48},
                   {"provider": Provider(), "hmac_key": "s" * 48, "global_daily_limit": True}):
        service = PhoneAuthService(store, **config)
        assert service.capabilities()["enabled"] is False
        assert error("phone_auth_unavailable", lambda: start(service)).status == 503


def test_new_account_native_profile_persistence_and_no_secrets(setup):
    store, provider, now, service = setup
    challenge, payload = start(service)
    same = service.start(payload, "127.0.0.1")
    assert same == challenge and len(provider.sends) == 1
    result = verify(service, challenge, payload, native=True)
    assert result["onboarding_required"] is True
    user_id = result["user"]["id"]
    with store.read() as tx:
        user = tx.get("users", user_id)
        serialized = json.dumps(tx.list("phone_challenges") + tx.list("mobile_sessions"))
        assert "194628" not in serialized and payload["flow_token"] not in serialized and result["token"] not in serialized
        assert user["role"] == "member" and user["development"] is False
        assert user["driver_approved"] is False and user["staff_capabilities"] == []
        assert user["phone_verified"] is True and user["verification"]["identity"] == "not_checked"
        assert user["phone_consent"]["adult_attested"] is True
    assert "auth_phone" not in result["user"] and "phone_consent" not in result["user"]
    completed = service.profile(user_id, {"name": "  తెలుగు ప్రయాణికుడు  "})
    assert completed["onboarding_required"] is False
    assert completed["user"]["name"] == "తెలుగు ప్రయాణికుడు"
    assert error("invalid_phone_flow", lambda: verify(service, challenge, payload, native=True)).status == 409
    now[0] += 61
    recreated = PhoneAuthService(Store(store.path), provider=provider, hmac_key="s" * 48,
                                global_daily_limit=100, clock=lambda: now[0])
    challenge, payload = start(recreated)
    again = verify(recreated, challenge, payload)
    assert again["user"]["id"] == user_id and again["onboarding_required"] is False
    with store.read() as tx:
        assert len(tx.list("users")) == len(tx.list("phone_identities")) == 1
    with pytest.raises(ValueError, match="identity key"):
        PhoneAuthService(store, provider=provider, hmac_key="changed" * 8, global_daily_limit=100)


@pytest.mark.parametrize("phone", ["123", "+19876543210", "5123456789", True, None, [9876543210], "+919876543210junk"])
def test_invalid_phone_never_sends(setup, phone):
    _, provider, _, service = setup
    error("invalid_phone", lambda: start(service, phone))
    assert not provider.sends


def test_flow_binding_expiry_and_consent_fail_closed(setup):
    store, provider, now, service = setup
    challenge, payload = start(service)
    error("invalid_phone_flow", lambda: verify(service, challenge, payload, body={"flow_token": secrets.token_urlsafe(32)}))
    error("consent_required", lambda: verify(service, challenge, payload, body={"consent": {"adult_attested": "true"}}))
    assert not provider.verifications
    now[0] += 301
    error("phone_auth_expired", lambda: verify(service, challenge, payload))
    with store.read() as tx:
        assert not tx.list("users")


def test_guesses_persist_and_provider_failure_is_not_success(setup):
    store, provider, now, service = setup
    challenge, payload = start(service)
    provider.fail_verify = True
    error("phone_auth_unavailable", lambda: verify(service, challenge, payload))
    provider.fail_verify, provider.result = False, False
    for _ in range(4):
        error("phone_auth_invalid_code", lambda: verify(service, challenge, payload))
    provider.result = True
    recreated = PhoneAuthService(store, provider=provider, hmac_key="s" * 48, global_daily_limit=100, clock=lambda: now[0])
    error("phone_auth_rate_limited", lambda: verify(recreated, challenge, payload))
    assert len(provider.verifications) == 5
    with store.read() as tx:
        assert not tx.list("users")


def test_resend_invalidates_old_challenge_and_is_idempotent(setup):
    _, provider, now, service = setup
    first, payload = start(service)
    resend = {"challenge_id": first["challenge_id"], "flow_token": payload["flow_token"], "request_id": str(uuid.uuid4())}
    error("phone_auth_rate_limited", lambda: service.resend(resend, "127.0.0.1"))
    now[0] += 61
    second = service.resend(resend, "127.0.0.1")
    assert second["challenge_id"] != first["challenge_id"]
    assert service.resend(resend, "127.0.0.1") == second
    error("invalid_phone_flow", lambda: verify(service, first, payload))
    assert verify(service, second, payload)["user"]["role"] == "member"
    assert len(provider.sends) == 2


def test_failed_send_debits_global_cap_and_restart_does_not_reset(setup):
    store, provider, now, _ = setup
    service = PhoneAuthService(store, provider=provider, hmac_key="s" * 48, global_daily_limit=1, clock=lambda: now[0])
    provider.fail_send = True
    failure = error("phone_auth_unavailable", lambda: start(service))
    assert "private detail" not in str(failure)
    recreated = PhoneAuthService(Store(store.path), provider=provider, hmac_key="s" * 48, global_daily_limit=1, clock=lambda: now[0])
    error("phone_auth_rate_limited", lambda: start(recreated, "8765432109", ip="127.0.0.2"))
    assert len(provider.sends) == 1
    now[0] = (int(now[0] // 86400) + 1) * 86400
    provider.fail_send = False
    start(recreated, "8765432109")
    assert len(provider.sends) == 2


def test_atomic_last_message_slot_across_instances(setup):
    store, provider, now, _ = setup
    services = [PhoneAuthService(Store(store.path), provider=provider, hmac_key="s" * 48,
                global_daily_limit=1, clock=lambda: now[0]) for _ in range(2)]
    def send(index):
        try:
            return start(services[index], ("9876543210", "8765432109")[index])[0]
        except PhoneAuthError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sum(isinstance(item, dict) for item in responses) == 1
    assert responses.count("phone_auth_rate_limited") == 1 and len(provider.sends) == 1


def test_only_one_provider_verification_and_resend_race_cannot_authenticate(setup):
    store, provider, now, service = setup
    challenge, payload = start(service)
    provider.entered, provider.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(verify, service, challenge, payload)
        assert provider.entered.wait(2)
        error("phone_auth_busy", lambda: verify(service, challenge, payload))
        # No SQLite transaction is held across provider I/O; another send replaces
        # the old generation. Its late positive result cannot create an account.
        now[0] += 61
        start(service, flow=payload["flow_token"])
        provider.release.set()
        with pytest.raises(PhoneAuthError):
            future.result()
    assert len(provider.verifications) == 1
    with store.read() as tx:
        assert not tx.list("users")


@pytest.mark.parametrize("restriction", [{"account_status": "suspended"}, {"disabled": True}, {"suspended": True}])
def test_restricted_account_cannot_reregister_or_use_bearer(setup, restriction):
    store, _, now, service = setup
    challenge, payload = start(service)
    result = verify(service, challenge, payload, native=True)
    with store.transaction() as tx:
        user = tx.get("users", result["user"]["id"])
        user.update(restriction)
        tx.put("users", user["id"], user)
    assert service.mobile_auth.authenticate(result["token"]) is None
    now[0] += 61
    challenge, payload = start(service)
    error("account_unavailable", lambda: verify(service, challenge, payload))
    with store.read() as tx:
        assert len(tx.list("users")) == 1 and len(tx.list("mobile_sessions")) == 1


def test_demo_phone_collision_never_claims_fixture_and_password_flag_preserves_admin(setup):
    store, _, _, service = setup
    with store.transaction() as tx:
        for identity, role in (("driver", "member"), ("admin", "staff")):
            tx.put("users", identity, {"id": identity, "name": identity, "role": role,
                   "development": True, "phone": "+919876543210", "password_hash": generate_password_hash("fixture")})
    challenge, payload = start(service)
    result = verify(service, challenge, payload)
    assert result["user"]["id"] not in {"driver", "admin"}
    auth = MobileAuthenticator(store, demo_password_enabled=False)
    assert auth.verify_credentials("driver", "fixture", "127.0.0.1") is None
    assert auth.verify_credentials("admin", "fixture", "127.0.0.1")["id"] == "admin"
    assert auth.verify_credentials(result["user"]["id"], "anything", "127.0.0.1") is None


def test_per_phone_and_ip_limits_and_no_plaintext_ip_in_buckets(setup):
    store, provider, now, _ = setup
    service = PhoneAuthService(store, provider=provider, hmac_key="s" * 48, global_daily_limit=100,
                              limits={"phone_hour": 1, "ip_ten_minutes": 1}, clock=lambda: now[0])
    start(service)
    now[0] += 61
    error("phone_auth_rate_limited", lambda: start(service, ip="192.0.2.99"))
    error("phone_auth_rate_limited", lambda: start(service, "8765432109"))
    with store.read() as tx:
        assert "127.0.0.1" not in json.dumps(tx.list("phone_auth_limits"))
    assert len(provider.sends) == 1


def test_current_consent_and_name_required_and_no_other_user_mutation(setup):
    store, _, _, service = setup
    challenge, payload = start(service)
    user_id = verify(service, challenge, payload)["user"]["id"]
    error("invalid_name", lambda: service.profile(user_id, {"name": "\n"}))
    service.terms_version = "next"
    error("consent_required", lambda: service.profile(user_id, {"name": "Example"}))
    with store.read() as tx:
        user = tx.get("users", user_id)
        assert service.requires_onboarding(user)
        assert user["name"] == ""


def test_status_guard_handles_malformed_restrictions():
    assert is_active_account({"id": "legacy"})
    assert not is_active_account({"status": []})
    assert not is_active_account({"account_status": None})


def test_reserved_fixture_identity_is_never_converted_to_member(setup):
    store, provider, _, service = setup
    with store.transaction() as tx:
        tx.put("users", "admin", {"id": "admin", "name": "Admin", "role": "staff", "development": True})
        key = service._digest("phone", "+919876543210")
        tx.put("phone_identities", key, {"id": key, "user_id": "admin", "status": "active"})
    challenge, payload = start(service)
    error("account_unavailable", lambda: verify(service, challenge, payload))
    with store.read() as tx:
        assert tx.get("users", "admin")["role"] == "staff"
        assert len(tx.list("users")) == 1 and not tx.list("mobile_sessions")
    assert len(provider.verifications) == 1


def test_provider_non_boolean_verification_never_authenticates(setup):
    store, provider, _, service = setup
    challenge, payload = start(service)
    provider.result = {"success": True}
    error("phone_auth_unavailable", lambda: verify(service, challenge, payload))
    with store.read() as tx:
        assert not tx.list("users") and not tx.list("mobile_sessions")


def test_transient_challenges_are_pruned_without_erasing_reserved_identity(setup):
    store, _, now, service = setup
    challenge, payload = start(service)
    user_id = verify(service, challenge, payload)["user"]["id"]
    now[0] += 86401
    new, _ = start(service, "8765432109")
    with store.read() as tx:
        assert [row["id"] for row in tx.list("phone_challenges")] == [new["challenge_id"]]
        assert len(tx.list("phone_send_requests")) == 1
        assert tx.list("phone_identities")[0]["user_id"] == user_id


@pytest.mark.parametrize("field", ["terms_accepted", "privacy_accepted", "adult_attested"])
@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_consent_requires_exact_explicit_boolean_acceptance(setup, field, value):
    _, provider, _, service = setup
    challenge, payload = start(service)
    consent = {"terms_version": service.terms_version, "privacy_version": service.privacy_version,
               "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}
    consent[field] = value
    error("consent_required", lambda: verify(service, challenge, payload, body={"consent": consent}))
    assert not provider.verifications


def test_domain_rechecks_current_account_and_mutation_transaction(setup):
    from app.domain import DomainError, Service
    store, _, _, _ = setup
    actor = {"id": "member-example", "role": "member"}
    with store.transaction() as tx:
        tx.put("users", actor["id"], {**actor, "account_status": "suspended"})
    domain = Service(store, None)
    with pytest.raises(DomainError) as caught:
        domain.dispatch("state", actor, {})
    assert caught.value.status == 401
    with store.transaction() as tx:
        with pytest.raises(DomainError) as caught:
            domain._current_actor(tx, actor, "search")
        assert caught.value.status == 401
