"""Isolated restore drills use only synthetic records and no external services."""
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from app.driver_verification import DriverVerificationService
from app.identity_verification import IdentityVerificationService
from app.phone_auth import PhoneAuthService
from app.store import Store
from scripts.backup_store import BackupError, backup, restore
from cryptography.fernet import Fernet


KEY = "synthetic-backup-test-key-" * 3


@pytest.fixture
def populated(tmp_path):
    store = Store(tmp_path / "source.sqlite3")
    DriverVerificationService(store)
    PhoneAuthService(store, provider=SimpleNamespace(ready=True), hmac_key=KEY, global_daily_limit=100)
    with store.transaction() as tx:
        for collection, identity, extra in (
            ("users", "synthetic-user", {"phone": "+919000000001", "name": "Private fixture name"}),
            ("phone_identities", "synthetic-phone-hmac", {"user_id": "synthetic-user"}),
            ("mobile_sessions", "synthetic-session-hash", {"user_id": "synthetic-user"}),
            ("driver_documents", "synthetic-document", {"filename": "private-evidence.pdf"}),
        ):
            tx.put(collection, identity, {"id": identity, **extra})
        tx._connection.execute("INSERT INTO driver_document_blobs(id,content) VALUES (?,?)", ("synthetic-document", b"private synthetic BLOB\x00\xff"))
        tx._connection.execute("CREATE TABLE identity_document_blobs (id TEXT PRIMARY KEY, content BLOB NOT NULL)")
        tx._connection.execute("CREATE TABLE identity_encryption_config (id INTEGER PRIMARY KEY, token BLOB NOT NULL)")
        tx._connection.execute("INSERT INTO identity_document_blobs VALUES (?,?)", ("synthetic-identity-document", b"synthetic encrypted identity evidence"))
        tx._connection.execute("INSERT INTO identity_encryption_config VALUES (?,?)", (1, b"synthetic encrypted key-binding token"))
    return store


