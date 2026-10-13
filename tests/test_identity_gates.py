"""Synthetic reviewed identities; no government API or real evidence claim."""
from tests.review_helpers import complete_checklist
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.domain import DomainError
from app.permissions import can_request, can_drive, has_current_identity_review, identity_review_summary
from app.user_projection import account_user
from app.reviews import _verification
from app.driver_verification import DriverVerificationService
from app.payments import PaymentService, PaymentError
from test_lifecycle import make_service, act, publish, search, KONDAPUR, VIJAYAWADA, SURYAPET, NANDIGAMA
from test_driver_verification import system, ready, decision

UTC = timezone.utc


def identity(at=None, days=30, source='identity_application'):
    at = at or datetime.now(UTC)
    return {'kind':'human_document_review','source':source,'application_id':'PRIVATE-APPLICATION-ID',
            'reviewed_at':at.isoformat(),'expires_at':(at+timedelta(days=days)).isoformat()}


def individual(at=None):
    return {'id':'real','role':'member','development':False,'auth_method':'phone',
            'auth_phone':'+919876543210','phone_verified':True,'identity_approval':identity(at)}


def real_service(tmp_path):
    service, store, users, router = make_service(tmp_path)
    stamp = datetime.now(UTC)
    expiry = (stamp + timedelta(days=60)).isoformat()
    with store.transaction() as tx:
        for index, (key, user) in enumerate(users.items()):
            if user.get('role') != 'member': continue
            user.update(development=False, auth_method='phone', auth_phone=f'+9198765432{index:02}',
                        phone_verified=True, identity_approval=identity(stamp))
            if key.startswith('driver'):
                user.update(driver_approved=True,driver_approval={'kind':'reviewed','expires_at':expiry,
                    'document_expiries':dict.fromkeys(('dl','rc','insurance'),expiry)},
                    verification=dict.fromkeys(('dl','rc','insurance','selfie','identity'),'verified'))
            tx.put('users',key,user)
    return service,store,users,router


def pending(tmp_path):
    service, store, users, router = real_service(tmp_path)
    _, trip = publish(service, users['driver'], KONDAPUR, VIJAYAWADA, seats=2)
    found = search(service, users['passenger'], SURYAPET, NANDIGAMA, trip['departure'])
    booking = act(service,'request',users['passenger'],match_id=found['matches'][0]['id'])['booking']
    return service,store,users,router,trip,booking


def revoke(store, who='passenger', expired=False):
    with store.transaction() as tx:
        user = tx.get('users', who)
        user['identity_approval'] = identity(datetime.now(UTC)-timedelta(days=31)) if expired else None
        user['verification'] = {**user.get('verification',{}),'identity':'verified'}  # Stale legacy badge cannot grant access.
        tx.put('users',who,user)


@pytest.mark.parametrize('change', [
    {'identity_approval':None}, {'development':True}, {'account_status':'closed'}, {'role':'staff'},
    {'identity_approval':{'kind':'human_document_review'}},
])
def test_current_review_is_not_a_legacy_flag(change):
    user=individual();user.update(verification={'identity':'verified'},**change)
    assert not has_current_identity_review(user)


@pytest.mark.parametrize('field,value', [('kind','verified'),('source','unknown'),('application_id',''),
    ('reviewed_at','2026-01-01'),('expires_at','bad')])
def test_malformed_approval_fails_closed(field,value):
    user=individual();user['identity_approval'][field]=value
    assert not has_current_identity_review(user)
    assert identity_review_summary(user)['status']=='not_checked'


def test_review_time_window_is_bounded_and_summary_allowlisted():
    at=datetime.now(UTC);user=individual(at)
    assert has_current_identity_review(user,at) and can_request(user,at)
    assert not has_current_identity_review(user,at-timedelta(microseconds=1))
    expiry=at+timedelta(days=30)
    assert not has_current_identity_review(user,expiry)
    assert identity_review_summary(user,expiry)['status']=='expired'
    user['identity_approval']=identity(at,366)
    assert not has_current_identity_review(user,at)
    user['identity_approval']=identity(at)
    own=account_user(user)
    assert set(own['identity_review'])=={'status','method','expires_at'}
    assert own['access']['can_request'] is True
    assert 'PRIVATE-APPLICATION-ID' not in json.dumps(own) and 'auth_phone' not in own and 'identity_approval' not in own
    user['identity_approval']=None
    assert _verification(user)['checks']['identity']=='not_checked'
    user['development']=True;user['verification']={'identity':'verified','dl':'verified'}
    assert identity_review_summary(user)['status']=='development'
    assert all(value!='verified' for value in _verification(user)['checks'].values())


