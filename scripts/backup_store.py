#!/usr/bin/env python3
"""Private SQLite snapshots and non-overwriting restore drills. No service mutations."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time


class BackupError(Exception):
    pass


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _private(path, mode):
    path.chmod(mode)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise BackupError("Private filesystem permissions are unavailable; use an owner-only filesystem path.")


def _new_file(path):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise BackupError("Destination already exists; overwrite is forbidden.") from None
    os.close(descriptor)
    try:
        _private(path, 0o600)
    except BaseException:
        path.unlink()
        raise


def _reader(path, *, immutable=False):
    if path.is_symlink() or not path.is_file():
        raise BackupError("A regular database file is required; symlinks are refused.")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True, timeout=10)


def _rows_digest(connection, query):
    """Fingerprint ordered rows without exposing identifiers or BLOB contents."""
    digest = hashlib.sha256()
    for row in connection.execute(query):
        for value in row:
            if value is None:
                raw = b""
                tag = b"n"
            elif isinstance(value, bytes):
                raw = value
                tag = b"b"
            elif isinstance(value, int):
                raw = str(value).encode("ascii")
                tag = b"i"
            else:
                raw = str(value).encode("utf-8")
                tag = b"t"
            digest.update(tag)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        digest.update(b"\xff")
    return digest.hexdigest()


def _inventory(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise BackupError("Database integrity check failed.")
    schema = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    tables = {row[1] for row in schema if row[0] == "table"}
    if "documents" not in tables:
        raise BackupError("Required documents table is missing.")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
    if not {"collection", "id", "data"} <= columns:
        raise BackupError("Required document-store columns are missing.")
    row = connection.execute(
        "SELECT data FROM documents WHERE collection='phone_auth_config' AND id='identity-key'"
    ).fetchone()
    fingerprint_digest = None
    if row:
        try:
            fingerprint = json.loads(row[0])["fingerprint"]
            if not isinstance(fingerprint, str) or not fingerprint:
                raise ValueError()
            fingerprint_digest = hashlib.sha256(fingerprint.encode()).hexdigest()
        except (ValueError, KeyError, TypeError):
            raise BackupError("Phone identity-key continuity metadata is invalid.") from None
    counts = {"documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]}
    if "driver_document_blobs" in tables:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(driver_document_blobs)")}
        if not {"id", "content"} <= columns:
            raise BackupError("Private document table columns are invalid.")
        counts["driver_document_blobs"] = connection.execute("SELECT COUNT(*) FROM driver_document_blobs").fetchone()[0]
    identity_blobs_present = "identity_document_blobs" in tables
    identity_config_present = "identity_encryption_config" in tables
    if identity_blobs_present:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(identity_document_blobs)")}
        if not {"id", "content"} <= columns:
            raise BackupError("Private identity document table columns are invalid.")
        counts["identity_document_blobs"] = connection.execute(
            "SELECT COUNT(*) FROM identity_document_blobs").fetchone()[0]
        identity_blobs_digest = _rows_digest(
            connection, "SELECT id,content FROM identity_document_blobs ORDER BY id")
    else:
        counts["identity_document_blobs"] = 0
        identity_blobs_digest = None
    if identity_config_present:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(identity_encryption_config)")}
        if not {"id", "token"} <= columns:
            raise BackupError("Identity encryption configuration columns are invalid.")
        counts["identity_encryption_config"] = connection.execute(
            "SELECT COUNT(*) FROM identity_encryption_config").fetchone()[0]
        identity_config_digest = _rows_digest(
            connection, "SELECT id,token FROM identity_encryption_config ORDER BY id")
        config_row = connection.execute(
            "SELECT token FROM identity_encryption_config WHERE id=1").fetchone()
        if counts["identity_encryption_config"] and config_row is None:
            raise BackupError("Identity encryption-key continuity metadata is invalid.")
        if config_row is not None and not isinstance(config_row[0], (bytes, bytearray, memoryview)):
            raise BackupError("Identity encryption-key continuity metadata is invalid.")
        identity_config_token_digest = (hashlib.sha256(bytes(config_row[0])).hexdigest()
                                        if config_row is not None else None)
    else:
        counts["identity_encryption_config"] = 0
        identity_config_digest = None
        identity_config_token_digest = None
    # Only fixed collection labels and counts are published, never identifiers or values.
    for collection in ("users", "phone_identities", "phone_auth_config", "mobile_sessions", "driver_documents"):
        counts[collection] = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE collection=?", (collection,)
        ).fetchone()[0]
    if counts["phone_identities"] and fingerprint_digest is None:
        raise BackupError("Phone identities exist without their key continuity metadata.")
    if counts["identity_document_blobs"] and identity_config_token_digest is None:
        raise BackupError("Encrypted identity evidence exists without its key continuity metadata.")
    return {"counts": counts, "schema_sha256": hashlib.sha256(json.dumps(schema).encode()).hexdigest(),
            "phone_key_fingerprint_sha256": fingerprint_digest,
            "driver_document_blobs_present": "driver_document_blobs" in tables,
            "identity_document_blobs_present": identity_blobs_present,
            "identity_document_blobs_sha256": identity_blobs_digest,
            "identity_encryption_config_present": identity_config_present,
            "identity_encryption_config_sha256": identity_config_digest,
            "identity_encryption_config_token_sha256": identity_config_token_digest}


def _copy(source, destination, *, immutable=False):
    deadline = time.monotonic() + 60
    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise BackupError("Snapshot timed out; retry during a quieter period.")
    with closing(_reader(source, immutable=immutable)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer, pages=256, progress=progress, sleep=0.05)
        # Produce a self-contained file; future application use can enable WAL again.
        writer.execute("PRAGMA journal_mode=DELETE")
        return _inventory(writer)


def backup(source, directory):
    source, directory = Path(source), Path(directory)
    if source.is_symlink() or not source.is_file():
        raise BackupError("Source must be an existing regular database file.")
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        raise BackupError("Backup directory already exists; choose a new directory.") from None
    try:
        _private(directory, 0o700)
        snapshot = directory / "store.sqlite3"
        _new_file(snapshot)
        inventory = _copy(source, snapshot)
        manifest = {"format": 2, "created_at": datetime.now(timezone.utc).isoformat(),
                    "database": "store.sqlite3", "bytes": snapshot.stat().st_size,
                    "sha256": _digest(snapshot), **inventory,
                    "external_phone_key_required": inventory["phone_key_fingerprint_sha256"] is not None,
                    "external_identity_evidence_key_required": inventory["identity_encryption_config_token_sha256"] is not None}
        target = directory / "manifest.json"
        _new_file(target)
        target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest
    except BaseException:
        shutil.rmtree(directory)
        raise


def restore(directory, destination):
    directory, destination = Path(directory), Path(destination)
    # Refuse even broken symlinks and SQLite sidecars from a previous database.
    if any(os.path.lexists(str(destination) + suffix) for suffix in ("", "-wal", "-shm", "-journal")):
        raise BackupError("Restore destination or its SQLite sidecars already exist; overwrite is forbidden.")
    snapshot, manifest_path = directory / "store.sqlite3", directory / "manifest.json"
    if directory.is_symlink() or manifest_path.is_symlink() or snapshot.is_symlink():
        raise BackupError("Backup symlinks are refused.")
    if any(os.path.lexists(str(snapshot) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise BackupError("Backup must be self-contained without SQLite sidecars.")
    try:
        if manifest_path.stat().st_size > 65536:
            raise ValueError()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["format"] not in (1, 2) or manifest["database"] != "store.sqlite3":
            raise ValueError()
        if snapshot.stat().st_size != manifest["bytes"] or _digest(snapshot) != manifest["sha256"]:
            raise BackupError("Backup bytes do not match the manifest.")
        common_keys = ("counts", "schema_sha256", "phone_key_fingerprint_sha256", "driver_document_blobs_present")
        identity_keys = ("identity_document_blobs_present", "identity_document_blobs_sha256",
                         "identity_encryption_config_present", "identity_encryption_config_sha256",
                         "identity_encryption_config_token_sha256")
        manifest_inventory = {key: manifest[key] for key in common_keys}
        if manifest["format"] == 2:
            manifest_inventory.update({key: manifest[key] for key in identity_keys})
            if manifest["external_identity_evidence_key_required"] is not (
                    manifest["identity_encryption_config_token_sha256"] is not None):
                raise ValueError()
        elif "identity_document_blobs" in manifest.get("counts", {}) or any(key in manifest for key in identity_keys):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise BackupError("Backup manifest is missing or invalid.") from None
    with closing(_reader(snapshot, immutable=True)) as connection:
        snapshot_inventory = _inventory(connection)
        observed_manifest_inventory = {key: snapshot_inventory[key] for key in manifest_inventory}
        if manifest["format"] == 1:
            observed_manifest_inventory["counts"] = {
                key: snapshot_inventory["counts"].get(key) for key in manifest["counts"]}
        if observed_manifest_inventory != manifest_inventory:
            raise BackupError("Backup schema, counts or phone-key metadata do not match.")
        # Legacy format-1 snapshots predate identity evidence inventory. Their
        # snapshot hash still protects the file; compare the restore to the
        # freshly inventoried snapshot so all tables are checked during copy.
        expected = snapshot_inventory if manifest["format"] == 1 else manifest_inventory
    _new_file(destination)
    try:
        actual = _copy(snapshot, destination, immutable=True)
        if actual != expected or _digest(snapshot) != manifest["sha256"]:
            raise BackupError("Restored schema, counts or phone-key metadata do not match.")
        _private(destination, 0o600)
        return {"restored": True, "integrity": "ok", **actual,
                "external_phone_key_required": actual["phone_key_fingerprint_sha256"] is not None,
                "external_identity_evidence_key_required": actual["identity_encryption_config_token_sha256"] is not None}
    except BaseException:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    save = sub.add_parser("backup")
    save.add_argument("--database", required=True, type=Path)
    save.add_argument("--output", required=True, type=Path)
    recover = sub.add_parser("restore")
    recover.add_argument("--backup", required=True, type=Path)
    recover.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = backup(args.database, args.output) if args.action == "backup" else restore(args.backup, args.destination)
    except BackupError as exc:
        parser.exit(1, f"{exc}\n")
    except (OSError, sqlite3.Error):
        parser.exit(1, "Database operation failed; check private paths, permissions and available disk space.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
