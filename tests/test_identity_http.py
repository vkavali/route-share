"""Real phone-auth HTTP boundaries for private identity review."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import secrets
import time
import uuid

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import create_app
from app.identity_verification import APPLICATIONS, DECISIONS, DOCUMENTS, DOCUMENT_ACCESS
from test_account_lifecycle_http import reauth as account_reauth
from test_phone_http import bearer, signup, web_headers

from PIL import Image
_png = BytesIO()
Image.new("RGB", (600, 800), "white").save(_png, format="PNG")
PNG = _png.getvalue()
_pdf = BytesIO()
Image.new("RGB", (600, 800), "white").save(_pdf, format="PDF")
PDF = _pdf.getvalue()


@pytest.fixture
def setup(tmp_path):
    class SMSFixture:
        ready = True

        def send(self, phone, *, challenge_id, expires_in):
            return "identity-http-handle-" + challenge_id

        def verify(self, handle, code):
            return handle.startswith("identity-http-handle-") and code == "831947"

    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "identity-http.sqlite"),
        "SECRET_KEY": "isolated-identity-http-session-key",
        "BETA_PASSWORD": "isolated-identity-http-demo-password",
        "PHONE_AUTH_ENABLED": True,
        "PHONE_AUTH_PROVIDER": SMSFixture(),
        "PUBLIC_OPERATOR_NAME": "Identity HTTP test operator",
        "PUBLIC_SUPPORT_EMAIL": "support@example.test",
        "PHONE_AUTH_HMAC_KEY": "i" * 48,
        "PHONE_AUTH_DAILY_LIMIT": 100,
        "DEMO_PASSWORD_ENABLED": False,
        "IDENTITY_EVIDENCE_KEY": Fernet.generate_key(),
    })
    now = [time.time()]
    app.extensions["phone_auth"].clock = lambda: now[0]
    app.extensions["account_lifecycle"].clock = lambda: now[0]
    app.extensions["identity_verification_service"].clock = lambda: datetime.fromtimestamp(now[0], tz=timezone.utc)
    app.extensions["identity_test_clock"] = now
    return app


def real_member(app, phone):
    client = app.test_client()
    verified, _old_csrf = signup(client, phone=phone)
    token = verified.json["csrf_token"]
    headers = web_headers(token)
    completed = client.post("/api/phone/profile", json={"name": "Identity HTTP member"}, headers=headers)
    assert completed.status_code == 200, completed.json
    assert completed.json["user"]["phone_verified"] is True
    assert completed.json["user"]["development"] is False
    return client, headers, completed.json["user"]["id"]


def real_native_member(app, phone):
    client = app.test_client(use_cookies=False)
    verified, _csrf = signup(client, native=True, phone=phone)
    headers = bearer(verified)
    completed = client.post("/api/phone/profile", json={"name": "Native identity member"}, headers=headers)
    assert completed.status_code == 200, completed.json
    assert completed.json["user"]["phone_verified"] is True
    assert completed.json["user"]["development"] is False
    return client, headers, completed.json["user"]["id"]


def make_reviewer(app, phone="8765432109"):
    client, headers, reviewer_id = real_member(app, phone)
    with app.extensions["beta_store"].transaction() as tx:
        user = tx.get("users", reviewer_id)
        user.update(role="staff", staff_capabilities=["verify.review"])
        tx.put("users", reviewer_id, user)
    return client, headers, reviewer_id


def save_application(client, headers, *, version=0):
    response = client.post("/api/identity_application", json={
        "legal_name": "Private Identity Applicant",
        "document_type": "driving_licence",
        "adult_attested": True,
        "document_consent": True,
        "expected_version": version,
    }, headers=headers)
    assert response.status_code == 200, response.json
    assert set(response.json) == {"application", "requirements"}
    assert response.json["requirements"]["available"] is True
    return response.json["application"]


def upload(client, headers, *, kind, version, payload=PNG, filename="evidence.png"):
    expires_on = (date.today() + timedelta(days=90)).isoformat() if kind == "identity_document" else ""
    response = client.post("/api/identity_documents", data={
        "file": (BytesIO(payload), filename),
        "kind": kind,
        "expires_on": expires_on,
        "expected_version": str(version),
    }, headers=headers, content_type="multipart/form-data")
    assert response.status_code == 200, response.json
    assert set(response.json) == {"application", "requirements"}
    return response.json["application"]


def test_phone_verified_member_can_submit_review_and_download_private_evidence(setup):
    app = setup
    owner, owner_headers, owner_id = real_member(app, "9876543210")
    reviewer, reviewer_headers, reviewer_id = make_reviewer(app)

    empty = owner.get("/api/identity_application", headers=owner_headers)
    assert empty.status_code == 200 and empty.json["application"] is None
    assert empty.headers["Cache-Control"] == "no-store"
    application = save_application(owner, owner_headers)
    application = upload(owner, owner_headers, kind="identity_document", version=application["version"])
    application = upload(owner, owner_headers, kind="selfie", version=application["version"], payload=PNG)
    assert len(application["documents"]) == 2

    document_id = next(d["id"] for d in application["documents"] if d["kind"] == "identity_document")
    downloaded = owner.get(f"/api/identity_document?document_id={document_id}", headers=owner_headers)
    assert downloaded.status_code == 200 and downloaded.data == PNG
    assert downloaded.headers["Content-Disposition"].startswith("attachment;")
    assert downloaded.headers["Cache-Control"] == "no-store"
    assert downloaded.headers["X-Content-Type-Options"] == "nosniff"

    submitted = owner.post("/api/submit_identity_application", json={
        "expected_version": application["version"]}, headers=owner_headers)
    assert submitted.status_code == 200, submitted.json
    application = submitted.json["application"]
    assert application["status"] == "submitted"

    queue = reviewer.get("/api/identity_verification_queue", headers=reviewer_headers)
    assert queue.status_code == 200 and set(queue.json) == {"applications", "requirements"}
    assert queue.json["applications"][0]["id"] == application["id"]
    assert queue.headers["Cache-Control"] == "no-store"
    self_review = owner.post("/api/review_identity_application", json={
        "application_id": application["id"], "expected_version": application["version"],
        "decision": "approved", "reason": "Attempted owner self-review.",
        "checks": {"document_readable": True, "name_matches": True,
                   "photo_matches": True, "adult_confirmed": True},
        "idempotency_key": "owner-self-review-001",
    }, headers=owner_headers)
    assert self_review.status_code == 403
    assert self_review.json["code"] in {"identity_self_review", "identity_forbidden"}
    for document in application["documents"]:
        opened = reviewer.get(f"/api/identity_document_preview?document_id={document['id']}", headers=reviewer_headers)
        assert opened.status_code == 200, opened.json
        assert set(opened.json) == {"image_data_url", "page", "page_count", "watermark"}
        assert opened.json["image_data_url"].startswith("data:image/jpeg;base64,")
        assert opened.headers["Cache-Control"] == "no-store"
        assert opened.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Disposition" not in opened.headers
        assert reviewer.get(f"/api/identity_document?document_id={document['id']}", headers=reviewer_headers).status_code == 404
        assert owner.get(f"/api/identity_document_preview?document_id={document['id']}", headers=owner_headers).status_code == 403
        for suffix in ("&page=0", "&page=13", "&page=01", "&page=1&page=2", "&original=true"):
            denied = reviewer.get(f"/api/identity_document_preview?document_id={document['id']}" + suffix, headers=reviewer_headers)
            assert denied.status_code == 400 and denied.headers["Cache-Control"] == "no-store"

    progress_response = reviewer.get('/api/identity_review_progress?application_id=' + application['id'], headers=reviewer_headers)
    assert progress_response.status_code == 200
    assert progress_response.headers['Cache-Control'] == 'no-store'
    for query in ('', '?application_id=' + application['id'] + '&application_id=' + application['id'],
                  '?application_id=' + application['id'] + '&unexpected=true'):
        invalid = reviewer.get('/api/identity_review_progress' + query, headers=reviewer_headers)
        assert invalid.status_code == 400 and invalid.json['code'] == 'review_progress_invalid'
    progress = progress_response.json
    for step in progress['steps']:
        saved = reviewer.post('/api/identity_review_progress', headers=reviewer_headers, json=dict(
            application_id=application['id'], expected_version=application['version'],
            expected_revision=progress['revision'], step=step['key'], checks={key:True for key in step['checks']}))
        assert saved.status_code == 200
        progress = saved.json
    assert progress['ready_for_approval']
    review = reviewer.post("/api/review_identity_application", json={
        "application_id": application["id"],
        "expected_version": application["version"],
        "decision": "approved",
        "reason": "Reviewed submitted identity evidence in the test flow.",
        "checks": {"document_readable": True, "name_matches": True,
                   "photo_matches": True, "adult_confirmed": True},
        "idempotency_key": "identity-review-http-001",
    }, headers=reviewer_headers)
    assert review.status_code == 200, review.json
    assert review.json["application"]["status"] == "approved"
    with app.extensions["beta_store"].read() as tx:
        stored_user = tx.get("users", owner_id)
        raw_application = tx.get(APPLICATIONS, application["id"])
        assert stored_user["verification"]["identity"] == "verified"
        assert stored_user["identity_approval"]["kind"] == "human_document_review"
        assert "Private Identity Applicant" not in json.dumps(raw_application)
        assert len(tx.list(DOCUMENTS)) == 2
        assert len(tx.list(DECISIONS)) == 1
        assert len(tx.list(DOCUMENT_ACCESS)) == 2
        assert tx._connection.execute("SELECT count(*) FROM identity_document_blobs").fetchone()[0] == 2

    # Exercise the native password-session boundary with a synthetic credential.
    # Public phone signup itself does not create a password.
    with app.extensions["beta_store"].transaction() as tx:
        user = tx.get("users", owner_id)
        user["password_hash"] = generate_password_hash("synthetic-native-identity-session")
        tx.put("users", owner_id, user)
    native = app.test_client(use_cookies=False)
    login = native.post("/api/mobile/login", json={
        "account": owner_id, "password": "synthetic-native-identity-session",
    })
    assert login.status_code == 200, login.json
    native_user = login.json["user"]
    assert native_user["access"]["can_request"] is True
    assert native_user["identity_review"]["status"] == "reviewed"
    for private_field in ("password_hash", "identity_approval", "auth_phone", "legal_name"):
        assert private_field not in native_user
    refreshed = native.get("/api/bootstrap", headers={"Authorization": "Bearer " + login.json["token"]})
    assert refreshed.status_code == 200
    assert refreshed.json["user"]["access"]["can_request"] is True
    assert refreshed.json["user"]["identity_review"] == native_user["identity_review"]
    bootstrap = owner.get("/api/bootstrap", headers=owner_headers)
    assert bootstrap.status_code == 200
    assert "Private Identity Applicant" not in json.dumps(bootstrap.json["user"])

    assert reviewer_id != owner_id


def test_identity_routes_require_auth_reviewer_capability_and_owner_scope(setup):
    app = setup
    owner, owner_headers, _owner_id = real_member(app, "9876543210")
    other, other_headers, _other_id = real_member(app, "8765432109")
    ops, ops_headers, _ops_id = make_reviewer(app, "7654321098")
    with app.extensions["beta_store"].transaction() as tx:
        user = tx.get("users", _ops_id)
        user["staff_capabilities"] = ["ops.read"]
        tx.put("users", _ops_id, user)

    assert app.test_client().get("/api/identity_application").status_code == 401
    unauthenticated = app.test_client()
    csrf = unauthenticated.get("/api/bootstrap").json["csrf_token"]
    assert unauthenticated.post("/api/identity_application", json={}, headers=web_headers(csrf)).status_code == 401
    assert owner.get("/api/identity_verification_queue", headers=owner_headers).status_code == 403
    assert ops.get("/api/identity_verification_queue", headers=ops_headers).status_code == 403

    application = save_application(owner, owner_headers)
    application = upload(owner, owner_headers, kind="identity_document", version=application["version"])
    doc_id = application["documents"][0]["id"]
    assert other.get(f"/api/identity_document?document_id={doc_id}", headers=other_headers).status_code == 404

    malformed = owner.post("/api/identity_documents", data={
        "file": (BytesIO(PNG), "x.png"), "kind": "identity_document",
        "expires_on": "", "expected_version": str(application["version"]), "unexpected": "x",
    }, headers=owner_headers, content_type="multipart/form-data")
    assert malformed.status_code == 400
    assert owner.post("/api/identity_documents", json={"kind": "identity_document"}, headers=owner_headers).status_code == 415


def test_native_phone_verified_member_can_use_identity_api_with_bearer(setup):
    app = setup
    client, headers, _user_id = real_native_member(app, "9876543210")
    response = client.get("/api/identity_application", headers=headers)
    assert response.status_code == 200 and response.json["application"] is None
    saved = client.post("/api/identity_application", json={
        "legal_name": "Native Identity Member",
        "document_type": "voter_id",
        "adult_attested": True,
        "document_consent": True,
        "expected_version": 0,
    }, headers=headers)
    assert saved.status_code == 200, saved.json
    assert saved.headers["Cache-Control"] == "no-store"


def test_withdrawal_removes_evidence(setup):
    app = setup
    client, headers, _user_id = real_member(app, "9876543210")
    application = save_application(client, headers)
    application = upload(client, headers, kind="identity_document", version=application["version"])
    assert len(application["documents"]) == 1
    withdrawn = client.post("/api/withdraw_identity_application", json={
        "expected_version": application["version"]}, headers=headers)
    assert withdrawn.status_code == 200, withdrawn.json
    assert withdrawn.json["application"]["status"] == "withdrawn"
    assert withdrawn.json["application"]["document_consent"] is False
    assert withdrawn.json["application"]["documents"] == []
    with app.extensions["beta_store"].read() as tx:
        assert tx.get(APPLICATIONS, application["id"])["status"] == "withdrawn"
        assert tx.list(DOCUMENTS) == []
        assert tx.list(DECISIONS) == []
        assert tx._connection.execute("SELECT count(*) FROM identity_document_blobs").fetchone()[0] == 0


def test_account_deletion_purges_identity_evidence_and_audits(setup):
    app = setup
    client, headers, user_id = real_member(app, "9876543210")
    application = save_application(client, headers)
    application = upload(client, headers, kind="identity_document", version=application["version"])
    application = upload(client, headers, kind="selfie", version=application["version"])
    application = client.post("/api/submit_identity_application", json={
        "expected_version": application["version"]}, headers=headers).json["application"]
    reviewer, reviewer_headers, _reviewer_id = make_reviewer(app)
    for document in application["documents"]:
        assert reviewer.get(f"/api/identity_document_preview?document_id={document['id']}",
                            headers=reviewer_headers).status_code == 200
    with app.extensions["beta_store"].read() as tx:
        assert len(tx.list(DOCUMENT_ACCESS)) == 2

    app.extensions["identity_test_clock"][0] += 61
    action_token = account_reauth(client, headers, "delete")
    response = client.post("/api/account/delete", json={
        "action_token": action_token, "confirm": True, "idempotency_key": str(uuid.uuid4()),
    }, headers=headers)
    assert response.status_code == 200, response.json
    with app.extensions["beta_store"].read() as tx:
        deleted = tx.get("users", user_id)
        assert deleted["account_status"] == "deleted"
        assert "identity_approval" not in deleted and "verification" not in deleted
        assert "Private Identity Applicant" not in json.dumps(deleted)
        assert tx.list(APPLICATIONS) == []
        assert tx.list(DOCUMENTS) == []
        assert tx.list(DOCUMENT_ACCESS) == []
        assert tx.list(DECISIONS) == []
        assert tx._connection.execute("SELECT count(*) FROM identity_document_blobs").fetchone()[0] == 0


def test_missing_key_fails_closed(setup):
    app = setup
    client, headers, _user_id = real_member(app, "9876543210")
    app.extensions["identity_verification_service"]._cipher = None
    response = client.get("/api/identity_application", headers=headers)
    assert response.status_code == 200 and response.json["requirements"]["available"] is False
    unavailable = client.post("/api/identity_application", json={
        "legal_name": "No key applicant", "document_type": "voter_id",
        "adult_attested": True, "document_consent": True, "expected_version": 0,
    }, headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json["code"] == "identity_unavailable"