@pytest.mark.parametrize('change',[{'phone_verified':False},{'auth_method':'password'},{'auth_phone':'invalid'}])
def test_real_request_requires_verified_phone_too(change):
    user=individual();user.update(change)
    assert not can_request(user)


def test_unreviewed_cannot_request_approved_can_and_expiry_allows_cancellation(tmp_path):
    service,store,users,_=real_service(tmp_path)
    _,trip=publish(service,users['driver'],KONDAPUR,VIJAYAWADA)
    found=search(service,users['passenger'],SURYAPET,NANDIGAMA,trip['departure'])
    revoke(store)
    with pytest.raises(DomainError) as error: act(service,'request',users['passenger'],match_id=found['matches'][0]['id'])
    assert error.value.status==403
    with store.transaction() as tx:
        user=tx.get('users','passenger');user['identity_approval']=identity();tx.put('users','passenger',user)
    booked=act(service,'request',users['passenger'],match_id=found['matches'][0]['id'])['booking']
    revoke(store,expired=True)
    assert act(service,'cancel_booking',users['passenger'],booking_id=booked['id'],reason='Cannot travel')['booking']['status']=='cancelled'


@pytest.mark.parametrize('expired',[False,True])
def test_accept_and_start_recheck_persisted_passenger(tmp_path,expired):
    service,store,users,_,trip,booking=pending(tmp_path)
    revoke(store,expired=expired)
    with pytest.raises(DomainError) as error: act(service,'accept',users['driver'],booking_id=booking['id'])
    assert error.value.status==409
    with store.transaction() as tx:
        user=tx.get('users','passenger');user['identity_approval']=identity();tx.put('users','passenger',user)
    act(service,'accept',users['driver'],booking_id=booking['id'])
    revoke(store,expired=expired)
    with pytest.raises(DomainError) as error: act(service,'start_trip',users['driver'],trip_id=trip['id'])
    assert error.value.status==409
    with store.read() as tx: assert tx.get('trips',trip['id'])['status']=='published'
    assert act(service,'cancel_trip',users['driver'],trip_id=trip['id'],reason='Identity review expired')['trip']['status']=='cancelled'


def test_accept_rechecks_clock_after_routing(tmp_path,monkeypatch):
    service,store,users,router,trip,booking=pending(tmp_path)
    import app.permissions as permissions
    at=datetime.now(UTC)
    with store.transaction() as tx:
        user=tx.get('users','passenger');user['identity_approval']=identity(at-timedelta(days=29));tx.put('users','passenger',user)
    original=service.router.route
    class Later(datetime):
        @classmethod
        def now(cls,tz=None): return at+timedelta(days=2)
    def delayed(points):
        result=original(points)
        monkeypatch.setattr(permissions,'datetime',Later)
        return result
    monkeypatch.setattr(service.router,'route',delayed)
    with pytest.raises(DomainError) as error: act(service,'accept',users['driver'],booking_id=booking['id'])
    assert error.value.status==409
    with store.read() as tx: assert tx.get('bookings',booking['id'])['status']=='pending'


def test_demo_requests_still_work_only_in_isolated_pool(tmp_path):
    service,store,users,_=make_service(tmp_path)
    assert can_request(users['passenger']) and not has_current_identity_review(users['passenger'])
    _,trip=publish(service,users['driver'],KONDAPUR,VIJAYAWADA)
    found=search(service,users['passenger'],SURYAPET,NANDIGAMA,trip['departure'])
    with store.transaction() as tx:
        user=tx.get('users','passenger');user.update(individual(),id='passenger');tx.put('users','passenger',user)
    with pytest.raises(DomainError): act(service,'request',users['passenger'],match_id=found['matches'][0]['id'])


