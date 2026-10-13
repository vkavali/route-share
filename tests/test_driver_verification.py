"""Real SQLite application/document/reviewer flows; no external verification claims."""
from tests.review_helpers import complete_checklist
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import base64
import json
import threading

import pytest
from cryptography.fernet import Fernet

from app.driver_verification import (
    APPLICATIONS, DECISIONS, DOCUMENTS, DOCUMENT_ACCESS, MAX_DOCUMENT_BYTES,
    DriverVerificationError, DriverVerificationService,
)
from app.permissions import can_drive
from app.store import Store

UTC = timezone.utc
EVIDENCE_KEY = Fernet.generate_key()
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
PDF = b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / 'verification.sqlite3')
    clock = [datetime(2026, 10, 8, 12, tzinfo=UTC)]
    users = {
        'alice': {'id':'alice', 'role':'member', 'development':False, 'auth_method':'phone', 'auth_phone':'+919876543210', 'phone_verified':True, 'verification':{'phone':'verified'}},
        'bob': {'id':'bob', 'role':'member', 'development':False, 'auth_method':'phone', 'auth_phone':'+919876543211', 'phone_verified':True},
        'reviewer': {'id':'reviewer', 'role':'staff', 'staff_capabilities':['verify.review']},
        'ops': {'id':'ops', 'role':'staff', 'staff_capabilities':['ops.read']},
        'safety': {'id':'safety', 'role':'staff', 'staff_capabilities':['safety.act']},
    }
    with store.transaction() as tx:
        for u in users.values(): tx.put('users',u['id'],u)
    service = DriverVerificationService(store, encryption_key=EVIDENCE_KEY, clock=lambda:clock[0])
    return service,store,users,clock


def draft(service, user, version=0, **changes):
    data = {'legal_name':'Private Applicant Name', 'vehicle':{'model':'Private Car','plate':'ts 01 ab 1234'},
            'adult_attested':True,'planned_trip_attested':True,'document_consent':True,
            'applicant_note':'Private applicant note', 'expected_version':version}
    data.update(changes)
    return service.save_application(user,data)['application']


def ready(system, user_id='alice'):
    service,_store,users,_clock = system
    user = users[user_id]
    app = draft(service,user)
    for kind in ('dl','rc','insurance','selfie'):
        app=service.upload_document(user,kind=kind,expires_on=None if kind=='selfie' else '2026-11-30',
             filename='secret-'+kind+'.png',content=BytesIO(PNG),expected_version=app['version'])['application']
    app=service.submit_application(user,{'expected_version':app['version']})['application']
    for doc in app['documents']:
        service.get_document_preview(users['reviewer'],doc['id'])
    complete_checklist(service, users['reviewer'], app)
    return app


def decision(app, **changes):
    data={'application_id':app['id'],'expected_version':app['version'],'decision':'approved',
          'reason':'Checked supplied evidence manually.',
          'checks':{'dl':True,'rc':True,'insurance':True,'identity_match':True},
          'idempotency_key':'review-key-12345'}
    data.update(changes)
    return data


def error(status, fn, code=None):
    with pytest.raises(DriverVerificationError) as caught:fn()
    assert caught.value.status==status
    if code:assert caught.value.code==code


def test_complete_private_application_review_and_restart(system):
    service,store,users,clock=system
    assert service.get_application(users['alice'])['application'] is None
    app=ready(system)
    assert app['status']=='submitted'
    with store.read() as tx:
        before=tx.get('users','alice')
        assert not can_drive(before,clock[0])
        assert len(tx.list(DOCUMENTS))==4
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==4
        assert 'iVBOR' not in json.dumps(tx.list(DOCUMENTS))
    assert service.verification_queue(users['reviewer'])['applications'][0]['id']==app['id']
    approved=service.review_application(users['reviewer'],decision(app))['application']
    assert approved['status']=='approved'
    assert approved['approval_expires_at']=='2026-12-01T00:00:00+00:00'
    with store.read() as tx:
        user=tx.get('users','alice')
        assert can_drive(user,clock[0])
        assert user['development'] is False
        assert user['driver_approval']['kind'] == 'reviewed'
        assert user['driver_approval']['review_scope']=='human_document_review'
        serialized=json.dumps(user)
        for secret in ('Private Applicant Name','Private applicant note','secret-dl','Checked supplied'):
            assert secret not in serialized
        assert len(tx.list(DECISIONS))==1
        assert tx.list('events')==[]
    restarted=DriverVerificationService(Store(store.path),encryption_key=EVIDENCE_KEY,clock=lambda:clock[0])
    assert restarted.get_application(users['alice'])['application']==approved
    for doc in approved['documents']:
        assert restarted.get_document(users['alice'],doc['id'])['content']==PNG
        error(404, lambda: restarted.get_document(users['reviewer'],doc['id']))
        assert restarted.get_document_preview(users['reviewer'],doc['id'])['image_data_url'].startswith('data:image/jpeg;base64,')


