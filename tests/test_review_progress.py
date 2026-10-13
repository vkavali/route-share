"""Real persisted sequential review, protected page receipts and stale-tab guards."""
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from app import review_progress as rp
from app.driver_verification import DriverVerificationError
from app.identity_verification import IdentityVerificationError, delete_user_evidence
from tests.test_document_preview import case
from tests.review_helpers import complete_checklist

ERRORS = (DriverVerificationError, IdentityVerificationError)


def payload(app, progress, index=0, checks=None):
    step = progress['steps'][index]
    return dict(application_id=app['id'], expected_version=app['version'],
                expected_revision=progress['revision'], step=step['key'],
                checks=checks if checks is not None else dict.fromkeys(step['checks'], True))


def inspect(service, staff, app):
    for doc in app['documents']:
        result = service.get_document_preview(staff, doc['id'])
        for page in range(2, result['page_count'] + 1):
            service.get_document_preview(staff, doc['id'], page)


def denied(code, fn):
    with pytest.raises(ERRORS) as caught: fn()
    assert caught.value.code == code
    return caught.value


def decision(kind, app, choice='approved'):
    checks = {field: True for _, fields in rp.SCHEMAS[kind] for field in fields}
    return dict(application_id=app['id'], expected_version=app['version'], decision=choice,
                checks=checks, reason='Synthetic staff inspection complete.', idempotency_key='review-progress-test')


def test_initial_read_is_nonmutating_and_strict_safe_projection(case):
    kind, store, service, owner, staff, outsider, app = case
    first = service.get_review_progress(staff, app['id'])
    assert first == service.get_review_progress(staff, app['id'])
    assert set(first) == {'application_id', 'application_version', 'revision', 'steps', 'current_step', 'ready_for_approval'}
    assert first['revision'] == 0 and not first['ready_for_approval']
    assert [s['key'] for s in first['steps']] == [key for key, _ in rp.SCHEMAS[kind]]
    assert first['current_step'] == first['steps'][0]['key']
    for step in first['steps']:
        assert set(step) == {'key', 'document_id', 'checks', 'complete'}
        assert not step['complete'] and not any(step['checks'].values())
    with store.read() as tx: assert tx.list(rp.COLLECTION) == []
    for user in (owner, outsider):
        with pytest.raises(ERRORS) as caught: service.get_review_progress(user, app['id'])
        assert caught.value.status == 403


def test_sequential_pages_partial_saves_and_two_tab_conflict(case):
    kind, store, service, owner, staff, outsider, app = case
    p = service.get_review_progress(staff, app['id'])
    denied('review_progress_step_locked', lambda: service.save_review_progress(staff, payload(app,p,1)))
    denied('review_progress_documents_unread', lambda: service.save_review_progress(staff,payload(app,p)))
    # A reviewer may save negative/unfinished answers without claiming inspection.
    p = service.save_review_progress(staff,payload(app,p,checks=dict.fromkeys(p['steps'][0]['checks'],False)))
    assert p['revision'] == 1 and p['current_step'] == p['steps'][0]['key']
    service.get_document_preview(staff,p['steps'][0]['document_id'],1)
    denied('review_progress_documents_unread', lambda: service.save_review_progress(staff,payload(app,p)))
    service.get_document_preview(staff,p['steps'][0]['document_id'],2)
    old = payload(app,p)
    p = service.save_review_progress(staff,old)
    assert p['revision'] == 2 and p['current_step'] == p['steps'][1]['key']
    denied('review_progress_revision_conflict', lambda: service.save_review_progress(staff,old))
    with store.read() as tx:
        assert tx.get(kind+'_applications',app['id'])['version'] == app['version']
        row = tx.list(rp.COLLECTION)[0]
        assert row['steps'][p['steps'][0]['key']]['completed_at']
        assert 'image_data_url' not in json.dumps(row)


