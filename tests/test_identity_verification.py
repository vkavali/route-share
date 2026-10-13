"""Persisted private identity review, privacy boundaries and concurrent writes."""
from tests.review_helpers import complete_checklist
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from cryptography.fernet import Fernet

from app.identity_verification import (
    APPLICATIONS, DOCUMENTS, DOCUMENT_ACCESS, DECISIONS, CHECKS, MAX_DOCUMENT_BYTES,
    IdentityVerificationError, IdentityVerificationService, delete_user_evidence,
)
from app.store import Store

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
PDF = b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n'
UTC = timezone.utc


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / 'identity.sqlite3')
    clock = [datetime(2026, 10, 8, 12, tzinfo=UTC)]
    users = {
        'alice': {'id': 'alice', 'role': 'member', 'verification': {'phone': 'not_checked'}},
        'bob': {'id': 'bob', 'role': 'member'},
        'fixture': {'id': 'fixture', 'role': 'member', 'development': True},
        'reviewer': {'id': 'reviewer', 'role': 'staff', 'staff_capabilities': ['verify.review']},
        'ops': {'id': 'ops', 'role': 'staff', 'staff_capabilities': ['ops.read']},
    }
    with store.transaction() as tx:
        for user in users.values():
            tx.put('users', user['id'], user)
    key = Fernet.generate_key()
    service = IdentityVerificationService(store, encryption_key=key, clock=lambda: clock[0])
    return service, store, users, clock, key


def save(service, user, version=0, **changes):
    payload = dict(expected_version=version, legal_name='Private Legal Name', document_type='passport',
                   adult_attested=True, document_consent=True)
    payload.update(changes)
    return service.save_application(user, payload)['application']


def ready(system, who='alice', version=0, **changes):
    service, _, users, _, _ = system
    app = save(service, users[who], version, **changes)
    for kind in ('identity_document', 'selfie'):
        expiry = '2028-11-30' if kind == 'identity_document' and app['document_type'] != 'voter_id' else None
        app = service.upload_document(users[who], kind=kind, expires_on=expiry, filename='Secret ID 123.png',
                                      content=BytesIO(PNG), expected_version=app['version'])['application']
    app = service.submit_application(users[who], {'expected_version': app['version']})['application']
    for doc in app['documents']:
        service.get_document_preview(users['reviewer'], doc['id'])
    complete_checklist(service, users['reviewer'], app)
    return app


def decision(app, **changes):
    payload = dict(application_id=app['id'], expected_version=app['version'], decision='approved',
                   reason='Checked supplied evidence manually.', checks={key: True for key in CHECKS},
                   idempotency_key='review-key-123456')
    payload.update(changes)
    return payload


def failure(status, fn, code=None):
    with pytest.raises(IdentityVerificationError) as caught:
        fn()
    assert caught.value.status == status
    if code:
        assert caught.value.code == code


def test_complete_persisted_path_twice_and_encrypted_restart(system):
    service, store, users, clock, key = system
    for who in ('alice', 'bob'):
        assert service.get_application(users[who])['application'] is None
        app = ready(system, who)
        result = service.review_application(users['reviewer'], decision(app, idempotency_key='review-for-' + who))
        assert result['application']['status'] == 'approved'
        assert result['application']['approval_expires_at'] == (clock[0] + timedelta(days=365)).isoformat()
        with store.read() as tx:
            user = tx.get('users', who)
            assert user['identity_approval']['kind'] == 'human_document_review'
            assert user['verification']['identity'] == 'verified'
            assert user.get('driver_approved') is None
            assert 'Private Legal Name' not in json.dumps(user)
        restarted = IdentityVerificationService(Store(store.path), encryption_key=key, clock=lambda: clock[0])
        assert restarted.get_application(users[who]) == result
        for doc in app['documents']:
            assert restarted.get_document(users[who], doc['id'])['content'] == PNG
    with store.read() as tx:
        assert len(tx.list(DECISIONS)) == 2
        assert len(tx.list(DOCUMENT_ACCESS)) == 4
        serialized = json.dumps(tx.list(APPLICATIONS) + tx.list(DOCUMENTS) + tx.list(DECISIONS))
        for secret in ('Private Legal Name', 'Secret ID 123', 'Checked supplied evidence manually.'):
            assert secret not in serialized
        blobs = tx._connection.execute('SELECT content FROM identity_document_blobs').fetchall()
        assert len(blobs) == 4
        assert all(PNG not in bytes(b[0]) and bytes(b[0]).startswith(b'gAAAA') for b in blobs)
        assert tx.list('events') == []