@pytest.mark.parametrize('actor',['bob','ops','safety'])
def test_evidence_only_owner_or_actual_reviewer(system,actor):
    service,_store,users,_clock=system
    app=ready(system)
    error(404,lambda:service.get_document(users[actor],app['documents'][0]['id']))
    error(403,lambda:service.verification_queue(users[actor]))
    error(403,lambda:service.review_application(users[actor],decision(app)))
    if actor=='bob':assert service.get_application(users['bob'])['application'] is None


def test_live_grant_revocation_and_self_review_forbidden(system):
    service,store,users,_clock=system
    app=ready(system)
    with store.transaction() as tx:
        tx.put('users','reviewer',{**users['reviewer'],'staff_capabilities':[]})
    error(403,lambda:service.verification_queue(users['reviewer']))
    error(404,lambda:service.get_document(users['reviewer'],app['documents'][0]['id']))
    error(403,lambda:service.get_document_preview(users['reviewer'],app['documents'][0]['id']))
    with store.transaction() as tx:
        u=tx.get('users','alice');u.update(role='staff',staff_capabilities=['verify.review']);tx.put('users','alice',u)
    error(403,lambda:service.review_application(users['alice'],decision(app)),'verification_self_review')
    error(403,lambda:service.get_application(users['alice']))


def test_unauthenticated_upload_does_not_read_body(system):
    service,*_=system
    class ForbiddenStream:
        def read(self,_):pytest.fail('Unauthenticated file read')
    error(401,lambda:service.upload_document(None,kind='dl',expires_on='2026-12-01',filename='x',
                                            content=ForbiddenStream(),expected_version=0))


@pytest.mark.parametrize('raw,kind',[(b'hello','dl'),(b'\x89PNG\r\n\x1a\n','dl'),
                                    (b'%PDF-1.7\nmissing eof','dl'),(PDF,'selfie'),
                                    (b'\xff\xd8\xfftruncated','selfie')])
def test_invalid_signatures_do_not_persist(system,raw,kind):
    service,store,users,_clock=system
    a=draft(service,users['alice'])
    error(400,lambda:service.upload_document(users['alice'],kind=kind,
          expires_on=None if kind=='selfie' else '2026-12-01',filename='fake.png',content=raw,expected_version=a['version']))
    with store.read() as tx:
        assert tx.list(DOCUMENTS)==[]
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==0


def test_upload_bounds_filename_signature_and_replacement(system):
    service,store,users,_clock=system
    a=draft(service,users['alice'])
    stream=BytesIO(b'x'*(MAX_DOCUMENT_BYTES+100))
    error(413,lambda:service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',
         filename='x',content=stream,expected_version=a['version']))
    assert stream.tell()==MAX_DOCUMENT_BYTES+1
    a=service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',filename='../../evil.exe',
           content=PDF,expected_version=a['version'])['application']
    old=a['documents'][0]['id'];assert a['documents'][0]['filename']=='evil.pdf'
    assert service.get_document(users['alice'],old)['content_type']=='application/pdf'
    a=service.upload_document(users['alice'],kind='dl',expires_on='2026-12-02',filename='new.png',
           content=PNG,expected_version=a['version'])['application']
    assert a['documents'][0]['id']!=old
    error(404,lambda:service.get_document(users['alice'],old))
    with store.read() as tx:
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==1


@pytest.mark.parametrize('value',['2026-02-30','2026-10-07','tomorrow','9999-12-01'])
def test_invalid_or_expired_document_dates(system,value):
    service,_store,users,_clock=system
    a=draft(service,users['alice'])
    error(400,lambda:service.upload_document(users['alice'],kind='dl',expires_on=value,
          filename='x.png',content=PNG,expected_version=a['version']))


