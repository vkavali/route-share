"""Completed-trip review integrity and explicit public-comment consent."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.domain import DomainError
from app.reviews import ReviewsError, ReviewsService
from test_lifecycle import make_service


@pytest.fixture
def setup(tmp_path):
    domain, store, users, _ = make_service(tmp_path)
    for key, name in [('driver','Driver Full Name'),('passenger','Meera Private Surname'),('passenger2','Ravi Other Surname')]:
        users[key].update(name=name,phone='+919876543210',password_hash='PRIVATE-HASH')
    with store.transaction() as tx:
        for key in users:
            tx.put('users',key,users[key])
    return domain, store, users, ReviewsService(store)


def completed(setup, number=1, passenger='passenger', driver='driver', trip_status='completed', booking_status='segment_completed'):
    _, store, _, _ = setup
    trip={'id':f't{number}','driver_id':driver,'status':trip_status,'origin':{'label':'PRIVATE OWNER START'},'destination':{'label':'PRIVATE OWNER END'}}
    booking={'id':f'b{number}','trip_id':trip['id'],'driver_id':driver,'passenger_id':passenger,'status':booking_status,
             'pickup':{'label':'My pickup','lat':17.1,'lon':79.1,'private_extra':'not projected'},
             'dropoff':{'label':'My dropoff','lat':17.2,'lon':79.2},'seats':1}
    with store.transaction() as tx:
        tx.put('trips',trip['id'],trip);tx.put('bookings',booking['id'],booking)
    return booking


def rate(setup, booking, author='passenger', **extra):
    domain, _, users, _ = setup
    return domain.dispatch('rate',users[author],{'booking_id':booking['id'],'stars':4,'comment':'private by default',**extra})['rating']


def profile(setup, viewer='other', target='driver'):
    return setup[3].dispatch('driver_profile',setup[2][viewer],{'user_id':target})


def test_private_history_eligible_participant_fields_and_empty_state(setup):
    _,_,users,reviews=setup
    assert reviews.dispatch('reviews',users['other'],{}) == {'given':[],'received':[],'eligible':[]}
    booking=completed(setup)
    eligible=reviews.dispatch('reviews',users['passenger'],{})['eligible']
    assert eligible == [{'booking_id':'b1','subject_id':'driver','subject_name':'Driver Full Name',
                         'origin':{'label':'My pickup','lat':17.1,'lon':79.1},'destination':{'label':'My dropoff','lat':17.2,'lon':79.2}}]
    rating=rate(setup,booking)
    given=reviews.dispatch('reviews',users['passenger'],{})
    received=reviews.dispatch('reviews',users['driver'],{})
    assert given['eligible']==[] and given['received']==[]
    assert received['received']==given['given']
    assert len(received['eligible'])==1  # Driver can independently review passenger.
    row=given['given'][0]
    assert set(row)=={'id','booking_id','stars','comment','created_at','author_name','subject_name','subject_id','publish_comment'}
    assert row['comment']=='private by default' and row['publish_comment'] is False
    assert 'PRIVATE' not in json.dumps(given)


def test_public_profile_consent_first_name_and_no_sensitive_fields(setup):
    booking=completed(setup)
    rate(setup,booking,comment='PUBLIC CONSENTED COMMENT',publish_comment=True)
    data=profile(setup)
    assert data['reviews'][0]['comment']=='PUBLIC CONSENTED COMMENT'
    assert data['reviews'][0]['author_name']=='Meera'
    assert set(data['reviews'][0])=={'author_name','stars','created_at','comment'}
    assert set(data['driver'])=={'id','name','development','vehicle_model','verification','identity_review','rating_average','rating_count','completed_trip_count'}
    serialized=json.dumps(data)
    for value in ['Private Surname','booking_id','author_id','PRIVATE-HASH','+919876543210','PRIVATE OWNER','plate']:
        assert value not in serialized
    assert data['driver']['rating_average'] is None and data['driver']['rating_count']==1


def test_legacy_comments_and_default_consent_remain_private(setup):
    booking=completed(setup)
    rating=rate(setup,booking,comment='NEVER PUBLIC')
    _,store,_,_=setup
    with store.transaction() as tx:
        row=tx.get('ratings',rating['id']);row.pop('publish_comment');tx.put('ratings',row['id'],row)
    assert 'NEVER PUBLIC' not in json.dumps(profile(setup))
    assert 'comment' not in profile(setup)['reviews'][0]
    retry=rate(setup,booking,stars=1,comment='NEW PUBLIC',publish_comment=True)
    assert retry['comment']=='NEVER PUBLIC' and retry['stars']==4 and 'publish_comment' not in retry
    with store.read() as tx:
        assert len(tx.list('ratings'))==1


@pytest.mark.parametrize('value',[None,42,{},[],True,'a'*501])
def test_invalid_comment_rejected_not_coerced_or_truncated(setup,value):
    with pytest.raises(DomainError) as error:
        rate(setup,completed(setup),comment=value)
    assert error.value.status==400
    assert setup[3].dispatch('reviews',setup[2]['passenger'],{})['given']==[]


@pytest.mark.parametrize('value',['true',1,None,{}])
def test_publication_requires_actual_boolean(setup,value):
    with pytest.raises(DomainError):
        rate(setup,completed(setup),publish_comment=value)


def test_max_comment_and_idempotent_immutable_submission(setup):
    booking=completed(setup)
    first=rate(setup,booking,comment='అ'*500,publish_comment=True)
    assert rate(setup,booking,stars=1,comment='changed',publish_comment=False)==first


@pytest.mark.parametrize('trip_status,booking_status',[('started','segment_completed'),('completed','accepted'),('cancelled','segment_completed')])
def test_incomplete_trip_or_segment_never_eligible_rated_or_aggregated(setup,trip_status,booking_status):
    booking=completed(setup,trip_status=trip_status,booking_status=booking_status)
    with pytest.raises(DomainError) as error:
        rate(setup,booking)
    assert error.value.status==409
    assert setup[3].dispatch('reviews',setup[2]['passenger'],{})['eligible']==[]
    with setup[1].transaction() as tx:
        tx.put('ratings','forged',{'id':'forged','booking_id':booking['id'],'author_id':'passenger','subject_id':'driver','stars':5,'comment':'forged','publish_comment':True})
    assert profile(setup)['driver']['rating_count']==0
    assert profile(setup)['reviews']==[]


def test_three_review_average_excludes_wrong_role_missing_booking_and_duplicates(setup):
    for number,stars in [(1,5),(2,4),(3,3)]:
        rate(setup,completed(setup,number),stars=stars)
        assert profile(setup)['driver']['rating_average']==(4.0 if number==3 else None)
    # Target driver's history as a passenger must not inflate driver rating.
    rate(setup,completed(setup,4,passenger='driver',driver='driver2'),author='driver2',stars=1)
    with setup[1].transaction() as tx:
        for key,booking,author,stars in [('duplicate','b1','passenger',5),('outsider','b1','other',5),('missing','absent','passenger',5),('boolean','b1','passenger2',True)]:
            tx.put('ratings',key,{'id':key,'booking_id':booking,'author_id':author,'subject_id':'driver','stars':stars})
    data=profile(setup)
    assert data['driver']['rating_count']==3 and data['driver']['rating_average']==4
    assert data['driver']['completed_trip_count']==3


def test_staff_outsider_and_stale_role_are_rejected(setup):
    booking=completed(setup)
    for author in ['admin','other']:
        with pytest.raises(DomainError) as error: rate(setup,booking,author=author)
        assert error.value.status==403
    for action,payload in [('reviews',{}),('driver_profile',{'user_id':'driver'})]:
        with pytest.raises(ReviewsError) as error: setup[3].dispatch(action,setup[2]['admin'],payload)
        assert error.value.status==403
    with setup[1].transaction() as tx:
        actor=tx.get('users','other');actor['role']='staff';tx.put('users','other',actor)
    with pytest.raises(ReviewsError) as error: profile(setup)
    assert error.value.status==403
    with pytest.raises(ReviewsError) as error: setup[3].dispatch('reviews',None,{})
    assert error.value.status==401


@pytest.mark.parametrize('blocker,blocked',[('other','driver'),('driver','other')])
def test_blocked_driver_is_not_disclosed(setup,blocker,blocked):
    completed(setup)
    with setup[1].transaction() as tx:
        key=blocker+':'+blocked;tx.put('blocks',key,{'id':key,'blocker_id':blocker,'blocked_id':blocked})
    with pytest.raises(ReviewsError) as error: profile(setup)
    assert error.value.status==404


def test_blocked_reviewer_not_named_and_expired_approval_not_current_reviewed(setup):
    rate(setup,completed(setup),publish_comment=True)
    with setup[1].transaction() as tx:
        tx.put('blocks','other:passenger',{'id':'other:passenger','blocker_id':'other','blocked_id':'passenger'})
        driver=tx.get('users','driver');driver.update(development=False,auth_method='phone',auth_phone='+919876543210',phone_verified=True,identity_approval={'kind':'human_document_review','source':'identity_application','application_id':'fixture-id','reviewed_at':datetime.now(timezone.utc).isoformat(),'expires_at':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()},verification={key:'verified' for key in ('dl','rc','insurance','selfie','identity')},
            driver_approval={'kind':'reviewed','expires_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()})
        tx.put('users','driver',driver)
    data=profile(setup)
    assert data['reviews']==[] and data['driver']['rating_count']==1
    assert data['driver']['verification']['status']=='expired'
    assert data['driver']['verification']['checks']['dl']=='expired'
    with setup[1].transaction() as tx:
        driver=tx.get('users','driver');driver['driver_approval']['expires_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();driver['driver_approval']['document_expiries']={key:driver['driver_approval']['expires_at'] for key in ('dl','rc','insurance')};tx.put('users','driver',driver)
    assert profile(setup)['driver']['verification']['status']=='reviewed'
    with pytest.raises(ReviewsError) as error:
        profile(setup,target='passenger')
    assert error.value.status==404


def test_each_document_expiry_is_current_without_mislabeling_other_checks(setup):
    completed(setup)
    future=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    with setup[1].transaction() as tx:
        driver=tx.get('users','driver')
        driver.update(development=False,verification={key:'verified' for key in ('dl','rc','insurance','selfie','identity')},
                      driver_approval={'kind':'reviewed','expires_at':future,
                                       'document_expiries':{'dl':future,'rc':future,'insurance':past}})
        tx.put('users','driver',driver)
    verification=profile(setup)['driver']['verification']
    assert verification['status']=='expired'
    assert verification['checks']['insurance']=='expired'
    assert verification['checks']['dl']=='verified'
    with setup[1].transaction() as tx:
        driver=tx.get('users','driver');driver['driver_approval']['document_expiries'].pop('insurance');tx.put('users','driver',driver)
    assert profile(setup)['driver']['verification']['status']=='not_verified'