def test_backup_restore_preserves_all_tables_and_phone_key_guard(populated, tmp_path):
    directory, target = tmp_path / "backup", tmp_path / "restored.sqlite3"
    manifest = backup(populated.path, directory)
    result = restore(directory, target)
    assert result["integrity"] == "ok"
    assert result["counts"]["documents"] == 5
    assert result["counts"]["driver_document_blobs"] == 1
    assert result["counts"]["identity_document_blobs"] == 1
    assert result["counts"]["identity_encryption_config"] == 1
    assert result["identity_document_blobs_present"] is True
    assert result["identity_encryption_config_present"] is True
    assert result["external_identity_evidence_key_required"] is True
    assert result["external_phone_key_required"] is True
    with sqlite3.connect(populated.path) as source, sqlite3.connect(target) as restored:
        for table in ("documents", "driver_document_blobs", "identity_document_blobs", "identity_encryption_config"):
            assert source.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() == restored.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
    recovered = Store(target)
    assert PhoneAuthService(recovered, provider=SimpleNamespace(ready=True), hmac_key=KEY, global_daily_limit=100).enabled
    with pytest.raises(ValueError, match="identity key differs"):
        PhoneAuthService(recovered, provider=SimpleNamespace(ready=True), hmac_key="wrong-key" * 8, global_daily_limit=100)
    metadata = json.dumps(manifest)
    assert all(private not in metadata for private in (KEY, "+919000000001", "Private fixture name", "private-evidence.pdf", "synthetic-user", "synthetic encrypted identity evidence", "synthetic encrypted key-binding token"))
    for path in (directory, directory / "store.sqlite3", directory / "manifest.json", target):
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_backup_reads_committed_snapshot_while_writer_has_uncommitted_changes(populated, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def writer():
        with populated.transaction() as tx:
            tx.put("users", "later", {"id": "later"})
            tx._connection.execute("INSERT INTO driver_document_blobs(id,content) VALUES (?,?)", ("later", b"later"))
            entered.set()
            assert release.wait(10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        assert entered.wait(3)
        try:
            before = backup(populated.path, tmp_path / "during")
            assert before["counts"]["users"] == 1
            assert before["counts"]["driver_document_blobs"] == 1
        finally:
            release.set()
        future.result()
    after = backup(populated.path, tmp_path / "after")
    assert after["counts"]["users"] == 2
    assert after["counts"]["driver_document_blobs"] == 2
    result = restore(tmp_path / "after", tmp_path / "recovered.sqlite3")
    assert result["counts"] == after["counts"]


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_restore_never_overwrites_existing_destination_or_sidecar(populated, tmp_path, suffix):
    backup(populated.path, tmp_path / "backup")
    target = tmp_path / "restore.sqlite3"
    protected = Path(str(target) + suffix)
    protected.write_bytes(b"preserve exactly")
    with pytest.raises(BackupError, match="overwrite"):
        restore(tmp_path / "backup", target)
    assert protected.read_bytes() == b"preserve exactly"


@pytest.mark.parametrize("damage", ["database", "manifest", "counts", "fingerprint", "identity_blob_missing",
                                    "identity_blob_tampered", "identity_config_missing", "identity_config_tampered",
                                    "identity_key_required"])
def test_corrupt_backup_is_rejected_before_restore_creation(populated, tmp_path, damage):
    directory, target = tmp_path / "backup", tmp_path / "restore.sqlite3"
    backup(populated.path, directory)
    if damage == "database":
        (directory / "store.sqlite3").write_bytes(b"broken sqlite")
    elif damage == "manifest":
        (directory / "manifest.json").write_text("not json")
    elif damage == "identity_key_required":
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["external_identity_evidence_key_required"] = False
        (directory / "manifest.json").write_text(json.dumps(manifest))
    elif damage.startswith("identity_"):
        snapshot = directory / "store.sqlite3"
        with sqlite3.connect(snapshot) as connection:
            if damage == "identity_blob_missing":
                connection.execute("DELETE FROM identity_document_blobs")
            elif damage == "identity_blob_tampered":
                connection.execute("UPDATE identity_document_blobs SET content=?", (b"different encrypted evidence",))
            elif damage == "identity_config_missing":
                connection.execute("DELETE FROM identity_encryption_config WHERE id=1")
            else:
                connection.execute("UPDATE identity_encryption_config SET token=? WHERE id=1", (b"different encrypted key-binding token",))
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["bytes"] = snapshot.stat().st_size
        manifest["sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        (directory / "manifest.json").write_text(json.dumps(manifest))
    else:
        manifest = json.loads((directory / "manifest.json").read_text())
        if damage == "counts":
            manifest["counts"]["documents"] += 1
        else:
            manifest["phone_key_fingerprint_sha256"] = "incorrect"
        (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BackupError):
        restore(directory, target)
    assert not target.exists()


def test_missing_required_table_and_existing_backup_refused(tmp_path):
    source = tmp_path / "wrong.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    with pytest.raises(BackupError, match="documents table"):
        backup(source, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()
    (tmp_path / "existing").mkdir()
    with pytest.raises(BackupError, match="already exists"):
        backup(source, tmp_path / "existing")


def test_backup_sidecars_and_symlink_destinations_are_refused(populated, tmp_path):
    directory = tmp_path / "backup"
    backup(populated.path, directory)
    (directory / "store.sqlite3-wal").write_bytes(b"untrusted sidecar")
    with pytest.raises(BackupError, match="self-contained"):
        restore(directory, tmp_path / "new.sqlite3")
    (directory / "store.sqlite3-wal").unlink()
    target = tmp_path / "linked.sqlite3"
    target.symlink_to(tmp_path / "nonexistent.sqlite3")
    with pytest.raises(BackupError, match="overwrite"):
        restore(directory, target)
    assert target.is_symlink()
    assert not (tmp_path / "nonexistent.sqlite3").exists()


def test_phone_identity_without_key_binding_refuses_snapshot(populated, tmp_path):
    with populated.transaction() as tx:
        tx.delete("phone_auth_config", "identity-key")
    with pytest.raises(BackupError, match="key continuity"):
        backup(populated.path, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_legacy_store_without_blob_table_and_cli(tmp_path):
    source = Store(tmp_path / "legacy.sqlite3")
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/backup_store.py")]
    saved = subprocess.run(command + ["backup", "--database", source.path, "--output", str(tmp_path / "backup")], capture_output=True, text=True)
    assert saved.returncode == 0, saved.stderr
    manifest = json.loads(saved.stdout)
    assert manifest["driver_document_blobs_present"] is False
    assert manifest["external_phone_key_required"] is False
    assert manifest["identity_document_blobs_present"] is False
    assert manifest["identity_encryption_config_present"] is False
    assert manifest["external_identity_evidence_key_required"] is False
    recovered = subprocess.run(command + ["restore", "--backup", str(tmp_path / "backup"), "--destination", str(tmp_path / "restored.sqlite3")], capture_output=True, text=True)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["restored"] is True


def test_restore_accepts_pre_identity_inventory_manifest(populated, tmp_path):
    directory = tmp_path / "legacy-backup"
    backup(populated.path, directory)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # Model a format-1 manifest created before identity evidence inventory existed.
    manifest["format"] = 1
    for key in ("identity_document_blobs_present", "identity_document_blobs_sha256",
                "identity_encryption_config_present", "identity_encryption_config_sha256",
                "identity_encryption_config_token_sha256", "external_identity_evidence_key_required"):
        manifest.pop(key, None)
    manifest["counts"].pop("identity_document_blobs", None)
    manifest["counts"].pop("identity_encryption_config", None)
    manifest_path.write_text(json.dumps(manifest))
    restored = restore(directory, tmp_path / "legacy-restored.sqlite3")
    assert restored["counts"]["identity_document_blobs"] == 1
    assert restored["external_identity_evidence_key_required"] is True


def test_fernet_identity_evidence_recovers_with_same_key_only(tmp_path):
    source = Store(tmp_path / "encrypted-source.sqlite3")
    # This synthetic key exists only in this test process. It is never written
    # to the database, manifest, command line or test output.
    encryption_key = Fernet.generate_key()
    identity = IdentityVerificationService(source, encryption_key=encryption_key)
    assert identity.available
    cleartext = b"synthetic identity evidence for isolated restore test"
    document_id = "synthetic-fernet-document"
    ciphertext = identity._cipher.encrypt(cleartext)
    with source.transaction() as tx:
        tx._connection.execute("INSERT INTO identity_document_blobs(id,content) VALUES (?,?)",
                               (document_id, ciphertext))

    directory, target = tmp_path / "encrypted-backup", tmp_path / "encrypted-restored.sqlite3"
    manifest = backup(source.path, directory)
    assert manifest["external_identity_evidence_key_required"] is True
    assert encryption_key.decode() not in json.dumps(manifest)
    restore(directory, target)

    recovered_store = Store(target)
    recovered = IdentityVerificationService(recovered_store, encryption_key=encryption_key)
    assert recovered.available
    with recovered_store.read() as tx:
        row = tx._connection.execute("SELECT content FROM identity_document_blobs WHERE id=?",
                                     (document_id,)).fetchone()
    assert recovered._cipher.decrypt(bytes(row[0])) == cleartext

    wrong_key = Fernet.generate_key()
    wrong = IdentityVerificationService(recovered_store, encryption_key=wrong_key)
    assert wrong.available is False