def test_missing_consent_evidence_attestation_and_partial_checks_do_not_approve(system):
    service,store,users,_clock=system
    a=draft(service,users['alice'],document_consent=False)
    error(409,lambda:service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',
          filename='x.png',content=PNG,expected_version=a['version']))
    error(409,lambda:service.submit_application(users['alice'],{'expected_version':a['version']}))
    a=draft(service,users['alice'],version=a['version'])
    error(409,lambda:service.submit_application(users['alice'],{'expected_version':a['version']}))
    for kind in ('dl','rc','insurance','selfie'):
        a=service.upload_document(users['alice'],kind=kind,expires_on=None if kind=='selfie' else '2026-11-30',
             filename='x.png',content=PNG,expected_version=a['version'])['application']
    a=draft(service,users['alice'],version=a['version'],adult_attested=False)
    error(409,lambda:service.submit_application(users['alice'],{'expected_version':a['version']}))
    a=draft(service,users['alice'],version=a['version'])
    a=service.submit_application(users['alice'],{'expected_version':a['version']})['application']
    payload=decision(a);payload['checks']['insurance']=False
    error(409,lambda:service.review_application(users['reviewer'],payload))
    with store.read() as tx:assert not tx.get('users','alice')['driver_approved']


def test_versions_retries_changed_payload_and_revocation(system):
    service,store,users,clock=system
    a=ready(system);payload=decision(a)
    approved=service.review_application(users['reviewer'],payload)['application']
    assert service.review_application(users['reviewer'],payload)['application']==approved
    error(409,lambda:service.review_application(users['reviewer'],{**payload,'reason':'A different review explanation'}),
          'verification_idempotency_conflict')
    error(409,lambda:service.review_application(users['reviewer'],{**payload,'idempotency_key':'second-review-key'}),
          'verification_version_conflict')
    revoked=service.review_application(users['reviewer'],decision(approved,decision='revoked',idempotency_key='revoke-review-key'))['application']
    with store.read() as tx:
        assert not can_drive(tx.get('users','alice'),clock[0]);assert len(tx.list(DECISIONS))==2
    # Replaying an old approval never resurrects the approval or returns stale UI state.
    assert service.review_application(users['reviewer'],payload)['application']['status']=='revoked'
    assert revoked['approval_expires_at'] is None


def test_approval_requires_unexpired_docs_at_decision_time(system):
    service,store,users,clock=system
    a=ready(system);clock[0]=datetime(2026,12,1,tzinfo=UTC)
    error(409,lambda:service.review_application(users['reviewer'],decision(a)))
    with store.read() as tx:assert not tx.get('users','alice')['driver_approved']


def test_document_and_aggregate_expiry_fail_closed_without_maintenance(system):
    service,store,users,clock=system
    a=ready(system);service.review_application(users['reviewer'],decision(a))
    with store.read() as tx:u=tx.get('users','alice')
    assert can_drive(u,datetime(2026,11,30,23,59,59,tzinfo=UTC))
    assert not can_drive(u,datetime(2026,12,1,tzinfo=UTC))
    u['driver_approval']['expires_at']='2030-01-01T00:00:00+00:00'
    assert not can_drive(u,datetime(2026,12,1,tzinfo=UTC))
    u['driver_approval']['document_expiries'].pop('rc')
    assert not can_drive(u,clock[0])


def test_retention_deletes_blobs_metadata_and_marks_expired_on_access(system):
    service,store,users,clock=system
    a=ready(system);approved=service.review_application(users['reviewer'],decision(a))['application']
    ids=[d['id'] for d in approved['documents']]
    clock[0]=datetime(2026,12,1,tzinfo=UTC)
    expired=service.get_application(users['alice'])['application']
    assert expired['status']=='expired'
    with store.read() as tx:assert not tx.get('users','alice')['driver_approved']
    clock[0]=datetime(2026,12,31,tzinfo=UTC)
    assert service.maintenance()['deleted_documents']==4
    assert service.maintenance()['deleted_documents']==0
    with store.read() as tx:
        assert tx.list(DOCUMENTS)==[]
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==0
    for identity in ids:error(404,lambda:service.get_document(users['alice'],identity))