def test_approval_requires_saved_checks_and_negative_resets_later_audit_survives(case):
    kind,store,service,owner,staff,outsider,app=case
    inspect(service,staff,app)
    denied('review_progress_incomplete',lambda:service.review_application(staff,decision(kind,app)))
    p=complete_checklist(service,staff,app)
    assert p['ready_for_approval'] and p['current_step'] is None
    values=dict.fromkeys(p['steps'][0]['checks'],True)
    values[next(iter(values))]=False
    p=service.save_review_progress(staff,payload(app,p,checks=values))
    assert not p['ready_for_approval'] and p['steps'][0]['checks']==values
    assert all(not any(step['checks'].values()) for step in p['steps'][1:])
    denied('review_progress_step_locked',lambda:service.save_review_progress(staff,payload(app,p,1)))
    denied('review_progress_incomplete',lambda:service.review_application(staff,decision(kind,app)))
    p=complete_checklist(service,staff,app)
    assert service.review_application(staff,decision(kind,app))['application']['status']=='approved'
    with store.read() as tx:
        assert tx.list(rp.COLLECTION)==[]
        snapshot=tx.list(kind+'_review_decisions')[0]['review_checklist']
        assert snapshot['revision']==p['revision'] and snapshot['application_version']==app['version']
        assert all(step['completed_at'] for step in snapshot['steps'].values())


def test_reviewers_independent_and_progress_persists_reloaded_service(case):
    kind,store,service,owner,staff,outsider,app=case
    other={**staff,'id':'other-reviewer'}
    with store.transaction() as tx:tx.put('users',other['id'],other)
    inspect(service,staff,app);complete_checklist(service,staff,app)
    assert service.get_review_progress(other,app['id'])['revision']==0
    inspect(service,other,app)
    denied('review_progress_incomplete',lambda:service.review_application(other,decision(kind,app)))
    # A fresh service object uses the same persisted records, never a client-local flag.
    kwargs={'clock':service.clock}
    if kind=='identity':
        # Reuse configured cipher for this service reload without changing storage keys.
        fresh=type(service).__new__(type(service));fresh.__dict__.update(service.__dict__)
    else:fresh=type(service)(store,**kwargs)
    assert fresh.get_review_progress(staff,app['id'])['ready_for_approval']
    with store.transaction() as tx:delete_user_evidence(tx,staff['id'])
    assert service.get_review_progress(staff,app['id'])['revision']==0


@pytest.mark.parametrize('mutation', ['extra','missing','boolversion','negative','unknownstep','extracheck','stringcheck'])
def test_strict_payload(case,mutation):
    kind,store,service,owner,staff,outsider,app=case
    p=service.get_review_progress(staff,app['id']);body=payload(app,p)
    if mutation=='extra':body['ready_for_approval']=True
    elif mutation=='missing':body.pop('expected_revision')
    elif mutation=='boolversion':body['expected_version']=True
    elif mutation=='negative':body['expected_revision']=-1
    elif mutation=='unknownstep':body['step']='anything'
    elif mutation=='extracheck':body['checks']['unknown']=True
    else:body['checks'][next(iter(body['checks']))]='true'
    denied('review_progress_invalid',lambda:service.save_review_progress(staff,body))
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]


@pytest.mark.parametrize('change',['grant','epoch','target','self'])
def test_live_access_rechecked_for_saved_and_read_progress(case,change):
    kind,store,service,owner,staff,outsider,app=case
    p=service.get_review_progress(staff,app['id']);body=payload(app,p,checks=dict.fromkeys(p['steps'][0]['checks'],False))
    with store.transaction() as tx:
        user=tx.get('users',owner['id'] if change=='target' else staff['id'])
        if change=='grant':user['staff_capabilities']=[]
        elif change=='epoch':user['auth_epoch']=44
        elif change=='target':user['account_status']='disabled'
        else:
            current=tx.get(kind+'_applications',app['id']);current['user_id']=staff['id'];tx.put(kind+'_applications',app['id'],current)
        tx.put('users',user['id'],user)
    for fn in (lambda:service.get_review_progress(staff,app['id']),lambda:service.save_review_progress(staff,body)):
        with pytest.raises(ERRORS):fn()
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]


