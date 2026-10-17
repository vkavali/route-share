"""Real SQLite security boundaries, fake transports; no live email/SMS claims."""
import base64
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from app.backup_email import BackupEmailService
from app.phone_auth import PhoneAuthError
from app.auth import issue_web_session_in, session_binding_matches_in
from test_account_lifecycle import ctx, action_proof, fails


class Mail:
    ready = True

    def __init__(self):
        self.sent = []
        self.entered = self.release = None
        self.fail = False

    def send_code(self, address, code, purpose):
        self.sent.append((address, code, purpose))
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail:
            raise RuntimeError("PRIVATE provider detail")


@pytest.fixture
def email_ctx(ctx):
    mail = Mail()
    service = BackupEmailService(ctx[0], ctx[4], provider=mail, encryption_key=Fernet.generate_key(), daily_limit=100, clock=lambda: ctx[2][0])
    ctx[4].backup_email = service
    return service, mail


def start_enroll(ctx, email_ctx, address="private@example.com"):
    token = action_proof(ctx, "backup_email")
    body = {"email": address, "action_token": token, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    result = email_ctx[0].start_enrollment(ctx[5], body, ctx[6], "127.0.0.1")
    return body, {"challenge_id": result["challenge_id"], "flow_token": body["flow_token"], "code": email_ctx[1].sent[-1][1]}


def enroll(ctx, email_ctx, address="private@example.com"):
    _, verify = start_enroll(ctx, email_ctx, address)
    result = email_ctx[0].verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1")
    assert result["backup_email"]["configured"]
    return verify


def start_recover(ctx, email_ctx, address="private@example.com"):
    ctx[2][0] += 61
    body = {"email": address, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    result = email_ctx[0].start_recovery(body, "127.0.0.2")
    return body, {"challenge_id": result["challenge_id"], "flow_token": body["flow_token"], "code": email_ctx[1].sent[-1][1]}


def phone_recover(ctx, email_ctx, number="8765432109"):
    _, verify = start_recover(ctx, email_ctx)
    proof = email_ctx[0].verify_recovery(verify, "127.0.0.2")
    body = {"recovery_token": proof["recovery_token"], "new_phone": number,
            "flow_token": verify["flow_token"], "request_id": str(uuid.uuid4())}
    result = email_ctx[0].start_phone(body, "127.0.0.2")
    return {**body, "challenge_id": result["challenge_id"], "code": "194628"}


def test_enrollment_requires_phone_session_proof_and_verified_address(ctx, email_ctx):
    service, mail = email_ctx
    body = {"email": "private@example.com", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    fails("invalid_action_proof", lambda: service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1"))
    assert not mail.sent
    start, verify = start_enroll(ctx, email_ctx)
    assert not ctx[4].status(ctx[5], ctx[6])["backup_email"]["configured"]
    with ctx[0].transaction() as tx:
        other_binding = issue_web_session_in(tx, ctx[5], secrets.token_urlsafe(32), at=ctx[2][0])
    fails("email_verification_invalid", lambda: service.verify_enrollment(ctx[5], verify, other_binding, "127.0.0.1"))
    # Correct OTP submitted from the wrong session is consumed; use a new challenge.
    ctx[2][0] += 61
    start["request_id"] = str(uuid.uuid4())
    sent = service.start_enrollment(ctx[5], start, ctx[6], "127.0.0.1")
    verify.update(challenge_id=sent["challenge_id"], code=mail.sent[-1][1])
    result = service.verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1")
    assert result["backup_email"]["masked_email"] == "p•••@example.com"
    fails("email_verification_invalid", lambda: service.verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1"))
    fails("invalid_action_proof", lambda: service.remove(ctx[5], {"action_token": start["action_token"]}, ctx[6]))
    with ctx[0].read() as tx:
        encoded = json.dumps(tx.list("account_backup_emails") + tx.list("email_challenges") + tx.list("account_action_proofs"))
    assert "private@example.com" not in encoded and verify["code"] not in encoded and start["action_token"] not in encoded


def test_full_recovery_retains_identity_revokes_sessions_and_replays(ctx, email_ctx):
    enroll(ctx, email_ctx)
    body = phone_recover(ctx, email_ctx)
    result = email_ctx[0].verify_phone(body, "127.0.0.2", native=True)
    assert result["user"]["id"] == ctx[5]["id"] and result["user"]["auth_epoch"] == 1
    assert result["user"]["phone"] == "+918765432109" and not result["user"]["driver_approved"]
    assert ctx[3].mobile_auth.authenticate(ctx[7]) is None
    authenticated = ctx[3].mobile_auth.authenticate(result["token"])
    assert authenticated["user"]["id"] == ctx[5]["id"]
    authenticated["lock"].release()
    with ctx[0].read() as tx:
        current = tx.get("users", ctx[5]["id"])
        assert not session_binding_matches_in(tx, current, ctx[6])
        assert not tx.list("email_recovery_proofs") and not tx.list("account_action_proofs")
        assert tx.get("account_backup_emails", current["id"])
        assert all(row.get("status") == "replaced" for row in tx.list("phone_identities") if row.get("phone") != "+918765432109")
    with pytest.raises(PhoneAuthError):
        email_ctx[0].verify_phone(body, "127.0.0.2", native=True)
    # Repeat recovery from the retained verified email to a second new phone.
    second = phone_recover(ctx, email_ctx, "7654321098")
    result2 = email_ctx[0].verify_phone(second, "127.0.0.2", native=True)
    assert result2["user"]["id"] == result["user"]["id"] and result2["user"]["auth_epoch"] == 2
    assert ctx[3].mobile_auth.authenticate(result["token"]) is None


def test_unknown_address_gets_identical_delivery_and_cannot_recover(ctx, email_ctx):
    service, mail = email_ctx
    _, verify = start_recover(ctx, email_ctx, "unknown@example.com")
    assert mail.sent[-1][0] == "unknown@example.com"
    fails("email_verification_invalid", lambda: service.verify_recovery(verify, "127.0.0.2"))
    with ctx[0].read() as tx:
        assert not tx.list("email_recovery_proofs")


def test_guess_limit_expiry_resend_and_no_plain_otp(ctx, email_ctx):
    service, mail = email_ctx
    body, verify = start_enroll(ctx, email_ctx)
    with ctx[0].read() as tx:
        encoded = json.dumps(tx.list("email_challenges"))
    assert verify["code"] not in encoded and body["email"] not in encoded
    bad = {**verify, "code": "000000" if verify["code"] != "000000" else "999999"}
    for _ in range(5):
        fails("email_invalid_code", lambda: service.verify_enrollment(ctx[5], bad, ctx[6], "127.0.0.1"))
    fails("email_rate_limited", lambda: service.verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1"))
    assert len(mail.sent) == 1
    assert service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1")["challenge_id"] == verify["challenge_id"]
    body["request_id"] = str(uuid.uuid4())
    fails("email_rate_limited", lambda: service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1"))
    ctx[2][0] += 61
    sent = service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1")
    fails("email_verification_invalid", lambda: service.verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1"))
    ctx[2][0] += 301
    verify.update(challenge_id=sent["challenge_id"], code=mail.sent[-1][1])
    fails("email_verification_invalid", lambda: service.verify_enrollment(ctx[5], verify, ctx[6], "127.0.0.1"))


def test_remove_and_replacement_invalidate_email_proof_and_newphone_challenge(ctx, email_ctx):
    enroll(ctx, email_ctx)
    body = phone_recover(ctx, email_ctx)
    replacement = start_enroll(ctx, email_ctx, "replacement@example.com")[1]
    email_ctx[0].verify_enrollment(ctx[5], replacement, ctx[6], "127.0.0.1")
    with pytest.raises(PhoneAuthError):
        email_ctx[0].verify_phone(body, "127.0.0.2")
    _, old = start_recover(ctx, email_ctx)
    fails("email_verification_invalid", lambda: email_ctx[0].verify_recovery(old, "127.0.0.2"))
    token = action_proof(ctx, "backup_email")
    assert not email_ctx[0].remove(ctx[5], {"action_token": token}, ctx[6])["backup_email"]["configured"]
    fails("invalid_action_proof", lambda: email_ctx[0].remove(ctx[5], {"action_token": token}, ctx[6]))


def test_delivery_does_not_hold_sqlite_lock_and_logout_during_send_denies(ctx, email_ctx):
    service, mail = email_ctx
    token = action_proof(ctx, "backup_email")
    mail.entered, mail.release = threading.Event(), threading.Event()
    body = {"email": "private@example.com", "action_token": token, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(service.start_enrollment, ctx[5], body, ctx[6], "127.0.0.1")
        assert mail.entered.wait(2)
        with ctx[0].transaction() as tx:
            tx.delete("web_sessions", ctx[6].partition(":")[2])
        mail.release.set()
        with pytest.raises(PhoneAuthError):
            work.result()
    with ctx[0].read() as tx:
        row = tx.list("email_challenges")[0]
        assert row["state"] == "failed" and row["code_hash"] is None
        assert not tx.list("account_backup_emails")


def test_failed_delivery_has_no_usable_code_and_safe_retry(ctx, email_ctx):
    service, mail = email_ctx
    mail.fail = True
    token = action_proof(ctx, "backup_email")
    body = {"email": "private@example.com", "action_token": token, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    failure = fails("backup_email_unavailable", lambda: service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1"))
    assert "PRIVATE" not in str(failure)
    with ctx[0].read() as tx:
        row = tx.list("email_challenges")[0]
        assert row["code_hash"] is None and row["state"] == "failed"
    ctx[2][0] += 61
    mail.fail = False
    body["request_id"] = str(uuid.uuid4())
    sent = service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1")
    assert sent["challenge_id"] != row["id"]


def test_concurrent_phone_recovery_completes_once(ctx, email_ctx):
    enroll(ctx, email_ctx)
    body = phone_recover(ctx, email_ctx)
    provider = ctx[1]
    provider.entered, provider.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(email_ctx[0].verify_phone, body, "127.0.0.2", True)
        assert provider.entered.wait(2)
        second = pool.submit(email_ctx[0].verify_phone, body, "127.0.0.2", True)
        with pytest.raises(PhoneAuthError):
            second.result()
        provider.release.set()
        assert first.result()["user"]["auth_epoch"] == 1
    with ctx[0].read() as tx:
        assert len(tx.list("mobile_sessions")) == 1


def test_reserved_phone_and_cross_flow_proof_do_not_take_over_another_account(ctx, email_ctx):
    enroll(ctx, email_ctx)
    body = phone_recover(ctx, email_ctx)
    fails("invalid_phone_flow", lambda: email_ctx[0].verify_phone({**body, "flow_token": secrets.token_urlsafe(32)}, "127.0.0.2"))
    key = ctx[3]._digest("phone", "+918765432109")
    with ctx[0].transaction() as tx:
        tx.put("phone_identities", key, {"id": key, "user_id": "someone-else", "status": "active"})
    fails("recovery_unavailable", lambda: email_ctx[0].verify_phone(body, "127.0.0.2"))
    with ctx[0].read() as tx:
        assert tx.get("users", ctx[5]["id"])["auth_epoch"] == 0
        assert tx.get("phone_identities", key)["user_id"] == "someone-else"


def test_deletion_erases_email_material_and_missing_configuration_is_closed(ctx, email_ctx):
    enroll(ctx, email_ctx)
    start_recover(ctx, email_ctx)
    token = action_proof(ctx, "delete")
    ctx[4].delete(ctx[5], {"action_token": token, "confirm": True, "idempotency_key": str(uuid.uuid4())}, ctx[6])
    with ctx[0].read() as tx:
        for collection in ("account_backup_emails", "email_challenges", "email_recovery_proofs", "email_send_requests", "email_send_state"):
            assert not tx.list(collection)
    disabled = BackupEmailService(ctx[0], ctx[4], provider=Mail(), daily_limit=100)
    fails("backup_email_unavailable", lambda: disabled.start_recovery({}, "127.0.0.1"))
    with pytest.raises(ValueError, match="encryption key differs"):
        BackupEmailService(ctx[0], ctx[4], provider=Mail(), encryption_key=Fernet.generate_key(), daily_limit=100)


def test_email_proof_expiry_and_mail_code_cannot_be_a_recovery_token(ctx, email_ctx):
    enroll(ctx, email_ctx)
    _, verify = start_recover(ctx, email_ctx)
    proof = email_ctx[0].verify_recovery(verify, "127.0.0.2")
    payload = {"flow_token": verify["flow_token"], "recovery_token": proof["recovery_token"],
               "new_phone": "8765432109", "request_id": str(uuid.uuid4())}
    fails("email_verification_invalid", lambda: email_ctx[0].start_phone({**payload, "recovery_token": verify["code"]}, "127.0.0.2"))
    with ctx[0].read() as tx:
        encoded = json.dumps(tx.list("email_recovery_proofs"))
    assert proof["recovery_token"] not in encoded and verify["code"] not in encoded
    ctx[2][0] += 601
    fails("email_verification_invalid", lambda: email_ctx[0].start_phone(payload, "127.0.0.2"))


def test_email_removal_during_phone_verification_is_rechecked_after_provider(ctx, email_ctx):
    enroll(ctx, email_ctx)
    body = phone_recover(ctx, email_ctx)
    token = action_proof(ctx, "backup_email")
    provider = ctx[1]
    provider.entered, provider.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(email_ctx[0].verify_phone, body, "127.0.0.2", True)
        assert provider.entered.wait(2)
        email_ctx[0].remove(ctx[5], {"action_token": token}, ctx[6])
        provider.release.set()
        with pytest.raises(PhoneAuthError):
            work.result()
    with ctx[0].read() as tx:
        assert tx.get("users", ctx[5]["id"])["auth_epoch"] == 0
        assert not tx.get("account_backup_emails", ctx[5]["id"])


def test_send_limits_survive_restart_and_address_ip_rotation(ctx, email_ctx):
    service, mail = email_ctx
    for count in range(5):
        body = {"email": "unknown@example.com", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
        service.start_recovery(body, f"127.0.0.{count + 1}")
        ctx[2][0] += 61
    # Reconstructing service does not reset durable admission counters.
    restarted = BackupEmailService(ctx[0], ctx[4], provider=mail, encryption_key=base64.urlsafe_b64encode(service.cipher._signing_key + service.cipher._encryption_key), daily_limit=100, clock=service.clock)
    body["request_id"] = str(uuid.uuid4())
    fails("phone_auth_rate_limited", lambda: restarted.start_recovery(body, "127.0.0.99"))
    assert len(mail.sent) == 5
    service.daily_limit = 5
    fresh = {"email": "another@example.com", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    fails("phone_auth_rate_limited", lambda: service.start_recovery(fresh, "127.0.0.99"))
    assert len(mail.sent) == 5


def test_demo_admin_and_stale_epoch_cannot_enroll(ctx, email_ctx):
    service, _ = email_ctx
    token = action_proof(ctx, "backup_email")
    body = {"email": "private@example.com", "action_token": token, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    for field, value in (("development", True), ("role", "admin"), ("auth_epoch", 1)):
        with ctx[0].transaction() as tx:
            changed = {**ctx[5], field: value}
            tx.put("users", changed["id"], changed)
        fails("account_unavailable", lambda: service.start_enrollment(ctx[5], body, ctx[6], "127.0.0.1"))
    with ctx[0].read() as tx:
        assert not tx.list("email_challenges")


def test_same_verified_address_cannot_replace_another_accounts_backup(ctx, email_ctx):
    enroll(ctx, email_ctx)
    store, provider, now, phone, life, _, _, _ = ctx
    payload = {"phone": "8765432109", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    challenge = phone.start(payload, "127.0.0.3")
    signed = phone.verify({"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"], "code": "194628",
        "consent": {"terms_version": phone.terms_version, "privacy_version": phone.privacy_version,
                    "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}, "127.0.0.3", native=True)
    with store.transaction() as tx:
        actor = tx.get("users", signed["user"]["id"])
        binding = issue_web_session_in(tx, actor, secrets.token_urlsafe(32), at=now[0])
    second = store, provider, now, phone, life, actor, binding, signed["token"]
    _, verify = start_enroll(second, email_ctx)
    fails("backup_email_unavailable", lambda: email_ctx[0].verify_enrollment(actor, verify, binding, "127.0.0.3"))
    with store.read() as tx:
        assert tx.get("account_backup_emails", ctx[5]["id"])
        assert not tx.get("account_backup_emails", actor["id"])