def test_completion_remains_available_after_identity_expiry(tmp_path):
    service,store,users,_,trip,booking=pending(tmp_path)
    act(service,'accept',users['driver'],booking_id=booking['id'])
    act(service,'start_trip',users['driver'],trip_id=trip['id'])
    revoke(store);revoke(store,'driver')
    assert act(service,'complete_segment',users['passenger'],booking_id=booking['id'])['booking']['status']=='segment_completed'
    assert act(service,'complete_trip',users['driver'],trip_id=trip['id'])['trip']['status']=='completed'


def test_driver_review_issues_bounded_identity_and_only_its_approval_is_invalidated(system):
    service,store,users,clock=system
    app=ready(system)
    service.review_application(users['reviewer'],decision(app))
    with store.read() as tx:
        user=tx.get('users','alice');approval=user['identity_approval']
        assert approval['kind']=='human_document_review' and approval['source']=='driver_application'
        assert has_current_identity_review(user,clock[0]) and can_drive(user,clock[0])
        assert datetime.fromisoformat(approval['expires_at'])<=clock[0]+timedelta(days=365)
    with store.transaction() as tx: DriverVerificationService._invalidate_user(tx,'alice')
    with store.read() as tx: assert tx.get('users','alice')['identity_approval'] is None


def test_driver_renewal_preserves_independent_identity_review(system):
    service,store,users,clock=system
    independent=identity(clock[0],days=200)
    with store.transaction() as tx:
        user=tx.get('users','alice');user['identity_approval']=independent;tx.put('users','alice',user)
    app=ready(system)
    service.review_application(users['reviewer'],decision(app))
    with store.read() as tx: assert tx.get('users','alice')['identity_approval']==independent
    with store.transaction() as tx: DriverVerificationService._invalidate_user(tx,'alice')
    with store.read() as tx:
        user=tx.get('users','alice')
        assert user['identity_approval']==independent and has_current_identity_review(user,clock[0])
        assert not can_drive(user,clock[0])


def test_new_payments_require_both_reviews_but_existing_reconciliation_survives(tmp_path):
    service,store,users,_,trip,booking=pending(tmp_path)
    act(service,'accept',users['driver'],booking_id=booking['id'])
    payments=PaymentService(store,enabled=True)
    payments.dispatch('trip_budget_action',users['driver'],{'trip_id':trip['id'],'action':'set_budget','expected_version':0,
        'idempotency_key':'budget','fuel_paise':10000,'toll_paise':0,'owner_share_paise':5000,'reason':'Owner estimate'})
    payload={'booking_id':booking['id'],'action':'propose','expected_version':0,'idempotency_key':'quote','amount_paise':1000,
             'breakdown':{'fuel_paise':1000,'toll_paise':0},'payee_name':'Synthetic owner','upi_id':'fixture@bank'}
    revoke(store)
    with pytest.raises(PaymentError):payments.dispatch('payment_action',users['driver'],payload)
    assert payments.dispatch('payment',users['driver'],{'booking_id':booking['id']})['payment']['collection_eligibility']['reason']=='identity_review_required'
    with store.transaction() as tx:
        user=tx.get('users','passenger');user['identity_approval']=identity();tx.put('users','passenger',user)
    payments.dispatch('payment_action',users['driver'],payload)
    def action(role,name,version):
        return payments.dispatch('payment_action',users[role],{'booking_id':booking['id'],'action':name,'expected_version':version,'idempotency_key':name})['payment']
    assert action('passenger','agree',1)['upi_uri']
    revoke(store);revoke(store,'driver')
    assert payments.dispatch('payment',users['passenger'],{'booking_id':booking['id']})['payment']['upi_uri'] is None
    action('passenger','report_paid',2);action('driver','confirm_received',3)
    action('passenger','request_refund',4);action('driver','report_refund',5)
    assert action('passenger','confirm_refund',6)['status']=='refunded'


