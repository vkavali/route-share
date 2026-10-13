"""Real Flask/cookie/bearer/SQLite account flows; no network or bank claims."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import struct
import zlib

import pytest
from werkzeug.test import EnvironBuilder

from app import create_app
from app.driver_verification import MAX_DOCUMENT_BYTES
from test_lifecycle import FixtureRoadProvider, KONDAPUR, VIJAYAWADA
from test_phone_http import SMSFixture, signup, web_headers, bearer

PASSWORD = 'http-fixture-only-not-production'


def png(size=80):
    """Valid 1px RGB PNG with a sized ancillary text chunk, including CRCs."""
    def chunk(kind, payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    prefix=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))
    suffix=chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00'))+chunk(b'IEND',b'')
    filler=max(0,size-len(prefix)-len(suffix)-12-8)
    return prefix+chunk(b'tEXt',b'Comment\x00'+b'x'*filler)+suffix


@pytest.fixture
def system(tmp_path):
    config={'TESTING':True,'SECRET_KEY':'http-account-session-only','DATABASE_PATH':str(tmp_path/'http.sqlite3'),
            'BETA_PASSWORD':PASSWORD,'DIRECT_UPI_ENABLED':True,'VOICE_ENABLED':False,
            'PHONE_AUTH_ENABLED':True,'PHONE_AUTH_PROVIDER':SMSFixture(),
            'PUBLIC_OPERATOR_NAME':'Test operator','PUBLIC_SUPPORT_EMAIL':'support@example.test',
            'PHONE_AUTH_HMAC_KEY':'h'*48,'PHONE_AUTH_DAILY_LIMIT':100}
    application=create_app(config)
    application.extensions['beta_service'].router=FixtureRoadProvider()
    store=application.extensions['beta_store']
    with store.transaction() as tx:
        ops={**tx.get('users','admin'),'id':'ops-http','name':'HTTP Ops','staff_capabilities':['ops.read']}
        tx.put('users',ops['id'],ops)
    return application,config


def actor(app, account, native=False):
    client=app.test_client()
    if native:
        response=client.post('/api/mobile/login',json={'account':account,'password':PASSWORD})
        assert response.status_code==200,response.json
        headers={'Authorization':'Bearer '+response.json['token'],'X-Expected-User-ID':account}
    else:
        boot=client.get('/api/bootstrap').json
        headers={'Origin':'http://localhost','X-CSRF-Token':boot['csrf_token']}
        response=client.post('/api/login',json={'account':account,'password':PASSWORD},headers=headers)
        assert response.status_code==200,response.json
        headers['X-Expected-User-ID']=account
    return client,headers


def phone_actor(app, phone, name, *, native=False):
    """Create a distinct synthetic customer through the actual OTP/profile APIs."""
    client=app.test_client(use_cookies=not native)
    signed,_=signup(client,native=native,phone=phone)
    uid=signed.json['user']['id']
    headers=bearer(signed) if native else web_headers(signed.json['csrf_token'])
    headers['X-Expected-User-ID']=uid
    who=(client,headers)
    post(who,'phone/profile',{'name':name})
    with app.extensions['beta_store'].read() as tx:
        user=tx.get('users',uid)
        assert user['development'] is False and user['phone_verified'] is True
        assert user['auth_method']=='phone' and user['auth_phone']=='+91'+phone
    return who,uid


def post(who, endpoint, data, expected=200):
    response=who[0].post('/api/'+endpoint,json=data,headers=who[1])
    assert response.status_code==expected,(endpoint,response.status_code,response.json)
    return response


def get(who, endpoint, expected=200):
    response=who[0].get('/api/'+endpoint,headers=who[1])
    assert response.status_code==expected,(endpoint,response.status_code,response.json)
    assert response.headers['Cache-Control']=='no-store'
    return response


def draft(owner):
    return post(owner,'driver_application',{'legal_name':'PRIVATE-LEGAL-APPLICANT',
        'vehicle':{'model':'Fixture Car','plate':'TS01AB1234'},'adult_attested':True,'planned_trip_attested':True,
        'document_consent':True,'applicant_note':'PRIVATE-APPLICATION-NOTE','expected_version':0}).json['application']


def upload(owner, current, kind, content):
    fields={'kind':kind,'expected_version':str(current['version']),
            'file':(BytesIO(content),'PRIVATE-DOCUMENT-'+kind+'.png')}
    if kind!='selfie':fields['expires_on']=(datetime.now(timezone.utc)+timedelta(days=60)).date().isoformat()
    response=owner[0].post('/api/driver_documents',data=fields,headers=owner[1],content_type='multipart/form-data')
    assert response.status_code==200,(kind,len(content),response.status_code,response.json)
    return response.json['application']


def decision(current):
    return {'application_id':current['id'],'expected_version':current['version'],'decision':'approved',
            'reason':'PRIVATE-REVIEW-REASON manually inspected all four files.',
            'checks':{'dl':True,'rc':True,'insurance':True,'identity_match':True},'idempotency_key':'http-review-approval-1'}


@pytest.mark.parametrize('large_upload',[False,True])
def test_complete_http_document_payment_review_and_restart(system,large_upload):
    app,config=system
    owner,owner_id=phone_actor(app,'9876543210','Synthetic owner',native=True)
    rider,rider_id=phone_actor(app,'8765432109','Synthetic rider')
    # This fixture isolates the driver-document/payment path. The separate ID
    # HTTP suite exercises real submission, encrypted upload, and staff review.
    reviewed=datetime.now(timezone.utc)
    with app.extensions['beta_store'].transaction() as tx:
        rider_record=tx.get('users',rider_id)
        rider_record['identity_approval']={
            'kind':'human_document_review','source':'identity_application',
            'application_id':'synthetic-http-rider-review','reviewed_at':reviewed.isoformat(),
            'expires_at':(reviewed+timedelta(days=30)).isoformat()}
        tx.put('users',rider_id,rider_record)
    outsider=actor(app,'driver')
    reviewer=actor(app,'admin')
    ops=actor(app,'ops-http')
    assert get(owner,'driver_application').json['application'] is None
    current=draft(owner)
    large=png(MAX_DOCUMENT_BYTES if large_upload else 8192)
    assert len(large)==(MAX_DOCUMENT_BYTES if large_upload else 8192)
    originals={}
    for kind in ('dl','rc','insurance','selfie'):
        originals[kind]=large if kind=='dl' else png(8192)
        current=upload(owner,current,kind,originals[kind])
    submitted=post(owner,'submit_driver_application',{'expected_version':current['version']}).json['application']
    assert submitted['status']=='submitted'
    assert get(reviewer,'verification_queue').json['applications'][0]['id']==submitted['id']
    get(ops,'verification_queue',403)
    post(ops,'review_driver_application',decision(submitted),403)
    unread=post(reviewer,'review_driver_application',decision(submitted),409)
    assert unread.json['code']=='verification_documents_unread'
    for document in submitted['documents']:
        endpoint='driver_document?document_id='+document['id']
        get(outsider,endpoint,404);get(ops,endpoint,404)
        get(reviewer,endpoint,404)
        downloaded=get(owner,endpoint)
        assert downloaded.data==originals[document['kind']]
        assert 'attachment;' in downloaded.headers['Content-Disposition']
        preview=get(reviewer,'driver_document_preview?document_id='+document['id'])
        assert set(preview.json)=={'image_data_url','page','page_count','watermark'}
        assert preview.json['image_data_url'].startswith('data:image/jpeg;base64,')
        get(ops,'driver_document_preview?document_id='+document['id'],403)
        assert 'Content-Disposition' not in preview.headers
        assert preview.headers['X-Content-Type-Options']=='nosniff'
    progress=get(reviewer,'driver_review_progress?application_id='+submitted['id']).json
    for step in progress['steps']:
        progress=post(reviewer,'driver_review_progress',dict(application_id=submitted['id'],
            expected_version=submitted['version'], expected_revision=progress['revision'],
            step=step['key'],checks={key:True for key in step['checks']})).json
    assert progress['ready_for_approval']
    approved=post(reviewer,'review_driver_application',decision(submitted)).json['application']
    assert approved['status']=='approved'
    assert get(owner,'bootstrap').json['user']['access']['can_drive'] is True
    with app.extensions['beta_store'].read() as tx:
        reviewed=tx.get('users',owner_id)
        assert reviewed['driver_approval']['kind']=='reviewed'
        assert set(reviewed['driver_approval']['document_expiries'])=={'dl','rc','insurance'}
    assert get(outsider,'driver_profile?user_id='+owner_id).json['driver']['verification']['status']=='reviewed'

    # Actual preview -> publish -> search -> request -> accept using labelled fixture road provider.
    departure=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat()
    preview=post(owner,'preview',{'origin':KONDAPUR,'destination':VIJAYAWADA,'departure':departure,'seats':2,'max_detour_minutes':15}).json['preview']
    trip=post(owner,'publish',{'preview_id':preview['id']}).json['trip']
    found=post(rider,'search',{'origin':KONDAPUR,'destination':VIJAYAWADA,'window_start':departure,
        'window_end':(datetime.fromisoformat(departure)+timedelta(hours=8)).isoformat(),'seats':1}).json
    match=next(m for m in found['matches'] if m['trip_id']==trip['id'])
    booking=post(rider,'request',{'match_id':match['id']}).json['booking']
    post(owner,'accept',{'booking_id':booking['id']})
    bid=booking['id']
    assert get(owner,'payments/trip-budget/'+trip['id']).json['budget'] is None
    post(rider,'payments/trip-budget/action',{'trip_id':trip['id'],'action':'set_budget',
        'expected_version':0,'idempotency_key':'http-budget-1','fuel_paise':180000,
        'toll_paise':20000,'owner_share_paise':100000,'reason':'Declared fixture trip costs'},403)
    budget=post(owner,'payments/trip-budget/action',{'trip_id':trip['id'],'action':'set_budget',
        'expected_version':0,'idempotency_key':'http-budget-1','fuel_paise':180000,
        'toll_paise':20000,'owner_share_paise':100000,'reason':'Declared fixture trip costs'}).json['budget']
    assert budget['passenger_cap_paise']==100000
    get(outsider,'payments/trip-budget/'+trip['id'],403)
    payment=get(owner,'payment?booking_id='+bid).json['payment']
    assert payment['allowed_actions']==['propose']
    assert get(rider,'payment?booking_id='+bid).json['payment']['allowed_actions']==[]
    get(outsider,'payment?booking_id='+bid,403);get(reviewer,'payment?booking_id='+bid,403)
    def command(who, action, version, expected=200, **extra):
        return post(who,'payment_action',{'booking_id':bid,'action':action,'expected_version':version,
                    'idempotency_key':f'http-{action}-{version}',**extra},expected).json
    payload={'amount_paise':50000,'breakdown':{'fuel_paise':45000,'toll_paise':5000},'note':'PRIVATE-PAYMENT-NOTE',
             'payee_name':'PRIVATE-PAYEE-NAME','upi_id':'privatefixture@okbank'}
    command(rider,'propose',0,409,**payload)
    proposal=command(owner,'propose',0,**payload)['payment']
    assert proposal['upi_uri'] is None and proposal['upi_id'] is None
    assert command(owner,'propose',0,**payload)['replayed'] is True
    assert 'agree' in get(rider,'payment?booking_id='+bid).json['payment']['allowed_actions']
    command(owner,'agree',1,409)
    agreement=command(rider,'agree',1)['payment']
    assert agreement['upi_uri'].startswith('upi://pay?') and 'am=500.00' in agreement['upi_uri']
    assert agreement['verification']=='manual_only'
    report=command(rider,'report_paid',2)['payment'];assert report['status']=='passenger_reported' and report['upi_uri'] is None
    command(rider,'confirm_received',3,409)
    assert command(owner,'confirm_received',3)['payment']['status']=='owner_confirmed'
    assert command(rider,'dispute',4)['payment']['status']=='disputed'
    assert command(rider,'request_refund',5)['payment']['status']=='refund_requested'
    assert command(owner,'report_refund',6)['payment']['status']=='refund_reported'
    final=command(rider,'confirm_refund',7)['payment']
    assert final['status']=='refunded' and final['allowed_actions']==[]

    for who in (owner,rider,outsider,reviewer,ops):
        for endpoint in ('bootstrap','state'):
            value=get(who,endpoint).get_data(as_text=True)
            for private in ('PRIVATE-LEGAL-APPLICANT','PRIVATE-APPLICATION-NOTE','PRIVATE-DOCUMENT-',
                            'PRIVATE-REVIEW-REASON','PRIVATE-PAYMENT-NOTE','PRIVATE-PAYEE-NAME','privatefixture@okbank'):
                assert private not in value,(endpoint,private)
    operations=get(ops,'operations').get_data(as_text=True)
    for private in ('PRIVATE-LEGAL-APPLICANT','PRIVATE-APPLICATION-NOTE','PRIVATE-DOCUMENT-',
                    'PRIVATE-REVIEW-REASON','PRIVATE-PAYMENT-NOTE','PRIVATE-PAYEE-NAME','privatefixture@okbank'):
        assert private not in operations

    # Rating remains unavailable until both participant segment and trip complete.
    post(rider,'rate',{'booking_id':bid,'stars':5,'comment':'Not yet'},409)
    post(owner,'start_trip',{'trip_id':trip['id']})
    post(rider,'board_segment',{'booking_id':bid})
    post(rider,'complete_segment',{'booking_id':bid})
    post(owner,'complete_trip',{'trip_id':trip['id']})
    assert any(row['booking_id']==bid for row in get(rider,'reviews').json['eligible'])
    rating=post(rider,'rate',{'booking_id':bid,'stars':5,'comment':'PUBLIC-CONSENTED-REVIEW','publish_comment':True}).json['rating']
    retry=post(rider,'rate',{'booking_id':bid,'stars':1,'comment':'change','publish_comment':False}).json['rating']
    assert retry==rating
    public=get(outsider,'driver_profile?user_id='+owner_id).json
    assert public['driver']['rating_count']==1 and public['driver']['rating_average'] is None
    assert public['reviews'][0]['comment']=='PUBLIC-CONSENTED-REVIEW'
    assert not any(k in public['reviews'][0] for k in ('booking_id','author_id','id'))
    assert get(owner,'reviews').json['received'][0]['booking_id']==bid

    restarted=create_app(config)
    # Persisted native session is still usable after app recreation.
    owner_after=(restarted.test_client(),owner[1])
    assert get(owner_after,'driver_application').json['application']['status']=='approved'
    assert get(owner_after,'payment?booking_id='+bid).json['payment']['status']=='refunded'
    assert get(owner_after,'reviews').json['received'][0]['id']==rating['id']
    assert get(owner_after,'driver_document?document_id='+approved['documents'][0]['id']).data==originals[approved['documents'][0]['kind']]


def test_http_auth_csrf_stale_actor_and_multipart_bounds(system):
    app,_=system
    anon=app.test_client()
    for endpoint in ('reviews','payments','driver_application','verification_queue','driver_profile?user_id=driver','driver_document?document_id='+'a'*32):
        assert anon.get('/api/'+endpoint).status_code==401
    owner=actor(app,'passenger2')
    assert owner[0].post('/api/driver_application',json={}).status_code==403
    current=draft(owner)
    stale={**owner[1],'X-Expected-User-ID':'passenger'}
    response=owner[0].post('/api/driver_documents',data={'kind':'selfie','expected_version':str(current['version']),'file':(BytesIO(png()),'image.png')},headers=stale)
    assert response.status_code==409 and response.json['code']=='account_changed'
    assert get(owner,'driver_application').json['application']['documents']==[]
    # Ordinary JSON endpoints retain their separate16KiB cap.
    response=owner[0].post('/api/driver_application',data=b'x'*(16384+1),content_type='application/json',headers=owner[1])
    assert response.status_code==413
    oversized_fields=owner[0].post('/api/driver_documents',data={'kind':'x'*(16*1024+1),
        'expected_version':str(current['version']),'file':(BytesIO(png()),'image.png')},headers=owner[1])
    assert oversized_fields.status_code==413
    # A missing Content-Length cannot turn the multipart stream into an unbounded upload.
    builder=EnvironBuilder(path='/api/driver_documents',method='POST',headers=owner[1],data={
        'kind':'dl','expires_on':'2030-01-01','expected_version':str(current['version']),
        'file':(BytesIO(png(MAX_DOCUMENT_BYTES+1)),'oversize.png')})
    environ=builder.get_environ();environ.pop('CONTENT_LENGTH',None);environ['wsgi.input_terminated']=True
    response=owner[0].open(environ)
    assert response.status_code==413
    assert get(owner,'driver_application').json['application']['documents']==[]
    malformed=owner[0].post('/api/driver_documents',data=b'--bad\r\nnot-a-part',content_type='multipart/form-data; boundary=bad',headers=owner[1])
    assert malformed.status_code==400
    duplicated=owner[0].post('/api/driver_documents',data={'kind':'selfie','expected_version':str(current['version']),
        'file':[(BytesIO(png()),'a.png'),(BytesIO(png()),'b.png')]},headers=owner[1])
    assert duplicated.status_code==400