@pytest.mark.parametrize('who', ['bob', 'ops'])
def test_private_access_and_current_reviewer_grants(system, who):
    service, store, users, _, _ = system
    app = ready(system)
    failure(404, lambda: service.get_document(users[who], app['documents'][0]['id']))
    failure(403, lambda: service.verification_queue(users[who]))
    failure(403, lambda: service.review_application(users[who], decision(app)))
    with store.transaction() as tx:
        user = tx.get('users', 'reviewer'); user['staff_capabilities'] = []; tx.put('users', 'reviewer', user)
    failure(403, lambda: service.review_application(users['reviewer'], decision(app)))
    failure(404, lambda: service.get_document(users['reviewer'], app['documents'][0]['id']))
    failure(403, lambda: service.get_document_preview(users['reviewer'], app['documents'][0]['id']))


def test_self_review_account_revocation_and_no_unauthenticated_stream_reads(system):
    service, store, users, _, _ = system
    app = ready(system)
    with store.transaction() as tx:
        user = tx.get('users', 'alice'); user.update(role='staff', staff_capabilities=['verify.review']); tx.put('users', 'alice', user)
    failure(403, lambda: service.review_application(users['alice'], decision(app)), 'identity_self_review')
    with store.transaction() as tx:
        user = tx.get('users', 'alice'); user['auth_epoch'] = 1; tx.put('users', 'alice', user)
    failure(401, lambda: service.get_document(users['alice'], app['documents'][0]['id']))
    class NeverRead:
        def read(self, _):
            pytest.fail('Unauthorized stream was read')
    failure(401, lambda: service.upload_document(None, kind='identity_document', expires_on=None,
                                                filename='x', content=NeverRead(), expected_version=0))


def test_missing_wrong_invalid_key_fail_closed_but_withdraw_works(system):
    service, store, users, clock, _ = system
    app = ready(system)
    for key in (None, 'broken', Fernet.generate_key()):
        locked = IdentityVerificationService(store, encryption_key=key, clock=lambda: clock[0])
        result = locked.get_application(users['alice'])
        assert result['requirements']['available'] is False
        assert result['application']['legal_name'] is None
        failure(503, lambda: save(locked, users['bob']))
        failure(503, lambda: locked.get_document(users['alice'], app['documents'][0]['id']))
        failure(503, lambda: locked.review_application(users['reviewer'], decision(app)))
    withdrawn = locked.withdraw_application(users['alice'], {'expected_version': app['version']})['application']
    assert withdrawn['status'] == 'withdrawn'
    with store.read() as tx:
        assert tx.list(DOCUMENTS) == []
        assert tx._connection.execute('SELECT count(*) FROM identity_document_blobs').fetchone()[0] == 0


@pytest.mark.parametrize('decision_type', ['rejected', 'needs_changes'])
def test_reject_resubmit_revoke_and_withdraw(system, decision_type):
    service, store, users, _, _ = system
    app = ready(system)
    app = service.review_application(users['reviewer'], decision(app, decision=decision_type))['application']
    assert app['status'] == decision_type
    app = ready(system, version=app['version'])
    app = service.review_application(users['reviewer'], decision(app, idempotency_key='second-review-key'))['application']
    assert app['status'] == 'approved'
    app = service.review_application(users['reviewer'], decision(app, decision='revoked', idempotency_key='revoke-review-key'))['application']
    assert app['status'] == 'revoked'
    with store.read() as tx:
        assert tx.get('users', 'alice')['identity_approval'] is None
    app = service.withdraw_application(users['alice'], {'expected_version': app['version']})['application']
    assert app['documents'] == [] and app['legal_name'] is None


def test_retention_does_not_extend_on_review_and_approval_expires(system):
    service, store, users, clock, _ = system
    app = ready(system)
    original_deadlines = [d['delete_after'] for d in app['documents']]
    app = service.review_application(users['reviewer'], decision(app))['application']
    assert [d['delete_after'] for d in app['documents']] == original_deadlines
    clock[0] += timedelta(days=31)
    assert service.maintenance()['deleted_documents'] == 2
    assert service.get_application(users['alice'])['application']['status'] == 'approved'
    clock[0] += timedelta(days=335)
    assert service.maintenance()['expired_applications'] == 1
    assert service.get_application(users['alice'])['application']['status'] == 'expired'
    with store.read() as tx:
        assert tx.get('users', 'alice')['identity_approval'] is None


