"""Isolated lifecycle service security/data boundaries; no real SMS or money."""
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.account_lifecycle import AccountLifecycleService, AccountLifecycleError
from app.auth import issue_web_session_in, session_binding_matches_in, current_actor_matches
from app.driver_verification import DriverVerificationService
from app.phone_auth import PhoneAuthService, PhoneAuthError
from app.store import Store
from test_phone_auth import Provider


@pytest.fixture
def ctx(tmp_path):
    store = Store(tmp_path / "lifecycle.db")
    provider = Provider()
    now = [1800000000.0]
    phone = PhoneAuthService(store, provider=provider, hmac_key="k" * 48,
                            global_daily_limit=100, clock=lambda: now[0])
    DriverVerificationService(store)
    life = AccountLifecycleService(store, phone, clock=lambda: now[0])
    payload = {"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    challenge = phone.start(payload, "127.0.0.1")
    result = phone.verify({"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"],
              "code": "194628", "consent": {"terms_version": phone.terms_version, "privacy_version": phone.privacy_version,
              "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}, "127.0.0.1", native=True)
    user_id = result["user"]["id"]
    phone.profile(user_id, {"name": "PRIVATE ORIGINAL NAME"})
    with store.transaction() as tx:
        actor = tx.get("users", user_id)
        binding = issue_web_session_in(tx, actor, secrets.token_urlsafe(32), at=now[0])
    return store, provider, now, phone, life, actor, binding, result["token"]


def challenge_for(ctx, purpose="delete"):
    store, provider, now, phone, life, actor, binding, _ = ctx
    now[0] += 61
    payload = {"purpose": purpose, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    result = life.reauth_start(actor, payload, binding, "127.0.0.1")
    return result, payload


def action_proof(ctx, purpose="delete"):
    challenge, payload = challenge_for(ctx, purpose)
    life, actor, binding = ctx[4:7]
    return life.reauth_verify(actor, {"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"],
                             "code": "194628"}, binding, "127.0.0.1")["action_token"]


def enroll(ctx):
    proof = action_proof(ctx, "recovery_key")
    secret = secrets.token_urlsafe(32)
    assert ctx[4].set_recovery_key(ctx[5], {"action_token": proof, "recovery_secret": secret, "saved": True}, ctx[6]) == {"recovery_key_configured": True}
    return secret


def recover_start(ctx, secret, number="8765432109"):
    payload = {"recovery_secret": secret, "new_phone": number, "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    result = ctx[4].recovery_start(payload, "127.0.0.2")
    body = {"challenge_id": result["challenge_id"], "flow_token": payload["flow_token"], "code": "194628",
            "recovery_secret": secret, "new_recovery_secret": secrets.token_urlsafe(32), "saved": True}
    return body


def fails(code, call):
    with pytest.raises(PhoneAuthError) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def test_reauth_bound_to_current_session_purpose_and_single_use(ctx):
    store, _, now, _, life, actor, binding, _ = ctx
    token = action_proof(ctx, "recovery_key")
    assert life.status(actor, binding)["recently_reauthenticated_until"] is not None
    fails("invalid_action_proof", lambda: life.delete(actor, {"action_token": token, "confirm": True,
          "idempotency_key": str(uuid.uuid4())}, binding))
    with store.transaction() as tx:
        second = issue_web_session_in(tx, actor, secrets.token_urlsafe(32), at=now[0])
    payload = {"action_token": token, "recovery_secret": secrets.token_urlsafe(32), "saved": True}
    fails("invalid_action_proof", lambda: life.set_recovery_key(actor, payload, second))
    assert life.set_recovery_key(actor, payload, binding)["recovery_key_configured"] is True
    fails("invalid_action_proof", lambda: life.set_recovery_key(actor, payload, binding))
    with store.read() as tx:
        encoded = json.dumps(tx.list("account_action_proofs") + tx.list("account_recovery_keys"))
    assert token not in encoded and payload["recovery_secret"] not in encoded


def test_expired_action_proof_and_missing_saved_ack_are_rejected(ctx):
    token = action_proof(ctx, "recovery_key")
    payload = {"action_token": token, "recovery_secret": secrets.token_urlsafe(32), "saved": "true"}
    fails("recovery_save_required", lambda: ctx[4].set_recovery_key(ctx[5], payload, ctx[6]))
    ctx[2][0] += 301
    payload["saved"] = True
    fails("reauth_expired", lambda: ctx[4].set_recovery_key(ctx[5], payload, ctx[6]))


def test_logout_during_provider_reauth_cannot_grant_action(ctx):
    store, provider, _, _, life, actor, binding, _ = ctx
    challenge, payload = challenge_for(ctx)
    provider.entered, provider.release = threading.Event(), threading.Event()
    body = {"challenge_id": challenge["challenge_id"], "flow_token": payload["flow_token"], "code": "194628"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(life.reauth_verify, actor, body, binding, "127.0.0.1")
        assert provider.entered.wait(2)
        with store.transaction() as tx:
            tx.delete("web_sessions", binding.partition(":")[2])
        provider.release.set()
        with pytest.raises(AccountLifecycleError) as denied:
            result.result()
        assert denied.value.code == "reauth_required"
    with store.read() as tx:
        assert not tx.list("account_action_proofs")


def test_normal_signin_challenge_cannot_authorize_deletion(ctx):
    _, _, now, phone, life, actor, binding, _ = ctx
    now[0] += 61
    payload = {"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    challenge = phone.start(payload, "127.0.0.1")
    fails("invalid_phone_flow", lambda: life.reauth_verify(actor, {"challenge_id": challenge["challenge_id"],
          "flow_token": payload["flow_token"], "code": "194628"}, binding, "127.0.0.1"))


@pytest.mark.parametrize("status", ["agreed", "passenger_reported", "disputed", "refund_requested", "refund_reported"])
def test_unresolved_payment_prevents_deletion_without_consuming_proof(ctx, status):
    store, _, _, _, life, actor, binding, _ = ctx
    token = action_proof(ctx)
    with store.transaction() as tx:
        tx.put("bookings", "booking", {"id": "booking", "driver_id": "other", "passenger_id": actor["id"], "status": "segment_completed"})
        tx.put("payments", "booking", {"id": "booking", "booking_id": "booking", "status": status})
    blocked = fails("account_deletion_blocked", lambda: life.delete(actor, {"action_token": token, "confirm": True,
                    "idempotency_key": str(uuid.uuid4())}, binding))
    assert blocked.blockers == [{"code": "unresolved_payment", "booking_id": "booking"}]
    with store.transaction() as tx:
        payment = tx.get("payments", "booking")
        payment["status"] = "voided_unpaid" if status == "agreed" else "refunded"
        tx.put("payments", payment["id"], payment)
    assert life.delete(actor, {"action_token": token, "confirm": True, "idempotency_key": str(uuid.uuid4())}, binding)["deleted"]


def test_active_rides_block_and_new_blocker_after_proof_is_rechecked(ctx):
    store, _, _, _, life, actor, binding, _ = ctx
    token = action_proof(ctx)
    assert life.status(actor, binding)["deletion_allowed"] is True
    with store.transaction() as tx:
        tx.put("trips", "trip", {"id": "trip", "driver_id": actor["id"], "status": "started"})
        tx.put("bookings", "booking", {"id": "booking", "driver_id": "other", "passenger_id": actor["id"], "status": "accepted"})
    blockers = life.status(actor, binding)["blockers"]
    assert {row["code"] for row in blockers} == {"active_trip", "active_booking"}
    fails("account_deletion_blocked", lambda: life.delete(actor, {"action_token": token, "confirm": True,
          "idempotency_key": str(uuid.uuid4())}, binding))
    with store.read() as tx:
        assert tx.get("trips", "trip")["status"] == "started"
        assert tx.get("bookings", "booking")["status"] == "accepted"


def test_delete_erases_current_personal_data_preserves_named_restricted_records(ctx):
    store, _, _, phone, life, actor, binding, old_token = ctx
    secret = enroll(ctx)
    token = action_proof(ctx)
    with store.transaction() as tx:
        tx.put("driver_applications", "application", {"id": "application", "user_id": actor["id"], "status": "draft",
               "version": 1, "legal_name": "PRIVATE LEGAL NAME", "applicant_note": "PRIVATE NOTE"})
        tx.put("driver_documents", "document", {"id": "document", "user_id": actor["id"], "application_id": "application"})
        tx._connection.execute("INSERT INTO driver_document_blobs(id,content) VALUES (?,?)", ("document", b"PRIVATE DOCUMENT"))
        tx.put("driver_document_access", "access", {"id": "access", "document_id": "document"})
        tx.put("payout_accounts", actor["id"], {"id": actor["id"], "upi_id": "private@upi"})
        tx.put("messages", "own", {"id": "own", "sender_id": actor["id"], "text": "PRIVATE CHAT"})
        tx.put("ratings", "rating", {"id": "rating", "author_id": actor["id"], "comment": "PRIVATE COMMENT", "publish_comment": True})
        tx.put("safety_reports", "report", {"id": "report", "reporter_id": actor["id"], "details": "RESTRICTED SAFETY EVIDENCE"})
        tx.put("bookings", "booking", {"id": "booking", "driver_id": actor["id"], "passenger_id": "other", "status": "segment_completed",
               "driver_name": actor["name"], "match": {"driver_name": actor["name"], "driver_summary": {"name": actor["name"]}}})
        tx.put("payments", "booking", {"id": "booking", "booking_id": "booking", "status": "owner_confirmed",
               "amount_paise": 50000, "currency": "INR", "payee_name": "PRIVATE PAYEE", "upi_id": "private@upi", "note": "PRIVATE NOTE"})
        tx.put("trusted_contact_links", "link", {"id": "link", "actor_id": "other", "booking_id": "booking"})
    result = life.delete(actor, {"action_token": token, "confirm": True, "idempotency_key": str(uuid.uuid4())}, binding)
    assert result["deleted"] is True and "restricted_safety_audit" in result["retained_categories"]
    assert phone.mobile_auth.authenticate(old_token) is None
    with store.read() as tx:
        user = tx.get("users", actor["id"])
        assert user["account_status"] == "deleted" and "auth_phone" not in user and "phone" not in user
        assert not session_binding_matches_in(tx, user, binding)
        assert not tx.list("web_sessions") and not tx.list("mobile_sessions") and not tx.list("messages")
        assert not tx.list("driver_documents") and not tx.list("driver_document_access")
        assert tx._connection.execute("SELECT count(*) FROM driver_document_blobs").fetchone()[0] == 0
        assert not tx.list("payout_accounts") and not tx.list("account_recovery_keys")
        assert not tx.list("trusted_contact_links")
        assert tx.get("ratings", "rating") is None
        assert tx.get("safety_reports", "report")["details"] == "RESTRICTED SAFETY EVIDENCE"
        assert tx.get("payments", "booking")["amount_paise"] == 50000
        assert "upi_id" not in tx.get("payments", "booking")
        reservation = tx.list("phone_identities")[0]
        assert reservation["status"] == "deleted" and "phone" not in reservation
    fails("recovery_unavailable", lambda: life.recovery_start({"recovery_secret": secret}, "127.0.0.1"))


def test_recovery_rotates_phone_epoch_sessions_and_key_without_lifting_privileges(ctx):
    store, _, _, phone, life, actor, binding, old_token = ctx
    secret = enroll(ctx)
    body = recover_start(ctx, secret)
    result = life.recovery_verify(body, "127.0.0.2", native=True)
    assert result["user"]["id"] == actor["id"] and result["user"]["phone"] == "+918765432109"
    assert result["user"]["driver_approved"] is False and result["user"]["role"] == "member"
    assert result["user"]["share_phone"] is False and result["user"]["auth_epoch"] == 1
    assert phone.mobile_auth.authenticate(old_token) is None
    auth = phone.mobile_auth.authenticate(result["token"])
    assert auth is not None
    auth["lock"].release()
    with store.read() as tx:
        user = tx.get("users", actor["id"])
        assert not current_actor_matches(user, actor)
        assert not session_binding_matches_in(tx, user, binding)
        assert len(tx.list("users")) == 1
        assert len(tx.list("account_recovery_keys")) == 1
        assert all(body["new_recovery_secret"] not in json.dumps(row) for row in tx.list("account_recovery_keys"))
        states = {row["status"] for row in tx.list("phone_identities")}
        assert states == {"active", "replaced"}
        assert all("phone" not in row for row in tx.list("phone_identities") if row["status"] == "replaced")
    fails("recovery_unavailable", lambda: life.recovery_start({"recovery_secret": secret}, "127.0.0.1"))
    fails("recovery_unavailable", lambda: life.recovery_verify(body, "127.0.0.2", native=True))


def test_recovery_cannot_claim_existing_number_or_restricted_account(ctx):
    store, provider, _, _, life, actor, _, _ = ctx
    secret = enroll(ctx)
    body = recover_start(ctx, secret)
    key = ctx[3]._digest("phone", "+918765432109")
    with store.transaction() as tx:
        tx.put("phone_identities", key, {"id": key, "user_id": "other", "status": "active"})
    fails("recovery_unavailable", lambda: life.recovery_verify(body, "127.0.0.2"))
    with store.transaction() as tx:
        user = tx.get("users", actor["id"])
        user["account_status"] = "suspended"
        tx.put("users", user["id"], user)
    sent = len(provider.sends)
    fails("recovery_unavailable", lambda: life.recovery_start({"recovery_secret": secret}, "127.0.0.1"))
    assert len(provider.sends) == sent


def test_ordinary_challenge_issued_before_recovery_cannot_sign_into_moved_identity(ctx):
    _, _, now, phone, life, _, _, _ = ctx
    secret = enroll(ctx)
    now[0] += 61
    stale_payload = {"phone": "9876543210", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    old = phone.start(stale_payload, "127.0.0.1")
    body = recover_start(ctx, secret)
    life.recovery_verify(body, "127.0.0.2")
    fails("invalid_phone_flow", lambda: phone.verify({"challenge_id": old["challenge_id"],
        "flow_token": stale_payload["flow_token"], "code": "194628", "consent": {"terms_version": phone.terms_version,
        "privacy_version": phone.privacy_version, "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}, "127.0.0.1"))


def test_recovery_code_rotation_during_provider_call_rejects_old_result(ctx):
    store, provider, _, _, life, actor, _, _ = ctx
    secret = enroll(ctx)
    body = recover_start(ctx, secret)
    provider.entered, provider.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(life.recovery_verify, body, "127.0.0.2")
        assert provider.entered.wait(2)
        with store.transaction() as tx:
            user = tx.get("users", actor["id"])
            tx.delete("account_recovery_keys", user["recovery_key_id"])
            user.pop("recovery_key_id")
            tx.put("users", user["id"], user)
        provider.release.set()
        with pytest.raises(AccountLifecycleError) as denied:
            result.result()
        assert denied.value.code == "recovery_unavailable"
    with store.read() as tx:
        assert tx.get("users", actor["id"])["auth_phone"] == "+919876543210"


def test_staff_demo_and_stale_epoch_cannot_self_manage(ctx):
    store, _, now, _, life, actor, binding, _ = ctx
    with store.transaction() as tx:
        user = tx.get("users", actor["id"])
        user["auth_epoch"] = 1
        tx.put("users", user["id"], user)
    fails("account_unavailable", lambda: life.status(actor, binding))
    for change in ({"development": True}, {"role": "staff"}):
        with store.transaction() as tx:
            current = {**actor, **change}
            tx.put("users", current["id"], current)
            new_binding = issue_web_session_in(tx, current, secrets.token_urlsafe(32), at=now[0])
        fails("account_unavailable", lambda: life.status(current, new_binding))


def test_recovery_stale_actor_rejected_at_all_transaction_actor_boundaries(ctx):
    from app.community import CommunityService, CommunityError
    from app.driver_verification import DriverVerificationError
    from app.payments import PaymentService, PaymentError
    from app.domain import Service, DomainError
    store, _, _, phone, life, actor, _, _ = ctx
    body = recover_start(ctx, enroll(ctx))
    life.recovery_verify(body, "127.0.0.2")
    with pytest.raises(CommunityError) as community_error:
        CommunityService(store).dispatch("update_profile", actor, {"name": "STALE OVERWRITE", "share_phone": False})
    assert community_error.value.status == 401
    with pytest.raises(DriverVerificationError) as driver_error:
        DriverVerificationService(store).get_application(actor)
    assert driver_error.value.status == 401
    with pytest.raises(PaymentError) as payment_error:
        PaymentService(store, enabled=True).dispatch("payments", actor, {})
    assert payment_error.value.status == 403
    with pytest.raises(DomainError) as domain_error:
        Service(store, None).dispatch("state", actor, {})
    assert domain_error.value.status == 401
    fails("account_unavailable", lambda: phone.profile(actor["id"], {"name": "STALE OVERWRITE"}, actor=actor))
    with store.read() as tx:
        assert tx.get("users", actor["id"])["name"] == "PRIVATE ORIGINAL NAME"


def test_native_bound_proof_cannot_be_consumed_after_same_token_logout(ctx):
    store, _, _, phone, life, actor, _, token = ctx
    binding = "native:" + phone.mobile_auth.token_hash(token)
    native_ctx = (*ctx[:6], binding, token)
    proof = action_proof(native_ctx)
    phone.mobile_auth.revoke(phone.mobile_auth.token_hash(token))
    fails("reauth_required", lambda: life.delete(actor, {"action_token": proof, "confirm": True,
          "idempotency_key": str(uuid.uuid4())}, binding))
    with store.read() as tx:
        assert tx.get("users", actor["id"])["account_status"] == "active"


def test_recovery_code_survives_restart_and_invalid_code_never_spends_sms(ctx):
    store, provider, now, phone, life, _, _, _ = ctx
    secret = enroll(ctx)
    sent = len(provider.sends)
    bad = secrets.token_urlsafe(32)
    fails("recovery_unavailable", lambda: life.recovery_start({"recovery_secret": bad}, "127.0.0.1"))
    assert len(provider.sends) == sent
    restored_store = Store(store.path)
    restored_phone = PhoneAuthService(restored_store, provider=provider, hmac_key="k" * 48,
                                     global_daily_limit=100, clock=lambda: now[0])
    restored = AccountLifecycleService(restored_store, restored_phone, clock=lambda: now[0])
    result = restored.recovery_start({"recovery_secret": secret, "new_phone": "8765432109",
                                     "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}, "127.0.0.1")
    assert result["challenge_id"] and len(provider.sends) == sent + 1


def test_saved_ack_and_delete_confirmation_are_exact_booleans(ctx):
    secret = enroll(ctx)
    body = recover_start(ctx, secret)
    body["saved"] = "true"
    fails("recovery_save_required", lambda: ctx[4].recovery_verify(body, "127.0.0.2"))
    proof = action_proof(ctx)
    fails("invalid_action_proof", lambda: ctx[4].delete(ctx[5], {"action_token": proof, "confirm": "true",
          "idempotency_key": str(uuid.uuid4())}, ctx[6]))


def test_signin_started_before_other_flow_claims_number_is_rejected(ctx):
    store, _, now, phone, _, _, _, _ = ctx
    now[0] += 61
    payload = {"phone": "8765432109", "flow_token": secrets.token_urlsafe(32), "request_id": str(uuid.uuid4())}
    challenge = phone.start(payload, "127.0.0.1")
    # Simulate another authorized identity transaction completing while this
    # provider challenge is pending; the old code must not mint its session.
    with store.transaction() as tx:
        user = dict(ctx[5], id="other-real-member", auth_phone="+918765432109", phone="+918765432109")
        tx.put("users", user["id"], user)
        key = phone._digest("phone", user["auth_phone"])
        tx.put("phone_identities", key, {"id": key, "user_id": user["id"], "status": "active", "phone": user["phone"]})
    fails("invalid_phone_flow", lambda: phone.verify({"challenge_id": challenge["challenge_id"],
        "flow_token": payload["flow_token"], "code": "194628", "consent": {"terms_version": phone.terms_version,
        "privacy_version": phone.privacy_version, "terms_accepted": True, "privacy_accepted": True, "adult_attested": True}}, "127.0.0.1"))


def test_deletion_removes_financial_free_text_copies_and_public_profile(ctx):
    from app.reviews import ReviewsService, ReviewsError
    store, _, _, _, life, actor, binding, _ = ctx
    token = action_proof(ctx)
    with store.transaction() as tx:
        tx.put("users", "other", {"id": "other", "name": "Counterparty", "role": "member"})
        tx.put("trips", "trip", {"id": "trip", "driver_id": actor["id"], "status": "completed", "driver_name": actor["name"]})
        tx.put("bookings", "booking", {"id": "booking", "trip_id": "trip", "driver_id": actor["id"],
               "passenger_id": "other", "status": "segment_completed"})
        event = {"id": "event", "booking_id": "booking", "actor_id": actor["id"], "action": "void_unpaid",
                 "reason": "PRIVATE FINANCIAL TEXT", "status": "voided_unpaid", "version": 2}
        tx.put("payment_events", "event", event)
        tx.put("payments", "booking", {"id": "booking", "booking_id": "booking", "status": "voided_unpaid",
               "amount_paise": 1000, "currency": "INR", "version": 2, "void_reason": "PRIVATE FINANCIAL TEXT",
               "events": [event], "unexpected_free_text": "PRIVATE FINANCIAL TEXT"})
        budget_event = {"id": "budget-event", "trip_id": "trip", "actor_id": actor["id"],
                        "reason": "PRIVATE FINANCIAL TEXT", "fuel_paise": 1000, "version": 1}
        tx.put("trip_budget_events", "budget-event", budget_event)
        tx.put("trip_expense_budgets", "trip", {"id": "trip", "trip_id": "trip", "fuel_paise": 1000,
               "toll_paise": 0, "owner_share_paise": 500, "total_paise": 1000, "passenger_cap_paise": 500,
               "events": [budget_event], "declaration": "owner_declared_unverified"})
    life.delete(actor, {"action_token": token, "confirm": True, "idempotency_key": str(uuid.uuid4())}, binding)
    with store.read() as tx:
        serialized = json.dumps([tx.list(collection) for collection in
            ("payments", "payment_events", "trip_expense_budgets", "trip_budget_events")])
        assert "PRIVATE FINANCIAL TEXT" not in serialized
        assert tx.get("payments", "booking")["amount_paise"] == 1000
    with pytest.raises(ReviewsError) as missing:
        ReviewsService(store).dispatch("driver_profile", {"id": "other"}, {"user_id": actor["id"]})
    assert missing.value.status == 404