@pytest.mark.parametrize('trigger', ['access', 'scheduled'])
def test_submitted_retention_reopens_preserving_documents_and_requires_fresh_review(system, trigger):
    service,store,users,clock=system
    submitted=ready(system)
    retained={d['kind']:d['id'] for d in submitted['documents'] if d['kind']!='selfie'}
    old_selfie=next(d['id'] for d in submitted['documents'] if d['kind']=='selfie')
    with store.read() as tx:
        assert tx.list('document_review_progress')
    clock[0]+=timedelta(days=31)
    if trigger=='scheduled':
        outcome=service.maintenance()
        assert outcome['deleted_documents']==1
        assert outcome['reopened_applications']==1
    reopened=service.get_application(users['alice'])['application']
    assert reopened['status']=='needs_changes'
    assert reopened['version']==submitted['version']+1
    assert 'upload' in reopened['decision_reason'].lower()
    assert {d['kind']:d['id'] for d in reopened['documents']}==retained
    assert service.maintenance()['reopened_applications']==0
    assert service.get_application(users['alice'])['application']==reopened
    with store.read() as tx:
        assert tx.list('document_review_progress')==[]
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==3
        assert not can_drive(tx.get('users','alice'),clock[0])
    error(404,lambda:service.get_document(users['alice'],old_selfie))
    error(409,lambda:service.review_application(users['reviewer'],decision(submitted)),
          'verification_version_conflict')
    error(403,lambda:service.verification_queue(users['ops']))

    corrected=draft(service,users['alice'],version=reopened['version'])
    corrected=service.upload_document(users['alice'],kind='selfie',expires_on=None,
        filename='replacement.png',content=PNG,expected_version=corrected['version'])['application']
    corrected=service.submit_application(users['alice'],{'expected_version':corrected['version']})['application']
    assert {d['kind']:d['id'] for d in corrected['documents'] if d['kind']!='selfie'}==retained
    error(409,lambda:service.review_application(users['reviewer'],decision(corrected)),
          'verification_documents_unread')
    for document in corrected['documents']:
        service.get_document_preview(users['reviewer'],document['id'])
    error(409,lambda:service.review_application(users['reviewer'],decision(corrected)),
          'review_progress_incomplete')
    complete_checklist(service,users['reviewer'],corrected)
    approved=service.review_application(users['reviewer'],decision(corrected))['application']
    assert approved['status']=='approved'
    with store.read() as tx:
        assert can_drive(tx.get('users','alice'),clock[0])


def test_edit_approval_or_withdraw_consent_invalidates_drive_permission(system):
    service,store,users,clock=system
    a=ready(system);a=service.review_application(users['reviewer'],decision(a))['application']
    a=draft(service,users['alice'],version=a['version'],document_consent=False)
    assert a['status']=='draft' and a['documents']==[]
    with store.read() as tx:
        assert not can_drive(tx.get('users','alice'),clock[0])
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==0


def test_simultaneous_approval_only_one_version_transition(system):
    service,store,users,_clock=system
    a=ready(system);barrier=threading.Barrier(2)
    def review(index):
        barrier.wait()
        try:
            return service.review_application(users['reviewer'],decision(a,idempotency_key=f'concurrent-key-{index}'))
        except DriverVerificationError as exc:return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(review,(1,2)))
    assert sum(isinstance(r,dict) for r in results)==1
    assert results.count(409)==1
    with store.read() as tx:assert len(tx.list(DECISIONS))==1


def test_simultaneous_upload_cannot_replace_newer_revision(system):
    service,store,users,_clock=system
    a=draft(service,users['alice']);barrier=threading.Barrier(2)
    def upload(index):
        barrier.wait()
        try:return service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',
                     filename=f'upload-{index}.png',content=PNG,expected_version=a['version'])
        except DriverVerificationError as exc:return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(upload,(1,2)))
    assert sum(isinstance(r,dict) for r in results)==1 and results.count(409)==1
    with store.read() as tx:
        assert len(tx.list(DOCUMENTS))==1
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==1


def test_transaction_failure_rolls_back_document_and_blob(system,monkeypatch):
    service,store,users,_clock=system
    a=draft(service,users['alice'])
    original=service._invalidate_user
    def fail(*_args,**_kwargs):raise RuntimeError('test transaction rollback')
    monkeypatch.setattr(service,'_invalidate_user',fail)
    with pytest.raises(RuntimeError):
        service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',filename='x.png',content=PNG,expected_version=a['version'])
    monkeypatch.setattr(service,'_invalidate_user',original)
    with store.read() as tx:
        assert tx.list(DOCUMENTS)==[]
        assert tx._connection.execute('SELECT count(*) FROM driver_document_blobs').fetchone()[0]==0
        assert tx.get(APPLICATIONS,a['id'])['version']==a['version']