def test_cannot_approve_deleted_or_unviewed_current_evidence(system):
    service, _, users, clock, _ = system
    app = ready(system)
    with service.store.transaction() as tx:
        for row in tx.list(DOCUMENT_ACCESS): tx.delete(DOCUMENT_ACCESS, row['id'])
    failure(409, lambda: service.review_application(users['reviewer'], decision(app)), 'identity_documents_unread')
    clock[0] += timedelta(days=31)
    service.maintenance()
    failure(409, lambda: service.review_application(users['reviewer'], decision(app)), 'identity_version_conflict')


def test_concurrent_save_and_review_idempotency(system):
    service, store, users, _, _ = system
    def attempt(_):
        try:
            return save(service, users['alice'])['version']
        except IdentityVerificationError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results, key=str) == [1, 'identity_version_conflict']
    app = ready(system, version=1)
    payload = decision(app)
    first = service.review_application(users['reviewer'], payload)
    assert service.review_application(users['reviewer'], payload) == first
    failure(409, lambda: service.review_application(users['reviewer'], {**payload, 'reason': 'Different review reason.'}), 'identity_idempotency_conflict')
    failure(409, lambda: service.review_application(users['reviewer'], decision(app, idempotency_key='another-review-key')), 'identity_version_conflict')
    with store.read() as tx:
        assert len(tx.list(DECISIONS)) == 1


def test_forged_approval_fields_ignored_and_development_stays_development(system):
    service, store, users, _, _ = system
    save(service, users['alice'], status='approved', verification={'identity': 'verified'}, identity_approval={'kind': 'human_document_review'}, user_id='bob')
    with store.read() as tx:
        assert tx.get('users', 'alice').get('identity_approval') is None
        assert tx.get('users', 'bob').get('identity_approval') is None
    app = ready(system, 'fixture')
    service.review_application(users['reviewer'], decision(app))
    with store.read() as tx:
        user = tx.get('users', 'fixture')
        assert user['development'] is True
        assert user['identity_approval']['kind'] == 'development'
        assert user['verification']['identity'] == 'development'


@pytest.mark.parametrize('kind', ['aadhaar', 'pan', 'national_id', [], None])
def test_only_supported_identity_types(system, kind):
    service, _, users, _, _ = system
    failure(400, lambda: save(service, users['alice'], document_type=kind))


def test_document_bounds_generic_names_type_change_and_voter_id(system):
    service, store, users, _, _ = system
    app = save(service, users['alice'])
    stream = BytesIO(b'x' * (MAX_DOCUMENT_BYTES + 100))
    failure(413, lambda: service.upload_document(users['alice'], kind='identity_document', expires_on='2028-11-30', filename='x', content=stream, expected_version=app['version']))
    assert stream.tell() == MAX_DOCUMENT_BYTES + 1
    failure(400, lambda: service.upload_document(users['alice'], kind='selfie', expires_on=None, filename='x', content=PDF, expected_version=app['version']))
    failure(400, lambda: service.upload_document(users['alice'], kind='identity_document', expires_on=None, filename='x', content=PNG, expected_version=app['version']))
    app = service.upload_document(users['alice'], kind='identity_document', expires_on='2028-11-30', filename='private-number-123.exe', content=PDF, expected_version=app['version'])['application']
    assert app['documents'][0]['filename'] == 'identity_document.pdf'
    app = save(service, users['alice'], app['version'], document_type='voter_id')
    assert app['documents'] == []
    app = ready(system, version=app['version'], document_type='voter_id')
    assert service.review_application(users['reviewer'], decision(app))['application']['status'] == 'approved'
    with store.transaction() as tx:
        delete_user_evidence(tx, 'alice')
    with store.read() as tx:
        for collection in (APPLICATIONS, DOCUMENTS, DECISIONS, DOCUMENT_ACCESS):
            assert tx.list(collection) == []
        assert tx._connection.execute('SELECT count(*) FROM identity_document_blobs').fetchone()[0] == 0


