"""Synthetic evidence only: fail-closed encryption, authorization and offline conversion."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3

import pytest
from cryptography.fernet import Fernet

from app import driver_verification as dv
from app.identity_verification import IdentityVerificationService
from app.store import Store, Transaction
from tests.review_helpers import complete_checklist
from tests.test_driver_verification import PNG, draft, decision


@pytest.fixture
def case(tmp_path):
    key = Fernet.generate_key()
    store = Store(tmp_path / 'driver.sqlite3')
    clock = [datetime(2026, 10, 8, 12, tzinfo=timezone.utc)]
    owner = {'id': 'owner', 'role': 'member', 'development': False, 'auth_method': 'phone',
             'auth_phone': '+919876543210', 'phone_verified': True}
    staff = {'id': 'staff', 'role': 'staff', 'staff_capabilities': ['verify.review']}
    with store.transaction() as tx:
        for user in (owner, staff): tx.put('users', user['id'], user)
    service = dv.DriverVerificationService(store, encryption_key=key, clock=lambda: clock[0])
    return service, store, key, clock, owner, staff


def uploaded(case, *, submit=True):
    service, _, _, _, owner, _ = case
    app = draft(service, owner)
    for kind in dv.KINDS:
        app = service.upload_document(owner, kind=kind, expires_on=None if kind == 'selfie' else '2026-12-30',
            filename='synthetic.png', content=PNG, expected_version=app['version'])['application']
    return service.submit_application(owner, {'expected_version': app['version']})['application'] if submit else app


def unavailable(fn):
    with pytest.raises(dv.DriverVerificationError) as error:
        fn()
    assert (error.value.status, error.value.code) == (503, 'verification_evidence_unavailable')


def stored(store):
    with store.read() as tx:
        return [tuple(row) for row in tx._connection.execute('SELECT id,content,encoding FROM driver_document_blobs ORDER BY id')]


def test_ciphertext_restart_owner_read_and_protected_preview(case):
    service, store, key, clock, owner, staff = case
    app = uploaded(case)
    for _, token, encoding in stored(store):
        assert encoding == 1 and token != PNG and PNG not in token
        assert Fernet(key).decrypt(token) == PNG
    restarted = dv.DriverVerificationService(store, encryption_key=key, clock=lambda: clock[0])
    document = app['documents'][0]['id']
    assert restarted.get_document(owner, document)['content'] == PNG
    assert restarted.get_document_preview(staff, document)['image_data_url'].startswith('data:image/jpeg;base64,')
    with pytest.raises(dv.DriverVerificationError) as error:
        restarted.get_document(staff, document)
    assert error.value.status == 404
    with store.read() as tx:
        token = tx._connection.execute('SELECT token FROM driver_encryption_config').fetchone()[0]
        assert Fernet(key).decrypt(token) == b'driver-evidence-key-v1'


@pytest.mark.parametrize('key_kind', ['missing', 'malformed', 'wrong'])
def test_key_failure_keeps_status_and_rejection_but_blocks_evidence(case, key_kind):
    service, store, key, clock, owner, staff = case
    app = uploaded(case)
    before = stored(store)
    with store.read() as tx:
        guard = bytes(tx._connection.execute('SELECT token FROM driver_encryption_config').fetchone()[0])
    bad = None if key_kind == 'missing' else 'not-a-key' if key_kind == 'malformed' else Fernet.generate_key()
    locked = dv.DriverVerificationService(store, encryption_key=bad, clock=lambda: clock[0])
    assert not locked.available
    assert locked.get_application(owner)['requirements']['available'] is False
    assert service.get_application(owner)['requirements']['available'] is True
    assert locked.get_application(owner)['application']['id'] == app['id']
    assert locked.verification_queue(staff)['applications'][0]['id'] == app['id']
    unavailable(lambda: locked.get_document(owner, app['documents'][0]['id']))
    unavailable(lambda: locked.get_document_preview(staff, app['documents'][0]['id']))
    unavailable(lambda: locked.review_application(staff, decision(app)))
    rejected = locked.review_application(staff, decision(app, decision='rejected'))['application']
    assert rejected['status'] == 'rejected'
    assert stored(store) == before
    with store.read() as tx:
        assert bytes(tx._connection.execute('SELECT token FROM driver_encryption_config').fetchone()[0]) == guard


@pytest.mark.parametrize('damage', ['missing', 'ciphertext', 'legacy', 'unknown_encoding', 'metadata'])
@pytest.mark.parametrize('submitted', [False, True])
def test_storage_damage_cannot_submit_or_approve(case, damage, submitted):
    service, store, _, _, owner, staff = case
    app = uploaded(case, submit=submitted)
    document = app['documents'][0]['id']
    with store.transaction() as tx:
        if damage == 'missing': tx._connection.execute('DELETE FROM driver_document_blobs WHERE id=?', (document,))
        elif damage == 'ciphertext': tx._connection.execute('UPDATE driver_document_blobs SET content=? WHERE id=?', (b'corrupt', document))
        elif damage == 'legacy': tx._connection.execute('UPDATE driver_document_blobs SET content=?,encoding=0 WHERE id=?', (PNG, document))
        elif damage == 'unknown_encoding': tx._connection.execute('UPDATE driver_document_blobs SET encoding=7 WHERE id=?', (document,))
        else:
            doc = tx.get(dv.DOCUMENTS, document); doc['sha256'] = '0' * 64; tx.put(dv.DOCUMENTS, document, doc)
    unavailable(lambda: service.review_application(staff, decision(app)) if submitted else
                service.submit_application(owner, {'expected_version': app['version']}))
    assert service.get_application(owner)['application']['status'] == app['status']


@pytest.mark.parametrize('cleanup', ['withdrawal', 'retention'])
def test_cleanup_works_without_key(case, cleanup):
    service, store, _, clock, owner, _ = case
    app = uploaded(case)
    locked = dv.DriverVerificationService(store, clock=lambda: clock[0])
    if cleanup == 'withdrawal':
        result = draft(locked, owner, version=app['version'], document_consent=False)
        assert result['documents'] == [] and stored(store) == []
    else:
        clock[0] += timedelta(days=31)
        result = locked.get_application(owner)['application']
        assert result['status'] == 'needs_changes' and len(stored(store)) == 3


def test_revocation_without_key_preserves_cleanup_access(case):
    service, store, _, clock, owner, staff = case
    app = uploaded(case)
    for doc in app['documents']: service.get_document_preview(staff, doc['id'])
    complete_checklist(service, staff, app)
    app = service.review_application(staff, decision(app))['application']
    locked = dv.DriverVerificationService(store, clock=lambda: clock[0])
    result = locked.review_application(staff, decision(app, decision='revoked', idempotency_key='revoke-key-12345'))['application']
    assert result['status'] == 'revoked'
    assert draft(locked, owner, version=result['version'], document_consent=False)['documents'] == []


def test_unauthorized_or_missing_key_never_reads_upload_stream(case):
    service, store, _, clock, owner, staff = case
    class Stream:
        def read(self, *_): pytest.fail('Upload stream read before authorization/key check')
    for actor, expected, target in ((None, 401, service), (staff, 403, service),
        (owner, 503, dv.DriverVerificationService(store, clock=lambda: clock[0]))):
        with pytest.raises(dv.DriverVerificationError) as error:
            target.upload_document(actor, kind='dl', expires_on='2026-12-30', filename='x.png', content=Stream(), expected_version=0)
        assert error.value.status == expected


def test_failed_replacement_rolls_back_ciphertext_and_metadata(case, monkeypatch):
    service, store, _, _, owner, _ = case
    app = uploaded(case, submit=False)
    before = stored(store)
    original = Transaction.put
    def fail_document(self, collection, identity, data):
        if collection == dv.DOCUMENTS: raise RuntimeError('synthetic persistence failure')
        return original(self, collection, identity, data)
    monkeypatch.setattr(Transaction, 'put', fail_document)
    with pytest.raises(RuntimeError):
        service.upload_document(owner, kind='selfie', expires_on=None, filename='x.png', content=PNG, expected_version=app['version'])
    assert stored(store) == before
    assert service.get_application(owner)['application'] == app


@pytest.mark.parametrize('damage', ['ciphertext', 'encoding'])
def test_preview_rechecks_stored_ciphertext_and_encoding(case, monkeypatch, damage):
    service, store, key, _, _, staff = case
    app = uploaded(case)
    doc_id = app['documents'][0]['id']
    def renderer(*_):
        with store.transaction() as tx:
            if damage == 'ciphertext':
                tx._connection.execute('UPDATE driver_document_blobs SET content=? WHERE id=?', (Fernet(key).encrypt(PNG), doc_id))
            else: tx._connection.execute('UPDATE driver_document_blobs SET encoding=0 WHERE id=?', (doc_id,))
        return {'image_data_url': 'data:image/jpeg;base64,synthetic', 'page': 1, 'page_count': 1, 'watermark': 'test'}
    monkeypatch.setattr(dv, 'render_preview', renderer)
    with pytest.raises(dv.DriverVerificationError) as error:
        service.get_document_preview(staff, doc_id)
    assert error.value.code == 'document_preview_stale'
    with store.read() as tx: assert tx.list(dv.DOCUMENT_ACCESS) == []


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_guard_cannot_be_replaced_when_encrypted_rows_exist(case, damage):
    service, store, key, clock, _, _ = case
    uploaded(case)
    with store.transaction() as tx:
        if damage == 'missing': tx._connection.execute('DELETE FROM driver_encryption_config')
        else: tx._connection.execute('UPDATE driver_encryption_config SET token=?', (b'corrupt',))
    locked = dv.DriverVerificationService(store, encryption_key=key, clock=lambda: clock[0])
    assert not locked.available
    with store.read() as tx:
        row = tx._connection.execute('SELECT token FROM driver_encryption_config').fetchone()
        assert row is None if damage == 'missing' else bytes(row[0]) == b'corrupt'


def legacy_store(tmp_path):
    store = Store(tmp_path / 'legacy.sqlite3')
    with store.transaction() as tx:
        tx._connection.execute('CREATE TABLE driver_document_blobs (id TEXT PRIMARY KEY, content BLOB NOT NULL)')
        for identity in ('a' * 32, 'b' * 32):
            tx.put(dv.DOCUMENTS, identity, {'id': identity, 'kind': 'dl', 'bytes': len(PNG),
                'sha256': hashlib.sha256(PNG).hexdigest(), 'content_type': 'image/png',
                'filename': 'synthetic.png', 'application_id': 'c' * 32})
            tx._connection.execute('INSERT INTO driver_document_blobs VALUES (?,?)', (identity, PNG))
    return store


def test_legacy_startup_is_not_data_conversion(tmp_path):
    store = legacy_store(tmp_path)
    service = dv.DriverVerificationService(store, encryption_key=Fernet.generate_key())
    assert service.available
    assert all(row[1] == PNG and row[2] == 0 for row in stored(store))
    with store.read() as tx:
        unavailable(lambda: service._read_blob(tx, tx.get(dv.DOCUMENTS, 'a' * 32)))


def test_clean_offline_migration_preserves_metadata_and_is_idempotent(tmp_path):
    store = legacy_store(tmp_path); key = Fernet.generate_key()
    IdentityVerificationService(store, encryption_key=key)
    with store.transaction() as tx:
        tx.put(dv.APPLICATIONS, 'c' * 32, {'id': 'c' * 32, 'status': 'approved', 'version': 9,
            'reviewed_at': '2026-10-08T12:00:00+00:00', 'approval_expires_at': '2026-12-31T00:00:00+00:00'})
        before = tx.list(dv.DOCUMENTS)
        approval = tx.list(dv.APPLICATIONS)
        identity_guard = bytes(tx._connection.execute('SELECT token FROM identity_encryption_config').fetchone()[0])
    assert dv.migrate_legacy_evidence(store.path, encryption_key=key, offline=True) == {'converted_documents': 2}
    for _, token, encoding in stored(store):
        assert encoding == 1 and Fernet(key).decrypt(token) == PNG
    with store.read() as tx:
        assert tx.list(dv.DOCUMENTS) == before
        assert tx.list(dv.APPLICATIONS) == approval
        assert bytes(tx._connection.execute('SELECT token FROM identity_encryption_config').fetchone()[0]) == identity_guard
    first = stored(store)
    assert dv.migrate_legacy_evidence(store.path, encryption_key=key, offline=True) == {'converted_documents': 0}
    assert stored(store) == first


@pytest.mark.parametrize('failure', ['bad_second_blob', 'missing_blob', 'missing_metadata', 'identity_guard', 'no_offline'])
def test_offline_migration_rolls_back_all_writes(tmp_path, failure):
    store = legacy_store(tmp_path); key = Fernet.generate_key()
    if failure == 'identity_guard': IdentityVerificationService(store, encryption_key=Fernet.generate_key())
    with store.transaction() as tx:
        if failure == 'bad_second_blob': tx._connection.execute('UPDATE driver_document_blobs SET content=? WHERE id=?', (b'bad', 'b' * 32))
        elif failure == 'missing_blob': tx._connection.execute('DELETE FROM driver_document_blobs WHERE id=?', ('b' * 32,))
        elif failure == 'missing_metadata': tx.delete(dv.DOCUMENTS, 'b' * 32)
    with sqlite3.connect(store.path) as conn: before = '\n'.join(conn.iterdump())
    with pytest.raises((dv.DriverVerificationError, ValueError)):
        dv.migrate_legacy_evidence(store.path, encryption_key=key, offline=failure != 'no_offline')
    with sqlite3.connect(store.path) as conn: assert '\n'.join(conn.iterdump()) == before


def test_wrong_key_cannot_migrate_or_overwrite_guard(tmp_path):
    store = legacy_store(tmp_path); key = Fernet.generate_key()
    dv.migrate_legacy_evidence(store.path, encryption_key=key, offline=True)
    with sqlite3.connect(store.path) as conn: before = '\n'.join(conn.iterdump())
    unavailable(lambda: dv.migrate_legacy_evidence(store.path, encryption_key=Fernet.generate_key(), offline=True))
    with sqlite3.connect(store.path) as conn: assert '\n'.join(conn.iterdump()) == before


@pytest.mark.parametrize('state', ['clean', 'legacy', 'bad_encoding', 'missing_guard', 'bad_ciphertext', 'wrong_key', 'missing_blob'])
def test_read_only_audit_is_aggregate_and_fail_closed(case, state):
    service, store, key, _, _, _ = case
    app = uploaded(case)
    doc_id = app['documents'][0]['id']
    with store.transaction() as tx:
        if state == 'legacy': tx._connection.execute('UPDATE driver_document_blobs SET content=?,encoding=0 WHERE id=?', (PNG, doc_id))
        elif state == 'bad_encoding': tx._connection.execute('UPDATE driver_document_blobs SET encoding=9 WHERE id=?', (doc_id,))
        elif state == 'missing_guard': tx._connection.execute('DELETE FROM driver_encryption_config')
        elif state == 'bad_ciphertext': tx._connection.execute('UPDATE driver_document_blobs SET content=? WHERE id=?', (b'corrupt', doc_id))
        elif state == 'missing_blob': tx._connection.execute('DELETE FROM driver_document_blobs WHERE id=?', (doc_id,))
    with sqlite3.connect(store.path) as conn: before = '\n'.join(conn.iterdump())
    result = dv.audit_evidence_storage(store.path, encryption_key=Fernet.generate_key() if state == 'wrong_key' else key)
    assert result['ready'] is (state == 'clean')
    assert set(result) == {'legacy_documents', 'encrypted_documents', 'invalid_encoding_documents', 'ready'}
    assert result['legacy_documents'] == (1 if state == 'legacy' else 0)
    assert result['invalid_encoding_documents'] == (1 if state == 'bad_encoding' else 0)
    with sqlite3.connect(store.path) as conn: assert '\n'.join(conn.iterdump()) == before


def test_offline_command_and_check_exit_codes(tmp_path):
    import os
    import subprocess
    import sys
    store = legacy_store(tmp_path); key = Fernet.generate_key()
    env = {**os.environ, 'IDENTITY_EVIDENCE_KEY': key.decode(), 'PYTHONDONTWRITEBYTECODE': '1'}
    command = [sys.executable, '-m', 'app.driver_verification', '--database', store.path]
    pending = subprocess.run(command + ['--check'], env=env, capture_output=True, text=True)
    assert pending.returncode == 1 and json.loads(pending.stdout)['legacy_documents'] == 2
    converted = subprocess.run(command + ['--offline'], env=env, capture_output=True, text=True)
    assert converted.returncode == 0 and json.loads(converted.stdout) == {'converted_documents': 2}
    checked = subprocess.run(command + ['--check'], env=env, capture_output=True, text=True)
    assert checked.returncode == 0 and json.loads(checked.stdout)['ready'] is True
    wrong = subprocess.run(command + ['--offline'], env={**env, 'IDENTITY_EVIDENCE_KEY': Fernet.generate_key().decode()}, capture_output=True, text=True)
    assert wrong.returncode == 1 and 'rolled back' in wrong.stderr
    assert key.decode() not in ''.join(r.stdout + r.stderr for r in (pending, converted, checked, wrong))


def test_migration_and_audit_stream_one_blob_and_skip_payload_when_blocked(tmp_path, monkeypatch):
    store = legacy_store(tmp_path); key = Fernet.generate_key()
    # Initialize only the guard/schema so pending audit reaches the legacy check.
    dv.DriverVerificationService(store, encryption_key=key)
    reads = []
    original_connect = sqlite3.connect
    class PayloadCursor:
        def __init__(self, cursor): self.cursor = cursor
        def fetchall(self): pytest.fail('BLOB payloads must not be fetched all at once')
        def __iter__(self): pytest.fail('Use the explicit bounded fetch contract')
        def fetchmany(self, size):
            assert size == 1
            batch = self.cursor.fetchmany(size)
            reads.append(len(batch))
            return batch
        def close(self): self.cursor.close()
    class Connection(sqlite3.Connection):
        def execute(self, statement, *args):
            cursor = super().execute(statement, *args)
            normalized = ''.join(statement.lower().split())
            if normalized.startswith('selectid,content,encodingfromdriver_document_blobs'):
                return PayloadCursor(cursor)
            return cursor
    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=Connection)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    pending = dv.audit_evidence_storage(store.path, encryption_key=key)
    assert pending['legacy_documents'] == 2 and not pending['ready'] and reads == []
    assert dv.migrate_legacy_evidence(store.path, encryption_key=key, offline=True)['converted_documents'] == 2
    assert reads == [1, 1, 0]
    reads.clear()
    assert not dv.audit_evidence_storage(store.path, encryption_key=Fernet.generate_key())['ready']
    assert reads == []
    assert dv.audit_evidence_storage(store.path, encryption_key=key)['ready']
    assert reads == [1, 1, 0]
