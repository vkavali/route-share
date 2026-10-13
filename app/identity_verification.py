"""Private, encrypted manual identity review; never government authentication.

Evidence is logically deleted from the primary store after 30 days. Backup and
SQLite WAL retention require an operator policy; deletion is not a secure erase.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import review_progress
from .auth import current_actor_matches
from .document_preview import PreviewError, page_number, render_preview, inspection_complete
from .permissions import access_summary
from .driver_verification import (
    DriverVerificationError, MAX_DOCUMENT_BYTES, _content_type, _expiry,
    _read_content, _text, _version,
)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # No plaintext fallback when the deployment is incomplete.
    Fernet = None
    InvalidToken = ValueError

UTC = timezone.utc
APPLICATIONS = "identity_applications"
DOCUMENTS = "identity_documents"
DECISIONS = "identity_review_decisions"
DOCUMENT_ACCESS = "identity_document_access"
KINDS = ("identity_document", "selfie")
DOCUMENT_TYPES = ("driving_licence", "passport", "voter_id")
CHECKS = {"document_readable", "name_matches", "photo_matches", "adult_confirmed"}
REQUIREMENTS = {
    "review_scope": "human_document_review", "document_types": list(DOCUMENT_TYPES),
    "kinds": list(KINDS), "document_kinds": list(KINDS),
    "expiry_required": ["driving_licence", "passport"],
    "max_document_bytes": MAX_DOCUMENT_BYTES, "retention_days": 30,
    "max_approval_days": 365,
    "content_types": ["image/png", "image/jpeg", "application/pdf"],
    "selfie_content_types": ["image/png", "image/jpeg"],
    "notice": "Private human review only; not government authentication, liveness or police verification. Do not upload Aadhaar or PAN.",
}


class IdentityVerificationError(Exception):
    def __init__(self, message, status=400, code="identity_invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def _error(message, status=400, code="identity_invalid"):
    raise IdentityVerificationError(message, status, code)


def _validate(fn, *args):
    try:
        return fn(*args)
    except DriverVerificationError as exc:
        raise IdentityVerificationError(str(exc), exc.status, exc.code) from exc


def _delete_document(tx, document_id):
    doc = tx.get(DOCUMENTS, document_id)
    if doc:
        review_progress.discard_application(tx, "identity", doc["application_id"])
    tx._connection.execute("DELETE FROM identity_document_blobs WHERE id = ?", (document_id,))
    tx.delete(DOCUMENTS, document_id)
    # Keep reviewer access audit until account deletion; it contains IDs, not evidence.


def delete_user_evidence(tx, user_id):
    """Account-deletion hook. Caller owns the transaction and user removal."""
    review_progress.discard_user(tx, user_id)
    app_ids = {a["id"] for a in tx.list(APPLICATIONS) if a["user_id"] == user_id}
    for doc in tx.list(DOCUMENTS):
        if doc["user_id"] == user_id:
            _delete_document(tx, doc["id"])
    for collection in (DOCUMENT_ACCESS, DECISIONS):
        for row in tx.list(collection):
            if row.get("application_id") in app_ids or row.get("actor_id") == user_id:
                tx.delete(collection, row["id"])
    for app_id in app_ids:
        tx.delete(APPLICATIONS, app_id)


class IdentityVerificationService:
    def __init__(self, store, *, encryption_key=None, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self._cipher = None
        try:
            if Fernet is not None and encryption_key:
                self._cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        except (ValueError, TypeError):
            pass
        with store.transaction() as tx:
            tx._connection.execute("CREATE TABLE IF NOT EXISTS identity_document_blobs (id TEXT PRIMARY KEY, content BLOB NOT NULL)")
            tx._connection.execute("CREATE TABLE IF NOT EXISTS identity_encryption_config (id INTEGER PRIMARY KEY, token BLOB NOT NULL)")
            row = tx._connection.execute("SELECT token FROM identity_encryption_config WHERE id=1").fetchone()
            if self._cipher and row:
                try:
                    if self._cipher.decrypt(bytes(row[0])) != b"identity-evidence-key-v1":
                        self._cipher = None
                except InvalidToken:
                    self._cipher = None
            elif self._cipher:
                tx._connection.execute("INSERT INTO identity_encryption_config(id,token) VALUES (1,?)", (self._cipher.encrypt(b"identity-evidence-key-v1"),))

    @property
    def available(self):
        return self._cipher is not None

    def requirements(self):
        return {**REQUIREMENTS, "available": self.available}

    def _require_key(self):
        if not self.available:
            _error("Private identity review is unavailable until encryption is configured.", 503, "identity_unavailable")

    def _encrypt(self, text):
        self._require_key()
        return self._cipher.encrypt(text.encode()).decode()

    def _decrypt(self, token):
        if not token or not self.available:
            return None
        try:
            return self._cipher.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError, UnicodeError):
            _error("Private evidence cannot be decrypted.", 503, "identity_unavailable")

    @staticmethod
    def _actor(tx, user, *, reviewer=False, member=False):
        identity = user.get("id") if isinstance(user, dict) else None
        current = tx.get("users", identity) if isinstance(identity, str) else None
        if not current_actor_matches(current, user):
            _error("Authentication required.", 401, "identity_unauthenticated")
        if reviewer and "verify.review" not in access_summary(current)["staff_capabilities"]:
            _error("Identity review access is required.", 403, "identity_forbidden")
        if member and current.get("role") != "member":
            _error("Identity applications are for member accounts.", 403, "identity_forbidden")
        return current

    @contextmanager
    def _access(self, user, *, reviewer=False, member=False):
        with self.store.transaction() as tx:
            current = self._actor(tx, user, reviewer=reviewer, member=member)
            at = self.clock().astimezone(UTC)
            self._maintenance(tx, at)
            yield tx, current, at

    @staticmethod
    def _own(tx, user_id):
        return next((a for a in tx.list(APPLICATIONS) if a["user_id"] == user_id), None)

    @staticmethod
    def _expected(app, value):
        if _validate(_version, value) != (app["version"] if app else 0):
            _error("This application changed. Reload it before saving.", 409, "identity_version_conflict")

    @staticmethod
    def _documents(tx, app):
        return [d for d in tx.list(DOCUMENTS) if d["application_id"] == app["id"]]

    def _view(self, tx, app):
        if app is None:
            return None
        fields = ("id", "user_id", "version", "status", "document_type", "adult_attested", "document_consent", "approval_expires_at")
        result = {key: app.get(key) for key in fields}
        result["legal_name"] = self._decrypt(app.get("legal_name_encrypted"))
        result["decision_reason"] = self._decrypt(app.get("decision_reason_encrypted")) or ""
        if app.get("decision_reason_code") == "evidence_retention_elapsed":
            result["decision_reason"] = "Evidence was deleted after 30 days. Upload current evidence and submit again."
        result["documents"] = [{key: d.get(key) for key in ("id", "kind", "expires_on", "filename", "delete_after")}
                               for d in sorted(self._documents(tx, app), key=lambda d: d["kind"])]
        return result

    def _result(self, tx, app):
        return {"application": self._view(tx, app), "requirements": self.requirements()}

    @staticmethod
    def _invalidate_user(tx, user_id, state="not_checked", *, force=False):
        user = tx.get("users", user_id)
        if not user:
            return
        approval = user.get("identity_approval")
        if not force and isinstance(approval, dict) and approval.get("source") != "identity_application":
            return  # Independent identity evidence is not ours to invalidate.
        if isinstance(approval, dict):
            user["identity_approval"] = None
        verification = dict(user.get("verification") or {})
        driver = user.get("driver_approval")
        # Preserve independent driver-backed legacy identity state.
        if force or not (user.get("driver_approved") is True and isinstance(driver, dict) and driver.get("kind") == "reviewed"):
            verification["identity"] = "development" if not force and user.get("development") is True else state
        user["verification"] = verification
        tx.put("users", user_id, user)

    def _maintenance(self, tx, at):
        deleted = expired = reopened = 0
        for doc in tx.list(DOCUMENTS):
            if datetime.fromisoformat(doc["delete_after"]) <= at:
                _delete_document(tx, doc["id"])
                deleted += 1
        for app in tx.list(APPLICATIONS):
            # Retention must not leave a submission locked without reviewable evidence.
            # Use a nonpersonal reason code so recovery also works without a key.
            if app["status"] == "submitted" and {d["kind"] for d in self._documents(tx, app)} != set(KINDS):
                app.update(status="needs_changes", version=app["version"] + 1,
                           decision_reason_encrypted=None, decision_reason_code="evidence_retention_elapsed",
                           updated_at=at.isoformat())
                tx.put(APPLICATIONS, app["id"], app)
                review_progress.discard_application(tx, "identity", app["id"])
                reopened += 1
            if app["status"] == "approved" and datetime.fromisoformat(app["approval_expires_at"]) <= at:
                app.update(status="expired", version=app["version"] + 1)
                tx.put(APPLICATIONS, app["id"], app)
                review_progress.discard_application(tx, "identity", app["id"])
                self._invalidate_user(tx, app["user_id"], "expired")
                expired += 1
        return {"deleted_documents": deleted, "expired_applications": expired, "reopened_applications": reopened}

    def maintenance(self):
        with self.store.transaction() as tx:
            return self._maintenance(tx, self.clock().astimezone(UTC))

    def get_application(self, user):
        with self._access(user, member=True) as (tx, current, _at):
            return self._result(tx, self._own(tx, current["id"]))

    def save_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send an application object.")
        name = _validate(_text, payload.get("legal_name"), "Legal name", 120, 1)
        document_type = payload.get("document_type")
        if not isinstance(document_type, str) or document_type not in DOCUMENT_TYPES:
            _error("Choose driving licence, passport or voter ID. Aadhaar and PAN are not accepted.")
        for field in ("adult_attested", "document_consent"):
            if type(payload.get(field)) is not bool:
                _error(f"{field} must be a boolean.")
        with self._access(user, member=True) as (tx, current, at):
            self._require_key()
            app = self._own(tx, current["id"])
            self._expected(app, payload.get("expected_version"))
            if app and app["status"] == "submitted":
                _error("Withdraw the submission before editing.", 409, "identity_locked")
            if app is None:
                app = {"id": uuid.uuid4().hex, "user_id": current["id"], "version": 0, "created_at": at.isoformat()}
            if app.get("document_type") != document_type or not payload["document_consent"]:
                for doc in self._documents(tx, app):
                    _delete_document(tx, doc["id"])
            app.update(legal_name_encrypted=self._encrypt(name), document_type=document_type,
                       adult_attested=payload["adult_attested"], document_consent=payload["document_consent"],
                       status="draft", version=app["version"] + 1, updated_at=at.isoformat(), approval_expires_at=None)
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "identity", app["id"])
            self._invalidate_user(tx, current["id"])
            return self._result(tx, app)

    def upload_document(self, user, *, kind, expires_on, filename, content, expected_version):
        if not isinstance(kind, str) or kind not in KINDS:
            _error("Choose identity_document or selfie.")
        with self.store.read() as tx:
            self._actor(tx, user, member=True)
            self._require_key()
        raw = _validate(_read_content, content)
        media, extension = _validate(_content_type, raw, kind)
        with self._access(user, member=True) as (tx, current, at):
            self._require_key()
            app = self._own(tx, current["id"])
            if not app:
                _error("Save the application first.", 409)
            self._expected(app, expected_version)
            if app["status"] not in {"draft", "needs_changes", "rejected", "revoked", "expired"}:
                _error("Reopen the application before replacing documents.", 409, "identity_locked")
            if not app["document_consent"]:
                _error("Consent to private document review is required.", 409)
            requires_expiry = kind == "identity_document" and app["document_type"] in {"driving_licence", "passport"}
            expiry = _validate(_expiry, expires_on) if requires_expiry else None
            if not requires_expiry and expires_on not in (None, ""):
                _error("This evidence does not take an expiry date.")
            if expiry and expiry <= at:
                _error("Upload a document that has not expired.", 400, "document_expired")
            for old in self._documents(tx, app):
                if old["kind"] == kind:
                    _delete_document(tx, old["id"])
            identity = uuid.uuid4().hex
            tx._connection.execute("INSERT INTO identity_document_blobs(id,content) VALUES (?,?)", (identity, self._cipher.encrypt(raw)))
            tx.put(DOCUMENTS, identity, {"id": identity, "application_id": app["id"], "user_id": current["id"],
                   "kind": kind, "expires_on": expires_on or None, "filename": kind + extension, "content_type": media,
                   "uploaded_at": at.isoformat(), "delete_after": (at + timedelta(days=30)).isoformat()})
            app.update(status="draft", version=app["version"] + 1, updated_at=at.isoformat(), approval_expires_at=None)
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "identity", app["id"])
            self._invalidate_user(tx, current["id"])
            return self._result(tx, app)

    def _ready(self, tx, app, at):
        legal_name = self._decrypt(app.get("legal_name_encrypted"))
        if not isinstance(legal_name, str) or not legal_name.strip():
            _error("Private identity details are unavailable. Save the application again.", 503, "identity_unavailable")
        if not all(app.get(f) is True for f in ("adult_attested", "document_consent")):
            _error("Confirm the adult and private review declarations.", 409, "identity_incomplete")
        docs = {d["kind"]: d for d in self._documents(tx, app)}
        if set(docs) != set(KINDS):
            _error("Upload a current identity document and selfie.", 409, "identity_incomplete")
        for doc in docs.values():
            row = tx._connection.execute("SELECT content FROM identity_document_blobs WHERE id=?", (doc["id"],)).fetchone()
            if datetime.fromisoformat(doc["delete_after"]) <= at or not row:
                _error("Replace deleted evidence before submitting or approving.", 409, "identity_incomplete")
            # A previous view is insufficient if stored evidence became corrupt.
            # Authenticate the current ciphertext before accepting either transition.
            try:
                self._cipher.decrypt(bytes(row[0]))
            except InvalidToken:
                _error("Private evidence cannot be decrypted. Replace the affected upload.", 503, "identity_unavailable")
        expiry = at + timedelta(days=365)
        if app["document_type"] in {"driving_licence", "passport"}:
            doc_expiry = _validate(_expiry, docs["identity_document"]["expires_on"])
            if doc_expiry <= at:
                _error("Replace the expired identity document.", 409, "document_expired")
            expiry = min(expiry, doc_expiry)
        return docs, expiry

    def submit_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send an application object.")
        with self._access(user, member=True) as (tx, current, at):
            self._require_key()
            app = self._own(tx, current["id"])
            if not app:
                _error("Save the application first.", 409)
            self._expected(app, payload.get("expected_version"))
            if app["status"] != "draft":
                _error("Only a draft application can be submitted.", 409, "identity_locked")
            self._ready(tx, app, at)
            app.update(status="submitted", version=app["version"] + 1, submitted_at=at.isoformat())
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "identity", app["id"])
            self._invalidate_user(tx, current["id"], "pending")
            return self._result(tx, app)

    def withdraw_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send an application object.")
        with self._access(user, member=True) as (tx, current, at):
            app = self._own(tx, current["id"])
            if not app:
                _error("Application not found.", 404)
            self._expected(app, payload.get("expected_version"))
            for doc in self._documents(tx, app):
                _delete_document(tx, doc["id"])
            app.update(status="withdrawn", document_consent=False, legal_name_encrypted=None,
                       decision_reason_encrypted=None, decision_reason_code=None, approval_expires_at=None,
                       version=app["version"] + 1, updated_at=at.isoformat())
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "identity", app["id"])
            self._invalidate_user(tx, current["id"])
            return self._result(tx, app)

    def verification_queue(self, user):
        with self._access(user, reviewer=True) as (tx, _current, _at):
            return {"applications": [self._view(tx, a) for a in sorted(tx.list(APPLICATIONS), key=lambda a: a["created_at"])
                                     if a["status"] not in {"draft", "withdrawn"}], "requirements": self.requirements()}

    def review_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send a review object.")
        app_id = _validate(_text, payload.get("application_id"), "Application identifier", 64, 1)
        decision = payload.get("decision")
        if not isinstance(decision, str) or decision not in {"approved", "needs_changes", "rejected", "revoked"}:
            _error("Choose approval, changes request, rejection or revocation.")
        reason = _validate(_text, payload.get("reason"), "Decision reason", 1000, 10)
        checks = payload.get("checks")
        if not isinstance(checks, dict) or set(checks) != CHECKS or any(type(v) is not bool for v in checks.values()):
            _error("Supply explicit document_readable, name_matches, photo_matches and adult_confirmed booleans.")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            _error("A valid idempotency key is required.")
        expected = _validate(_version, payload.get("expected_version"))
        canonical = dict(application_id=app_id, decision=decision, reason=reason, checks=checks, expected_version=expected)
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        with self._access(user, reviewer=True) as (tx, current, at):
            self._require_key()
            app = tx.get(APPLICATIONS, app_id)
            if not app:
                _error("Application not found.", 404)
            if app["user_id"] == current["id"]:
                _error("You cannot review your own application.", 403, "identity_self_review")
            event_id = hashlib.sha256((current["id"] + ":" + key).encode()).hexdigest()
            prior = tx.get(DECISIONS, event_id)
            if prior:
                if prior["payload_sha256"] != digest:
                    _error("This review key was used for different details.", 409, "identity_idempotency_conflict")
                return self._result(tx, app)
            self._expected(app, expected)
            if app["status"] != ("approved" if decision == "revoked" else "submitted"):
                _error("This application cannot receive that decision in its current state.", 409, "identity_locked")
            target = tx.get("users", app["user_id"])
            if not target or target.get("role") != "member" or not current_actor_matches(target, target):
                _error("The applicant is no longer an active member.", 409)
            checklist_snapshot = None
            expiry_at = None
            reviewed_docs = []
            if decision == "approved":
                if not all(checks.values()):
                    _error("Confirm every identity review check.", 409, "identity_incomplete")
                docs, expiry = self._ready(tx, app, at)
                if not inspection_complete(tx.list(DOCUMENT_ACCESS), current["id"], app, docs.values()):
                    _error("View every page of each current document before approving.", 409, "identity_documents_unread")
                checklist_snapshot = review_progress.approval_snapshot(tx, "identity", current, app, docs, _error)
                reviewed_docs = sorted(d["id"] for d in docs.values())
                expiry_at = expiry.isoformat()
                verification = dict(target.get("verification") or {})
                development = target.get("development") is True
                verification["identity"] = "development" if development else "verified"
                target.update(identity_approval={"kind": "development" if development else "human_document_review",
                              "source": "identity_application", "application_id": app_id, "expires_at": expiry_at,
                              "reviewed_at": at.isoformat()}, verification=verification)
                tx.put("users", target["id"], target)
            else:
                self._invalidate_user(tx, target["id"], "rejected" if decision in {"rejected", "revoked"} else "pending",
                                      force=decision in {"rejected", "revoked"})
            encrypted_reason = self._encrypt(reason)
            app.update(status=decision, version=app["version"] + 1, decision_reason_encrypted=encrypted_reason, decision_reason_code=None,
                       approval_expires_at=expiry_at, reviewed_at=at.isoformat())
            tx.put(APPLICATIONS, app_id, app)
            review_progress.discard_application(tx, "identity", app["id"])
            tx.put(DECISIONS, event_id, {"id": event_id, "actor_id": current["id"], "application_id": app_id,
                   "decision": decision, "reason_encrypted": encrypted_reason, "checks": checks, "at": at.isoformat(),
                   "document_ids": reviewed_docs, "payload_sha256": digest, "result_version": app["version"], "review_checklist": checklist_snapshot})
            return self._result(tx, app)

    def get_review_progress(self, user, application_id):
        with self._access(user, reviewer=True) as (tx, current, _at):
            app, docs = review_progress.application(tx, "identity", current, application_id, _error)
            return review_progress.get(tx, "identity", current, app, docs)

    def save_review_progress(self, user, payload):
        review_progress.validate(payload, "identity", _error)
        with self._access(user, reviewer=True) as (tx, current, at):
            app, docs = review_progress.application(tx, "identity", current, payload["application_id"], _error,
                                                   expected=payload["expected_version"])
            return review_progress.save(tx, "identity", current, app, docs, payload, at, _error)

    def get_document(self, user, document_id):
        if not isinstance(document_id, str) or not re.fullmatch(r"[a-f0-9]{32}", document_id):
            _error("Document not found.", 404)
        with self._access(user) as (tx, current, at):
            doc = tx.get(DOCUMENTS, document_id)
            if not doc or doc["user_id"] != current["id"]:
                _error("Document not found.", 404)
            self._require_key()
            row = tx._connection.execute("SELECT content FROM identity_document_blobs WHERE id=?", (document_id,)).fetchone()
            if not row:
                _error("Document not found.", 404)
            try:
                raw = self._cipher.decrypt(bytes(row[0]))
            except InvalidToken:
                _error("Private evidence cannot be decrypted.", 503, "identity_unavailable")
            return {"content": raw, "content_type": doc["content_type"], "filename": doc["filename"]}


    def _preview_record(self, tx, current, document_id):
        doc = tx.get(DOCUMENTS, document_id)
        app = tx.get(APPLICATIONS, doc["application_id"]) if doc else None
        target = tx.get("users", app["user_id"]) if app else None
        if (not doc or not app or not target or not current_actor_matches(target, target)
                or not app.get("document_consent")
                or app.get("status") not in {"submitted", "approved", "needs_changes", "rejected"}
                or doc["user_id"] != app["user_id"]):
            _error("Document not found.", 404)
        if app["user_id"] == current["id"]:
            _error("You cannot inspect your own application as a reviewer.", 403, "identity_self_review")
        return doc, app

    def get_document_preview(self, user, document_id, page=1):
        if not isinstance(document_id, str) or not re.fullmatch(r"[a-f0-9]{32}", document_id):
            _error("Document not found.", 404)
        try:
            page = page_number(page)
        except PreviewError as exc:
            _error(str(exc), exc.status, exc.code)
        with self._access(user, reviewer=True) as (tx, current, at):
            doc, app = self._preview_record(tx, current, document_id)
            row = tx._connection.execute("SELECT content FROM identity_document_blobs WHERE id=?", (document_id,)).fetchone()
            if not row:
                _error("Document not found.", 404)
            self._require_key()
            try:
                raw = self._cipher.decrypt(bytes(row[0]))
            except InvalidToken:
                _error("Private evidence cannot be decrypted.", 503, "identity_unavailable")
            version, app_id = app["version"], app["id"]
            stored_digest = hashlib.sha256(bytes(row[0])).digest()
        # Do not hold a SQLite writer lock during native decoding. Re-authorize
        # and recheck the evidence/version before releasing pixels or a receipt.
        try:
            result = render_preview(raw, doc["content_type"], page, current["id"], at)
        except PreviewError as exc:
            _error(str(exc), exc.status, exc.code)
        with self._access(user, reviewer=True) as (tx, current, at):
            doc, app = self._preview_record(tx, current, document_id)
            row = tx._connection.execute("SELECT content FROM identity_document_blobs WHERE id=?", (document_id,)).fetchone()
            if (app["id"] != app_id or app["version"] != version or not row
                    or hashlib.sha256(bytes(row[0])).digest() != stored_digest):
                _error("This application changed. Reload it before inspection.", 409, "document_preview_stale")
            receipt_id = hashlib.sha256(f"{current['id']}:{document_id}:{version}:{page}".encode()).hexdigest()
            tx.put(DOCUMENT_ACCESS, receipt_id, {"id": receipt_id, "actor_id": current["id"],
                   "document_id": document_id, "application_id": app_id, "application_version": version,
                   "page": page, "page_count": result["page_count"], "mode": "watermarked_preview", "at": at.isoformat()})
            return result