def test_independent_approval_is_not_cleared_by_identity_draft(system):
    service, store, users, _, _ = system
    independent = {'kind': 'human_document_review', 'source': 'driver_application', 'expires_at': '2028-01-01T00:00:00+00:00'}
    with store.transaction() as tx:
        user = tx.get('users', 'alice'); user.update(identity_approval=independent, verification={'identity': 'verified'}); tx.put('users', 'alice', user)
    app = save(service, users['alice'])
    service.withdraw_application(users['alice'], {'expected_version': app['version']})
    with store.read() as tx:
        assert tx.get('users', 'alice')['identity_approval'] == independent
        assert tx.get('users', 'alice')['verification']['identity'] == 'verified'


def test_review_conflict_under_two_tabs(system):
    service, store, users, _, _ = system
    app = ready(system)
    def attempt(index):
        try:
            result = service.review_application(users['reviewer'], decision(app, idempotency_key=f'parallel-review-{index}'))
            return result['application']['status']
        except IdentityVerificationError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ['approved', 'identity_version_conflict']
    with store.read() as tx:
        assert len(tx.list(DECISIONS)) == 1


def test_strict_declarations_and_review_checks(system):
    service, _, users, _, _ = system
    failure(400, lambda: save(service, users['alice'], adult_attested='true'))
    failure(400, lambda: save(service, users['alice'], document_consent=1))
    app = save(service, users['alice'], adult_attested=False)
    failure(409, lambda: service.submit_application(users['alice'], {'expected_version': app['version']}), 'identity_incomplete')
    app = ready(system, version=app['version'])
    failure(400, lambda: service.review_application(users['reviewer'], decision(app, checks={k: 1 for k in CHECKS})))
    failure(409, lambda: service.review_application(users['reviewer'], decision(app, checks={k: k != 'adult_confirmed' for k in CHECKS})), 'identity_incomplete')
    failure(400, lambda: service.review_application(users['reviewer'], decision(app, checks={k: True for k in CHECKS - {'name_matches'}})))


def test_expiry_caps_approval_and_replaced_document_requires_new_view(system):
    service, _, users, _, _ = system
    app = ready(system)
    app = service.review_application(users['reviewer'], decision(app, decision='needs_changes'))['application']
    app = service.upload_document(users['alice'], kind='identity_document', expires_on='2026-11-01',
                                  filename='x', content=PNG, expected_version=app['version'])['application']
    app = service.submit_application(users['alice'], {'expected_version': app['version']})['application']
    payload = decision(app, idempotency_key='new-evidence-review')
    failure(409, lambda: service.review_application(users['reviewer'], payload), 'identity_documents_unread')
    doc = next(d for d in app['documents'] if d['kind'] == 'identity_document')
    for current_doc in app['documents']: service.get_document_preview(users['reviewer'], current_doc['id'])
    complete_checklist(service, users['reviewer'], app)
    approved = service.review_application(users['reviewer'], payload)['application']
    assert approved['approval_expires_at'] == '2026-11-02T00:00:00+00:00'


def test_pending_retention_reopens_for_fresh_evidence_and_resubmission(system):
    service, store, users, clock, _ = system
    submitted = ready(system)
    clock[0] += timedelta(days=31)
    maintenance = service.maintenance()
    assert maintenance['reopened_applications'] == 1
    assert maintenance['deleted_documents'] == 2
    reopened = service.get_application(users['alice'])['application']
    assert reopened['status'] == 'needs_changes'
    assert reopened['version'] == submitted['version'] + 1
    assert reopened['documents'] == []
    assert '30 days' in reopened['decision_reason']
    assert service.maintenance()['reopened_applications'] == 0
    failure(409, lambda: service.review_application(users['reviewer'], decision(submitted)), 'identity_version_conflict')
    resubmitted = ready(system, version=reopened['version'])
    approved = service.review_application(users['reviewer'], decision(resubmitted, idempotency_key='review-new-upload'))['application']
    assert approved['status'] == 'approved'
    assert approved['decision_reason'] == 'Checked supplied evidence manually.'
    with store.read() as tx:
        assert tx.get('users', 'alice')['identity_approval']['kind'] == 'human_document_review'