def test_two_concurrent_saves_one_wins_and_negative_decision_cleans_progress(case):
    kind,store,service,owner,staff,outsider,app=case
    p=service.get_review_progress(staff,app['id']);body=payload(app,p,checks=dict.fromkeys(p['steps'][0]['checks'],False))
    def save():
        try:return service.save_review_progress(staff,body)['revision']
        except ERRORS as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(lambda _:save(),range(2)))
    assert sorted(map(str,result))==['1','review_progress_revision_conflict']
    updated=service.review_application(staff,decision(kind,app,'needs_changes'))['application']
    assert updated['status']=='needs_changes'
    denied('review_progress_version_conflict',lambda:service.save_review_progress(staff,body))
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]
    denied('review_progress_locked',lambda:service.get_review_progress(staff,app['id']))


def test_owner_evidence_deletion_cleans_both_namespaces(case):
    kind,store,service,owner,staff,outsider,app=case
    p=service.get_review_progress(staff,app['id'])
    service.save_review_progress(staff,payload(app,p,checks=dict.fromkeys(p['steps'][0]['checks'],False)))
    with store.transaction() as tx:delete_user_evidence(tx,owner['id'])
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]


def test_applicant_deactivated_after_checklist_cannot_receive_final_approval(case):
    kind,store,service,owner,staff,outsider,app=case
    inspect(service,staff,app);complete_checklist(service,staff,app)
    with store.transaction() as tx:
        target=tx.get('users',owner['id']);target['account_status']='disabled';tx.put('users',owner['id'],target)
    with pytest.raises(ERRORS) as caught:service.review_application(staff,decision(kind,app))
    assert caught.value.status==409
    with store.read() as tx:
        assert tx.get(kind+'_applications',app['id'])['status']=='submitted'
        assert tx.list(kind+'_review_decisions')==[]


def test_changed_evidence_resets_revision_and_requires_new_inspection(case):
    from tests.test_document_preview import image_bytes
    kind,store,service,owner,staff,outsider,app=case
    inspect(service,staff,app);old=complete_checklist(service,staff,app)
    changed=service.review_application(staff,decision(kind,app,'needs_changes'))['application']
    first=rp.SCHEMAS[kind][0][0]
    changed=service.upload_document(owner,kind=first,expires_on='2027-02-01',filename='replacement.png',
        content=image_bytes(),expected_version=changed['version'])['application']
    changed=service.submit_application(owner,{'expected_version':changed['version']})['application']
    denied('review_progress_version_conflict',lambda:service.save_review_progress(staff,payload(app,old)))
    fresh=service.get_review_progress(staff,changed['id'])
    assert fresh['revision']==0 and not any(s['complete'] for s in fresh['steps'])
    assert fresh['steps'][0]['document_id']!=old['steps'][0]['document_id']
    denied('review_progress_documents_unread',lambda:service.save_review_progress(staff,payload(changed,fresh)))
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]


def test_withdrawal_deletes_progress_and_locks_reads(case):
    kind,store,service,owner,staff,outsider,app=case
    p=service.get_review_progress(staff,app['id'])
    service.save_review_progress(staff,payload(app,p,checks=dict.fromkeys(p['steps'][0]['checks'],False)))
    if kind=='identity':service.withdraw_application(owner,{'expected_version':app['version']})
    else:service.save_application(owner,dict(legal_name='Synthetic Applicant',vehicle={'model':'Synthetic','plate':'TS01AB1234'},
        adult_attested=True,planned_trip_attested=True,document_consent=False,expected_version=app['version']))
    with store.read() as tx:assert tx.list(rp.COLLECTION)==[]
    denied('review_progress_locked',lambda:service.get_review_progress(staff,app['id']))
