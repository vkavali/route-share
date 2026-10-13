"""Private driver applications and bounded human document review, not government checks.

Evidence is Fernet-encrypted in the same SQLite transaction as private metadata.
Only status summaries and expiry metadata are written to users. Maintenance deletes
logical primary-store evidence; backup/WAL retention remains an operational duty.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # Never fall back to plaintext if the deployment is incomplete.
    Fernet = None
    InvalidToken = ValueError

from .permissions import has_current_identity_review, has_verified_phone, access_summary
from . import review_progress
from .auth import current_actor_matches
from .document_preview import PreviewError, page_number, render_preview, inspection_complete

MAX_DOCUMENT_BYTES = 3 * 1024 * 1024
APPLICATIONS = "driver_applications"
DOCUMENTS = "driver_documents"
DECISIONS = "driver_review_decisions"
DOCUMENT_ACCESS = "driver_document_access"
KINDS = ("dl", "rc", "insurance", "selfie")
EXPIRING_KINDS = ("dl", "rc", "insurance")
REQUIREMENTS = {
    "document_kinds": list(KINDS), "expiry_required": list(EXPIRING_KINDS),
    "max_document_bytes": MAX_DOCUMENT_BYTES,
    "content_types": ["image/png", "image/jpeg", "application/pdf"],
    "selfie_content_types": ["image/png", "image/jpeg"],
    "review_scope": "Human review of supplied evidence only; not government or police verification.",
}
UTC = timezone.utc
KEY_GUARD = b"driver-evidence-key-v1"


class DriverVerificationError(Exception):
    def __init__(self, message, status=400, code="verification_invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def _error(message, status=400, code="verification_invalid"):
    raise DriverVerificationError(message, status, code)


def _text(value, label, maximum, minimum=0):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        _error(f"{label} must contain {minimum} to {maximum} characters.")
    return value.strip()


def _expiry(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _error("Enter an expiry date as YYYY-MM-DD.")
    try:
        day = date.fromisoformat(value)
        expiry = datetime.combine(day + timedelta(days=1), time.min, UTC)
        expiry + timedelta(days=30)  # Retention deadline must be representable too.
        return expiry
    except (ValueError, OverflowError):
        _error("Enter a valid expiry date.")


def _version(value):
    if type(value) is not int or value < 0:
        _error("A nonnegative expected_version integer is required.")
    return value


def _read_content(content):
    if isinstance(content, bytes):
        raw = content
    elif callable(getattr(content, "read", None)):
        # Never read an unbounded upload, including a stream returning short reads.
        chunks, size = [], 0
        while size <= MAX_DOCUMENT_BYTES:
            chunk = content.read(min(65536, MAX_DOCUMENT_BYTES + 1 - size))
            if not isinstance(chunk, bytes):
                _error("Upload a binary document.")
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
    else:
        _error("Upload a document file.")
    if not raw or len(raw) > MAX_DOCUMENT_BYTES:
        _error("Documents must be nonempty and at most 3 MiB.", 413, "document_too_large")
    return raw


def _content_type(raw, kind):
    # Signature and minimal envelope validation, not malware scanning or OCR.
    if (raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 45
            and raw[8:16] == b"\x00\x00\x00\rIHDR"
            and all(struct.unpack(">II", raw[16:24]))
            and raw.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")):
        return "image/png", ".png"
    if raw.startswith(b"\xff\xd8\xff") and len(raw) >= 12 and raw.endswith(b"\xff\xd9"):
        return "image/jpeg", ".jpg"
    if kind != "selfie" and re.match(br"%PDF-(?:1\.[0-7]|2\.0)(?:\s)", raw) and b"%%EOF" in raw[-1024:]:
        return "application/pdf", ".pdf"
    _error("Use a PNG or JPEG image, or a PDF for documents other than the selfie.", 400, "document_type_invalid")


def _unavailable():
    _error("Private driver evidence is unavailable. Contact support before continuing.", 503, "verification_evidence_unavailable")


def _cipher_for(key):
    try:
        return Fernet(key.encode() if isinstance(key, str) else key) if Fernet is not None and key else None
    except (ValueError, TypeError, UnicodeError):
        return None


def _validate_guard(connection, cipher, *, allow_create=False):
    # The configured key is shared with identity evidence, but its driver binding is distinct.
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, expected in (("identity_encryption_config", b"identity-evidence-key-v1"),
                            ("driver_encryption_config", KEY_GUARD)):
        row = connection.execute(f"SELECT token FROM {table} WHERE id=1").fetchone() if table in tables else None
        if row:
            try:
                if cipher.decrypt(bytes(row[0])) != expected:
                    _unavailable()
            except (InvalidToken, ValueError, TypeError):
                _unavailable()
        elif table == "driver_encryption_config":
            if not allow_create:
                _unavailable()
            columns = {r[1] for r in connection.execute("PRAGMA table_info(driver_document_blobs)")}
            if "encoding" in columns and connection.execute("SELECT 1 FROM driver_document_blobs WHERE encoding!=0 LIMIT 1").fetchone():
                _unavailable()  # A missing guard is not permission to replace a lost binding.
            connection.execute("CREATE TABLE IF NOT EXISTS driver_encryption_config (id INTEGER PRIMARY KEY, token BLOB NOT NULL)")
            connection.execute("INSERT INTO driver_encryption_config(id,token) VALUES (1,?)", (cipher.encrypt(KEY_GUARD),))


def _check_plaintext(raw, doc):
    if (not raw or len(raw) > MAX_DOCUMENT_BYTES or len(raw) != doc.get("bytes")
            or hashlib.sha256(raw).hexdigest() != doc.get("sha256")):
        _unavailable()
    try:
        media, _ = _content_type(raw, doc.get("kind"))
    except DriverVerificationError:
        _unavailable()
    if media != doc.get("content_type"):
        _unavailable()


class DriverVerificationService:
    def __init__(self, store, *, encryption_key=None, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self._cipher = _cipher_for(encryption_key)
        with store.transaction() as tx:
            connection = tx._connection
            connection.execute("""CREATE TABLE IF NOT EXISTS driver_document_blobs
                (id TEXT PRIMARY KEY, content BLOB NOT NULL, encoding INTEGER NOT NULL DEFAULT 0)""")
            if "encoding" not in {row[1] for row in connection.execute("PRAGMA table_info(driver_document_blobs)")}:
                connection.execute("ALTER TABLE driver_document_blobs ADD COLUMN encoding INTEGER NOT NULL DEFAULT 0")
            connection.execute("CREATE TABLE IF NOT EXISTS driver_encryption_config (id INTEGER PRIMARY KEY, token BLOB NOT NULL)")
            if self._cipher:
                try:
                    _validate_guard(connection, self._cipher, allow_create=True)
                except DriverVerificationError:
                    self._cipher = None

    @property
    def available(self):
        return self._cipher is not None

    def _require_key(self, tx):
        if not self._cipher:
            _unavailable()
        _validate_guard(tx._connection, self._cipher)

    def _read_blob(self, tx, doc):
        self._require_key(tx)
        row = tx._connection.execute("SELECT content,encoding FROM driver_document_blobs WHERE id=?", (doc["id"],)).fetchone()
        if not row or row[1] != 1:
            _unavailable()
        try:
            raw = self._cipher.decrypt(bytes(row[0]))
        except (InvalidToken, ValueError, TypeError):
            _unavailable()
        _check_plaintext(raw, doc)
        return raw

    def _now(self):
        return self.clock().astimezone(UTC)

    @staticmethod
    def _actor(tx, user, *, reviewer=False, member=False):
        identity = user.get("id") if isinstance(user, dict) else None
        current = tx.get("users", identity) if isinstance(identity, str) else None
        if not current_actor_matches(current, user):
            _error("Authentication required.", 401, "verification_unauthenticated")
        if reviewer and "verify.review" not in access_summary(current)["staff_capabilities"]:
            _error("Document review access is required.", 403, "verification_forbidden")
        if member and current.get("role") != "member":
            _error("Driver applications are for member accounts.", 403, "verification_forbidden")
        return current

    @contextmanager
    def _access(self, user, *, reviewer=False, member=False):
        with self.store.transaction() as tx:
            current = self._actor(tx, user, reviewer=reviewer, member=member)
            at = self._now()
            self._maintenance(tx, at)
            yield tx, current, at

    @staticmethod
    def _own(tx, user_id):
        return next((a for a in tx.list(APPLICATIONS) if a["user_id"] == user_id), None)

    @staticmethod
    def _expected(application, value):
        if _version(value) != (application["version"] if application else 0):
            _error("This application changed. Reload it before saving.", 409, "verification_version_conflict")

    @staticmethod
    def _documents(tx, application):
        return [d for d in tx.list(DOCUMENTS) if d["application_id"] == application["id"]]

    def _view(self, tx, application):
        if application is None:
            return None
        fields = ("id", "user_id", "version", "status", "legal_name", "vehicle",
                  "adult_attested", "planned_trip_attested", "document_consent", "applicant_note",
                  "decision_reason", "approval_expires_at")
        result = {key: application.get(key) for key in fields}
        result["documents"] = [{key: d.get(key) for key in ("id", "kind", "expires_on", "filename")}
                               for d in sorted(self._documents(tx, application), key=lambda row: row["kind"])]
        return result

    def requirements(self):
        return {**REQUIREMENTS, "available": self.available}

    def _result(self, tx, application):
        return {"application": self._view(tx, application), "requirements": self.requirements()}

    @staticmethod
    def _invalidate_user(tx, user_id, state="not_checked"):
        user = tx.get("users", user_id)
        if user:
            verification = dict(user["verification"]) if isinstance(user.get("verification"), dict) else {}
            approval = user.get("identity_approval")
            independent = isinstance(approval, dict) and approval.get("source") == "identity_application"
            for kind in KINDS:
                verification[kind] = state
            if not independent:
                verification["identity"] = state
            if isinstance(approval, dict) and approval.get("source") == "driver_application":
                user["identity_approval"] = None
            user.update(driver_approved=False, driver_approval=None, verification=verification)
            tx.put("users", user_id, user)

    def _maintenance(self, tx, at):
        deleted = 0
        for doc in tx.list(DOCUMENTS):
            if datetime.fromisoformat(doc["delete_after"]) <= at:
                self._delete_document(tx, doc["id"])
                deleted += 1
        expired = reopened = 0
        for app in tx.list(APPLICATIONS):
            # Retention must not strand a submitted application without reviewable evidence.
            if app["status"] == "submitted" and {d["kind"] for d in self._documents(tx, app)} != set(KINDS):
                app.update(status="needs_changes", version=app["version"] + 1,
                           decision_reason="Some documents reached their retention limit. Upload the missing documents and submit again.",
                           updated_at=at.isoformat())
                tx.put(APPLICATIONS, app["id"], app)
                review_progress.discard_application(tx, "driver", app["id"])
                reopened += 1
            if app["status"] == "approved" and datetime.fromisoformat(app["approval_expires_at"]) <= at:
                app.update(status="expired", version=app["version"] + 1)
                tx.put(APPLICATIONS, app["id"], app)
                review_progress.discard_application(tx, "driver", app["id"])
                self._invalidate_user(tx, app["user_id"], "expired")
                expired += 1
        return {"deleted_documents": deleted, "expired_applications": expired, "reopened_applications": reopened}

    @staticmethod
    def _delete_document(tx, document_id):
        doc = tx.get(DOCUMENTS, document_id)
        if doc:
            review_progress.discard_application(tx, "driver", doc["application_id"])
        tx._connection.execute("DELETE FROM driver_document_blobs WHERE id = ?", (document_id,))
        tx.delete(DOCUMENTS, document_id)
        for access in tx.list(DOCUMENT_ACCESS):
            if access["document_id"] == document_id:
                tx.delete(DOCUMENT_ACCESS, access["id"])

    def maintenance(self):
        """Callable by a scheduled operator task; also runs on authenticated service access."""
        with self.store.transaction() as tx:
            return self._maintenance(tx, self._now())

    def get_application(self, user):
        with self._access(user, member=True) as (tx, current, _at):
            return self._result(tx, self._own(tx, current["id"]))

    def save_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send an application object.")
        name = _text(payload.get("legal_name"), "Legal name", 120, 1)
        vehicle = payload.get("vehicle")
        if not isinstance(vehicle, dict):
            _error("Vehicle details are required.")
        vehicle = {"model": _text(vehicle.get("model"), "Vehicle model", 100, 1),
                   "plate": _text(vehicle.get("plate"), "Vehicle registration", 30, 1).upper()}
        for field in ("adult_attested", "planned_trip_attested", "document_consent"):
            if type(payload.get(field)) is not bool:
                _error(f"{field} must be a boolean.")
        note = _text(payload.get("applicant_note", ""), "Applicant note", 1000)
        with self._access(user, member=True) as (tx, current, at):
            app = self._own(tx, current["id"])
            self._expected(app, payload.get("expected_version"))
            if app and app["status"] == "submitted" and payload["document_consent"] is not False:
                _error("The submitted application is awaiting review.", 409, "verification_locked")
            if app is None:
                app = {"id": uuid.uuid4().hex, "user_id": current["id"], "version": 0,
                       "created_at": at.isoformat(), "decision_reason": ""}
            app.update(legal_name=name, vehicle=vehicle, status="draft", applicant_note=note,
                       adult_attested=payload["adult_attested"], planned_trip_attested=payload["planned_trip_attested"],
                       document_consent=payload["document_consent"], approval_expires_at=None,
                       version=app["version"] + 1, updated_at=at.isoformat())
            # Withdrawing evidence consent removes its primary-store copies immediately.
            if not app["document_consent"]:
                for doc in self._documents(tx, app):
                    self._delete_document(tx, doc["id"])
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "driver", app["id"])
            self._invalidate_user(tx, current["id"])
            return self._result(tx, app)

    def upload_document(self, user, *, kind, expires_on, filename, content, expected_version):
        if kind not in KINDS:
            _error("Choose dl, rc, insurance or selfie.")
        # Reject unauthorized actors before reading the stream. Recheck under write transaction.
        with self.store.read() as tx:
            self._actor(tx, user, member=True)
            self._require_key(tx)
        raw = _read_content(content)
        media, extension = _content_type(raw, kind)
        name = filename if isinstance(filename, str) else "document"
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:110].strip(" .") or "document"
        # A safe extension reflects the detected content, never an executable original suffix.
        name = name.rsplit(".", 1)[0] + extension
        expiry = _expiry(expires_on) if kind in EXPIRING_KINDS else None
        if kind == "selfie" and expires_on not in (None, ""):
            _error("Selfie expiry is assigned by the review, not the applicant.")
        with self._access(user, member=True) as (tx, current, at):
            app = self._own(tx, current["id"])
            if not app:
                _error("Save the application first.", 409)
            self._expected(app, expected_version)
            if app["status"] not in {"draft", "needs_changes", "rejected", "revoked", "expired"}:
                _error("Reopen the application before replacing documents.", 409, "verification_locked")
            if not app["document_consent"]:
                _error("Consent to private document review is required.", 409)
            if expiry and expiry <= at:
                _error("Upload a document that has not expired.", 400, "document_expired")
            self._require_key(tx)
            encrypted = self._cipher.encrypt(raw)
            # Selfie retention is initially bounded to 30 days from upload, then tied
            # to the earliest reviewed document expiry on approval.
            delete_after = (expiry or at) + timedelta(days=30)
            for old in self._documents(tx, app):
                if old["kind"] == kind:
                    self._delete_document(tx, old["id"])
            identity = uuid.uuid4().hex
            tx._connection.execute("INSERT INTO driver_document_blobs(id,content,encoding) VALUES (?,?,1)", (identity, encrypted))
            tx.put(DOCUMENTS, identity, {"id": identity, "application_id": app["id"], "user_id": current["id"],
                   "kind": kind, "expires_on": expires_on or None, "filename": name, "content_type": media,
                   "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                   "uploaded_at": at.isoformat(), "delete_after": delete_after.isoformat()})
            app.update(status="draft", version=app["version"] + 1, updated_at=at.isoformat(), approval_expires_at=None)
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "driver", app["id"])
            self._invalidate_user(tx, current["id"])
            return self._result(tx, app)

    def _ready(self, tx, app, at):
        self._require_key(tx)
        if not all(app.get(f) is True for f in ("adult_attested", "planned_trip_attested", "document_consent")):
            _error("Confirm the adult, planned-trip and document-review declarations.", 409, "verification_incomplete")
        docs = {d["kind"]: d for d in self._documents(tx, app)}
        if set(docs) != set(KINDS):
            _error("Upload licence, RC, insurance and selfie evidence.", 409, "verification_incomplete")
        expiries = {kind: _expiry(docs[kind]["expires_on"]) for kind in EXPIRING_KINDS}
        if any(expiry <= at for expiry in expiries.values()):
            _error("Replace expired documents before submitting or approving.", 409, "document_expired")
        for doc in docs.values():
            self._read_blob(tx, doc)
        return docs, expiries

    def submit_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send an application object.")
        with self._access(user, member=True) as (tx, current, at):
            app = self._own(tx, current["id"])
            if not app:
                _error("Save the application first.", 409)
            self._expected(app, payload.get("expected_version"))
            if app["status"] != "draft":
                _error("Only a draft application can be submitted.", 409, "verification_locked")
            self._ready(tx, app, at)
            app.update(status="submitted", version=app["version"] + 1, submitted_at=at.isoformat())
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "driver", app["id"])
            self._invalidate_user(tx, current["id"], "pending")
            return self._result(tx, app)

    def verification_queue(self, user):
        with self._access(user, reviewer=True) as (tx, _current, _at):
            return {"applications": [self._view(tx, a) for a in sorted(tx.list(APPLICATIONS), key=lambda a: a["created_at"])
                                     if a["status"] in {"submitted", "approved", "needs_changes", "rejected", "revoked", "expired"}]}

    def review_application(self, user, payload):
        if not isinstance(payload, dict):
            _error("Send a review object.")
        app_id = _text(payload.get("application_id"), "Application identifier", 64, 1)
        decision = payload.get("decision")
        if not isinstance(decision, str) or decision not in {"approved", "needs_changes", "rejected", "revoked"}:
            _error("Choose an approval, changes request, rejection or revocation.")
        reason = _text(payload.get("reason"), "Decision reason", 1000, 10)
        checks = payload.get("checks")
        fields = {"dl", "rc", "insurance", "identity_match"}
        if not isinstance(checks, dict) or set(checks) != fields or any(type(v) is not bool for v in checks.values()):
            _error("Supply explicit boolean dl, rc, insurance and identity_match checks.")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            _error("A valid idempotency key is required.")
        expected = _version(payload.get("expected_version"))
        canonical = {"application_id": app_id, "decision": decision, "reason": reason,
                     "checks": checks, "expected_version": expected}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        with self._access(user, reviewer=True) as (tx, current, at):
            app = tx.get(APPLICATIONS, app_id)
            if not app:
                _error("Application not found.", 404)
            if app["user_id"] == current["id"]:
                _error("You cannot review your own application.", 403, "verification_self_review")
            event_id = hashlib.sha256((current["id"] + ":" + key).encode()).hexdigest()
            prior = tx.get(DECISIONS, event_id)
            if prior:
                if prior["payload_sha256"] != digest:
                    _error("This review key was already used for different details.", 409, "verification_idempotency_conflict")
                return self._result(tx, app)
            self._expected(app, expected)
            if decision == "revoked":
                if app["status"] != "approved":
                    _error("Only an approved application can be revoked.", 409)
            elif app["status"] != "submitted":
                _error("Only a submitted application can be reviewed.", 409, "verification_locked")
            target = tx.get("users", app["user_id"])
            if not target or target.get("role") != "member" or not current_actor_matches(target, target):
                _error("The applicant is no longer an active member.", 409)
            checklist_snapshot = None
            expiry_at = None
            if decision == "approved":
                if target.get("development") is not True and not has_verified_phone(target):
                    _error("Verified phone sign-in is required before driver approval.", 409, "verified_phone_required")
                if not all(checks.values()):
                    _error("All document and identity-match checks must be confirmed.", 409, "verification_incomplete")
                docs, expiries = self._ready(tx, app, at)
                if not inspection_complete(tx.list(DOCUMENT_ACCESS), current["id"], app, docs.values()):
                    _error("View every page of each current document before approving.", 409, "verification_documents_unread")
                checklist_snapshot = review_progress.approval_snapshot(tx, "driver", current, app, docs, _error)
                expiry_at = min(expiries.values()).isoformat()
                selfie = docs["selfie"]
                selfie["delete_after"] = (min(expiries.values()) + timedelta(days=30)).isoformat()
                tx.put(DOCUMENTS, selfie["id"], selfie)
                verification = dict(target["verification"]) if isinstance(target.get("verification"), dict) else {}
                for kind in (*KINDS, "identity"):
                    verification[kind] = "verified"
                target.update(driver_approved=True, driver_approval={"kind": "development" if target.get("development") is True else "reviewed", "expires_at": expiry_at,
                              "document_expiries": {kind: value.isoformat() for kind, value in expiries.items()},
                              "review_scope": "human_document_review"}, verification=verification, vehicle=app["vehicle"])
                previous_identity = target.get("identity_approval")
                previous_identity = previous_identity if isinstance(previous_identity, dict) else {}
                if not (previous_identity.get("source") == "identity_application" and has_current_identity_review(target, at)):
                    identity_expiry = min(at + timedelta(days=365), expiries["dl"])
                    target["identity_approval"] = {"kind": "development" if target.get("development") is True else "human_document_review",
                        "source": "driver_application", "application_id": app_id,
                        "reviewed_at": at.isoformat(), "expires_at": identity_expiry.isoformat()}
                # Preserve development identity: reviewing a fixture is still a fixture.
                tx.put("users", target["id"], target)
            else:
                self._invalidate_user(tx, target["id"], "rejected" if decision in {"rejected", "revoked"} else "pending")
            app.update(status=decision, version=app["version"] + 1, decision_reason=reason,
                       approval_expires_at=expiry_at, reviewed_at=at.isoformat())
            tx.put(APPLICATIONS, app["id"], app)
            review_progress.discard_application(tx, "driver", app["id"])
            # Private audit record: no reviewer reason or document data in general ops events.
            tx.put(DECISIONS, event_id, {"id": event_id, "actor_id": current["id"], "application_id": app_id,
                   "decision": decision, "reason": reason, "checks": checks, "at": at.isoformat(),
                   "payload_sha256": digest, "result_version": app["version"], "review_checklist": checklist_snapshot})
            return self._result(tx, app)

    def get_review_progress(self, user, application_id):
        with self._access(user, reviewer=True) as (tx, current, _at):
            app, docs = review_progress.application(tx, "driver", current, application_id, _error)
            return review_progress.get(tx, "driver", current, app, docs)

    def save_review_progress(self, user, payload):
        review_progress.validate(payload, "driver", _error)
        with self._access(user, reviewer=True) as (tx, current, at):
            app, docs = review_progress.application(tx, "driver", current, payload["application_id"], _error,
                                                   expected=payload["expected_version"])
            return review_progress.save(tx, "driver", current, app, docs, payload, at, _error)

    def get_document(self, user, document_id):
        if not isinstance(document_id, str) or not re.fullmatch(r"[a-f0-9]{32}", document_id):
            _error("Document not found.", 404)
        with self._access(user) as (tx, current, at):
            doc = tx.get(DOCUMENTS, document_id)
            if not doc or doc["user_id"] != current["id"]:
                _error("Document not found.", 404)
            raw = self._read_blob(tx, doc)
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
            _error("You cannot inspect your own application as a reviewer.", 403, "verification_self_review")
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
            row = tx._connection.execute("SELECT content FROM driver_document_blobs WHERE id=?", (document_id,)).fetchone()
            if not row:
                _error("Document not found.", 404)
            raw = self._read_blob(tx, doc)
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
            self._require_key(tx)
            row = tx._connection.execute("SELECT content,encoding FROM driver_document_blobs WHERE id=?", (document_id,)).fetchone()
            if (app["id"] != app_id or app["version"] != version or not row
                    or row[1] != 1 or hashlib.sha256(bytes(row[0])).digest() != stored_digest):
                _error("This application changed. Reload it before inspection.", 409, "document_preview_stale")
            receipt_id = hashlib.sha256(f"{current['id']}:{document_id}:{version}:{page}".encode()).hexdigest()
            tx.put(DOCUMENT_ACCESS, receipt_id, {"id": receipt_id, "actor_id": current["id"],
                   "document_id": document_id, "application_id": app_id, "application_version": version,
                   "page": page, "page_count": result["page_count"], "mode": "watermarked_preview", "at": at.isoformat()})
            return result



def _stored_blob_rows(connection):
    # Stable IDs while migration updates only content/encoding; never materialize all BLOBs.
    cursor = connection.execute("SELECT id,content,encoding FROM driver_document_blobs ORDER BY id")
    try:
        while True:
            batch = cursor.fetchmany(1)
            if not batch:
                break
            yield batch[0]
    finally:
        cursor.close()


def migrate_legacy_evidence(database_path, *, encryption_key, offline=False):
    """Explicit offline conversion only; no runtime migration or key rotation.

    Caller must stop all application/worker access and keep a protected backup.
    A single SQLite transaction includes schema, guard and every BLOB conversion.
    """
    import sqlite3
    from pathlib import Path
    if offline is not True:
        raise ValueError("Stop all database users and explicitly confirm offline conversion.")
    cipher = _cipher_for(encryption_key)
    if cipher is None:
        _unavailable()
    path = Path(database_path).resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"driver_document_blobs", "documents"} <= tables:
            _unavailable()
        _validate_guard(connection, cipher, allow_create=True)
        columns = {r[1] for r in connection.execute("PRAGMA table_info(driver_document_blobs)")}
        if "encoding" not in columns:
            connection.execute("ALTER TABLE driver_document_blobs ADD COLUMN encoding INTEGER NOT NULL DEFAULT 0")
        converted = 0
        for document_id, content, encoding in _stored_blob_rows(connection):
            metadata = connection.execute("SELECT data FROM documents WHERE collection=? AND id=?", (DOCUMENTS, document_id)).fetchone()
            if not metadata:
                _unavailable()
            try:
                doc = json.loads(metadata[0])
                raw = bytes(content) if encoding == 0 else cipher.decrypt(bytes(content)) if encoding == 1 else None
            except (InvalidToken, ValueError, TypeError):
                _unavailable()
            if not isinstance(doc, dict) or doc.get("id") != document_id:
                _unavailable()
            _check_plaintext(raw, doc)
            if encoding == 0:
                connection.execute("UPDATE driver_document_blobs SET content=?,encoding=1 WHERE id=?", (cipher.encrypt(raw), document_id))
                converted += 1
        # Metadata without evidence is also corruption; never report a partial clean conversion.
        missing = connection.execute("""SELECT 1 FROM documents d LEFT JOIN driver_document_blobs b ON b.id=d.id
            WHERE d.collection=? AND b.id IS NULL LIMIT 1""", (DOCUMENTS,)).fetchone()
        if missing:
            _unavailable()
        connection.commit()
        return {"converted_documents": converted}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def audit_evidence_storage(database_path, *, encryption_key):
    """Read-only release gate. Return aggregate counts only, never evidence or IDs."""
    import sqlite3
    from pathlib import Path
    path = Path(database_path).resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
    result = {"legacy_documents": 0, "encrypted_documents": 0, "invalid_encoding_documents": 0, "ready": False}
    try:
        connection.execute("BEGIN")
        columns = {r[1] for r in connection.execute("PRAGMA table_info(driver_document_blobs)")}
        if not columns:
            return result
        if "encoding" in columns:
            counts = connection.execute("""SELECT
                COALESCE(SUM(CASE WHEN encoding=0 THEN 1 ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN encoding=1 THEN 1 ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN encoding IN (0,1) THEN 0 ELSE 1 END),0)
                FROM driver_document_blobs""").fetchone()
            result.update(zip(("legacy_documents", "encrypted_documents", "invalid_encoding_documents"), counts))
        else:
            result["legacy_documents"] = connection.execute("SELECT COUNT(*) FROM driver_document_blobs").fetchone()[0]
        cipher = _cipher_for(encryption_key)
        if cipher is None:
            return result
        _validate_guard(connection, cipher)
        if "encoding" not in columns or result["legacy_documents"] or result["invalid_encoding_documents"]:
            return result
        for document_id, content, _ in _stored_blob_rows(connection):
            metadata = connection.execute("SELECT data FROM documents WHERE collection=? AND id=?", (DOCUMENTS, document_id)).fetchone()
            if not metadata:
                return result
            doc = json.loads(metadata[0])
            if not isinstance(doc, dict) or doc.get("id") != document_id:
                return result
            _check_plaintext(cipher.decrypt(bytes(content)), doc)
        missing = connection.execute("""SELECT 1 FROM documents d LEFT JOIN driver_document_blobs b ON b.id=d.id
            WHERE d.collection=? AND b.id IS NULL LIMIT 1""", (DOCUMENTS,)).fetchone()
        result["ready"] = missing is None
        return result
    except (DriverVerificationError, InvalidToken, ValueError, TypeError, sqlite3.Error):
        return result
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    import argparse
    import os
    import sys
    parser = argparse.ArgumentParser(description="Offline driver evidence encryption; never run against a live database.")
    parser.add_argument("--database", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Confirm all database users are stopped and a protected backup exists")
    mode.add_argument("--check", action="store_true", help="Read-only aggregate audit; exit nonzero unless storage is ready")
    args = parser.parse_args()
    try:
        if args.check:
            result = audit_evidence_storage(args.database, encryption_key=os.environ.get("IDENTITY_EVIDENCE_KEY"))
        else:
            result = migrate_legacy_evidence(args.database, encryption_key=os.environ.get("IDENTITY_EVIDENCE_KEY"), offline=args.offline)
    except Exception:
        print("Driver evidence conversion failed; transaction rolled back. Check the key, guard and source integrity offline.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result))
    if args.check and not result["ready"]:
        sys.exit(1)