def test_pending_retention_recovery_without_key_still_allows_withdrawal(system):
    service, store, users, clock, _ = system
    submitted = ready(system)
    clock[0] += timedelta(days=31)
    locked = IdentityVerificationService(store, clock=lambda: clock[0])
    reopened = locked.get_application(users['alice'])['application']
    assert reopened['status'] == 'needs_changes'
    assert reopened['version'] == submitted['version'] + 1
    assert reopened['legal_name'] is None
    withdrawn = locked.withdraw_application(users['alice'], {'expected_version': reopened['version']})['application']
    assert withdrawn['status'] == 'withdrawn'
    assert withdrawn['decision_reason'] == ''


@pytest.mark.parametrize('negative', ['rejected', 'revoked'])
def test_explicit_negative_review_overrides_independent_driver_identity(system, negative):
    service, store, users, _, _ = system
    app = ready(system)
    if negative == 'revoked':
        app = service.review_application(users['reviewer'], decision(app))['application']
    independent = {'kind': 'human_document_review', 'source': 'driver_application', 'expires_at': '2028-01-01T00:00:00+00:00'}
    with store.transaction() as tx:
        user = tx.get('users', 'alice')
        user.update(identity_approval=independent, verification={'identity': 'verified'},
                    driver_approved=True, driver_approval={'kind': 'reviewed'})
        tx.put('users', 'alice', user)
    service.review_application(users['reviewer'], decision(app, decision=negative, idempotency_key='negative-review-key'))
    with store.read() as tx:
        user = tx.get('users', 'alice')
        assert user['identity_approval'] is None
        assert user['verification']['identity'] == 'rejected'
    # An ordinary subsequent draft must not resurrect the rejected identity.
    app = service.get_application(users['alice'])['application']
    save(service, users['alice'], app['version'])
    with store.read() as tx:
        assert tx.get('users', 'alice')['identity_approval'] is None
        assert tx.get('users', 'alice')['verification']['identity'] == 'rejected'


def test_corrupt_ciphertext_cannot_be_reviewed_or_approved_and_can_be_withdrawn(system):
    service, store, users, _, _ = system
    app = ready(system)
    doc_id = app['documents'][0]['id']
    with store.transaction() as tx:
        tx._connection.execute('UPDATE identity_document_blobs SET content=? WHERE id=?', (b'corrupted ciphertext', doc_id))
    failure(503, lambda: service.get_document(users['alice'], doc_id), 'identity_unavailable')
    failure(503, lambda: service.review_application(users['reviewer'], decision(app)), 'identity_unavailable')
    with store.read() as tx:
        assert tx.get('users', 'alice').get('identity_approval') is None
        assert tx.list(DECISIONS) == []
    withdrawn = service.withdraw_application(users['alice'], {'expected_version': app['version']})['application']
    assert withdrawn['status'] == 'withdrawn'
    assert withdrawn['documents'] == []


def test_corrupt_encrypted_metadata_does_not_prevent_withdrawal(system):
    service, store, users, _, _ = system
    app = ready(system)
    with store.transaction() as tx:
        row = tx.get(APPLICATIONS, app['id'])
        row['legal_name_encrypted'] = 'corrupt-token'
        tx.put(APPLICATIONS, app['id'], row)
    failure(503, lambda: service.get_application(users['alice']), 'identity_unavailable')
    withdrawn = service.withdraw_application(users['alice'], {'expected_version': app['version']})['application']
    assert withdrawn['status'] == 'withdrawn'
    assert withdrawn['legal_name'] is None


@pytest.mark.parametrize('stored_name', [None, 'corrupt-token'])
@pytest.mark.parametrize('transition', ['submit', 'approve'])
def test_missing_or_corrupt_name_cannot_authorize_identity(system, stored_name, transition):
    service, store, users, _, _ = system
    app = ready(system)
    with store.transaction() as tx:
        row = tx.get(APPLICATIONS, app['id'])
        row['legal_name_encrypted'] = stored_name
        if transition == 'submit':
            row['status'] = 'draft'
        tx.put(APPLICATIONS, app['id'], row)
    action = (lambda: service.submit_application(users['alice'], {'expected_version': app['version']})) if transition == 'submit' else (lambda: service.review_application(users['reviewer'], decision(app)))
    failure(503, action, 'identity_unavailable')
    with store.read() as tx:
        assert tx.get('users', 'alice').get('identity_approval') is None
        assert tx.list(DECISIONS) == []
    withdrawn = service.withdraw_application(users['alice'], {'expected_version': app['version']})['application']
    assert withdrawn['status'] == 'withdrawn'
    assert withdrawn['documents'] == []