def test_current_evidence_must_be_retrieved_by_deciding_reviewer(system):
    service,store,users,_clock=system
    app=ready(system)
    other={'id':'other-reviewer','role':'staff','staff_capabilities':['verify.review']}
    with store.transaction() as tx:tx.put('users',other['id'],other)
    error(409,lambda:service.review_application(other,decision(app)),'verification_documents_unread')
    for doc in app['documents'][:-1]:service.get_document_preview(other,doc['id'])
    error(409,lambda:service.review_application(other,decision(app)),'verification_documents_unread')
    service.get_document_preview(other,app['documents'][-1]['id'])
    complete_checklist(service, other, app)
    assert service.review_application(other,decision(app))['application']['status']=='approved'


def test_replacing_evidence_requires_new_reviewer_access(system):
    service,store,users,_clock=system
    app=ready(system)
    app=service.review_application(users['reviewer'],decision(app,decision='needs_changes'))['application']
    old=next(d['id'] for d in app['documents'] if d['kind']=='dl')
    app=service.upload_document(users['alice'],kind='dl',expires_on='2026-12-01',filename='new.png',
           content=PNG,expected_version=app['version'])['application']
    app=service.submit_application(users['alice'],{'expected_version':app['version']})['application']
    payload=decision(app,idempotency_key='second-decision-key')
    error(409,lambda:service.review_application(users['reviewer'],payload),'verification_documents_unread')
    with store.read() as tx:assert old not in {row['document_id'] for row in tx.list(DOCUMENT_ACCESS)}
    new=next(d['id'] for d in app['documents'] if d['kind']=='dl')
    for doc in app['documents']: service.get_document_preview(users['reviewer'],doc['id'])
    complete_checklist(service, users['reviewer'], app)
    assert service.review_application(users['reviewer'],payload)['application']['status']=='approved'


@pytest.mark.parametrize("approved", [1, "true", "false", [], {}, None, False])
def test_non_boolean_approval_fails_closed(approved):
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    user = {"role":"member", "development":True, "driver_approved":approved,
            "driver_approval":{"kind":"development", "expires_at":future}}
    assert can_drive(user) is False


@pytest.mark.parametrize("verification", [[], ["verified"], "verified", 1, None])
def test_malformed_review_status_fails_closed(verification):
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    user = {"role":"member", "driver_approved":True, "verification":verification,
            "driver_approval":{"kind":"reviewed", "expires_at":future,
                               "document_expiries":dict.fromkeys(("dl","rc","insurance"), future)}}
    assert can_drive(user) is False


@pytest.mark.parametrize("decision_value", [[], {}, None, True, 1])
def test_malformed_decision_is_validation_error(system, decision_value):
    service, _, users, _ = system
    error(400, lambda: service.review_application(users["reviewer"], {
        "application_id":"unneeded", "decision":decision_value}))


def test_draft_repairs_malformed_legacy_status_without_claiming_approval(system):
    service, store, users, _ = system
    with store.transaction() as tx:
        user = tx.get("users", "alice")
        user["verification"] = ["invalid legacy field"]
        tx.put("users", "alice", user)
    draft(service, users["alice"])
    with store.read() as tx:
        user = tx.get("users", "alice")
        assert not can_drive(user)
        assert user["verification"]["dl"] == "not_checked"


def test_submitted_applicant_can_withdraw_evidence_before_staff_decision(system):
    service, store, users, _ = system
    app = ready(system)
    docs = list(app['documents'])
    old_decision = decision(app)
    withdrawn = draft(service, users['alice'], app['version'], document_consent=False)
    assert withdrawn['status'] == 'draft' and withdrawn['documents'] == []
    assert withdrawn['document_consent'] is False and withdrawn['version'] == app['version'] + 1
    error(409, lambda: service.review_application(users['reviewer'], old_decision),
          'verification_version_conflict')
    for document in docs:
        error(404, lambda: service.get_document_preview(users['reviewer'], document['id']))
    with store.read() as tx:
        assert tx.list(DOCUMENTS) == []
        assert tx.list(DOCUMENT_ACCESS) == []
        assert tx._connection.execute('SELECT COUNT(*) FROM driver_document_blobs').fetchone()[0] == 0
        assert not can_drive(tx.get('users', 'alice'))