@pytest.mark.parametrize('dl_days',[180,730])
def test_driver_identity_expiry_uses_dl_and_year_bound_not_rc(system,dl_days):
    from io import BytesIO
    from test_driver_verification import draft, PNG
    service,store,users,clock=system
    app=draft(service,users['alice'])
    dates={'dl':(clock[0]+timedelta(days=dl_days)).date().isoformat(),
           'rc':(clock[0]+timedelta(days=2)).date().isoformat(),
           'insurance':(clock[0]+timedelta(days=10)).date().isoformat()}
    for kind in ('dl','rc','insurance','selfie'):
        app=service.upload_document(users['alice'],kind=kind,expires_on=dates.get(kind),filename='fixture.png',
            content=BytesIO(PNG),expected_version=app['version'])['application']
    app=service.submit_application(users['alice'],{'expected_version':app['version']})['application']
    for doc in app['documents']: service.get_document_preview(users['reviewer'],doc['id'])
    complete_checklist(service, users['reviewer'], app)
    service.review_application(users['reviewer'],decision(app))
    with store.read() as tx:
        user=tx.get('users','alice')
        expiry=datetime.fromisoformat(user['identity_approval']['expires_at'])
        dl_expiry=datetime.fromisoformat(user['driver_approval']['document_expiries']['dl'])
        assert expiry==min(clock[0]+timedelta(days=365),dl_expiry)
        assert expiry>datetime.fromisoformat(user['driver_approval']['expires_at'])


def test_human_reviewed_demo_keeps_document_expiry_without_real_identity(system):
    service,store,users,clock=system
    with store.transaction() as tx:
        user=tx.get('users','alice');user['development']=True;tx.put('users','alice',user)
    app=ready(system);service.review_application(users['reviewer'],decision(app))
    with store.read() as tx: user=tx.get('users','alice')
    assert user['driver_approval']['kind']=='development' and can_drive(user,clock[0])
    assert not has_current_identity_review(user,clock[0])
    assert identity_review_summary(user,clock[0])['status']=='development'
    user['driver_approval']['expires_at']=(clock[0]+timedelta(days=700)).isoformat()
    assert not can_drive(user,datetime(2026,12,1,tzinfo=UTC))


def test_real_driver_review_requires_phone_signin(system):
    from app.driver_verification import DriverVerificationError
    service,store,users,_=system
    app=ready(system)
    with store.transaction() as tx:
        user=tx.get('users','alice');user['phone_verified']=False;tx.put('users','alice',user)
    with pytest.raises(DriverVerificationError) as error: service.review_application(users['reviewer'],decision(app))
    assert error.value.code=='verified_phone_required'


def test_request_rechecks_identity_between_dispatch_and_commit(tmp_path,monkeypatch):
    service,store,users,_=real_service(tmp_path)
    _,trip=publish(service,users['driver'],KONDAPUR,VIJAYAWADA)
    found=search(service,users['passenger'],SURYAPET,NANDIGAMA,trip['departure'])
    original=service._request
    def changed(user,payload):
        revoke(store)
        return original(user,payload)
    monkeypatch.setattr(service,'_request',changed)
    with pytest.raises(DomainError) as error: act(service,'request',users['passenger'],match_id=found['matches'][0]['id'])
    assert error.value.status==403
    with store.read() as tx: assert not tx.list('bookings')


def test_start_checks_every_accepted_passenger(tmp_path):
    service,store,users,_,trip,first=pending(tmp_path)
    act(service,'accept',users['driver'],booking_id=first['id'])
    found=search(service,users['passenger2'],SURYAPET,NANDIGAMA,trip['departure'])
    second=act(service,'request',users['passenger2'],match_id=found['matches'][0]['id'])['booking']
    act(service,'accept',users['driver'],booking_id=second['id'])
    revoke(store,'passenger2')
    with pytest.raises(DomainError): act(service,'start_trip',users['driver'],trip_id=trip['id'])
    with store.read() as tx:
        assert tx.get('trips',trip['id'])['status']=='published'
        assert tx.get('bookings',first['id'])['status']=='accepted'


def test_public_summary_expiry_and_no_evidence_metadata(tmp_path):
    service,store,users,_=real_service(tmp_path)
    summary=service.community.public_summary('passenger')
    assert summary['identity_review']['status']=='reviewed'
    assert summary['verification']['identity']=='verified'
    assert 'PRIVATE-APPLICATION-ID' not in json.dumps(summary) and 'auth_phone' not in summary
    revoke(store,expired=True)
    summary=service.community.public_summary('passenger')
    assert summary['identity_review']['status']=='expired'
    assert summary['verification']['identity']=='expired'
