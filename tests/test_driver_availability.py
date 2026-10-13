"""Approval/vehicle trust is rechecked at actual persisted trip mutation boundaries."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import DomainError
from test_lifecycle import (make_service, act, publish, search, booking_for,
                            KONDAPUR, VIJAYAWADA, SURYAPET, NANDIGAMA, future_departure)


def change_driver(store, change):
    with store.transaction() as tx:
        user = tx.get('users', 'driver')
        if change == 'revoked':
            user['driver_approved'] = False
        elif change == 'expired':
            user['driver_approval']['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        elif change == 'vehicle':
            user['vehicle'] = {'model':'Different approved car', 'plate':'DIFFERENT'}
        tx.put('users', 'driver', user)


def fixture(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    _, trip = publish(service, users['driver'], KONDAPUR, VIJAYAWADA, seats=2)
    found, booking = booking_for(service, users['passenger'], SURYAPET, NANDIGAMA, trip['departure'])
    return service, store, users, trip, found, booking


@pytest.mark.parametrize('change', ['revoked', 'expired', 'vehicle'])
def test_old_match_cannot_admit_new_request_or_accept_after_approval_change(tmp_path, change):
    service, store, users, trip, found, booking = fixture(tmp_path)
    second = search(service, users['passenger2'], SURYAPET, NANDIGAMA, trip['departure'])
    change_driver(store, change)
    assert search(service, users['passenger2'], SURYAPET, NANDIGAMA, trip['departure'])['matches'] == []
    with pytest.raises(DomainError) as denied:
        act(service, 'request', users['passenger2'], match_id=second['matches'][0]['id'])
    assert denied.value.status == 409
    with pytest.raises(DomainError) as denied:
        act(service, 'accept', users['driver'], booking_id=booking['id'])
    assert denied.value.status in {403, 409}
    with store.read() as tx:
        assert tx.get('bookings', booking['id'])['status'] == 'pending'
        assert len(tx.list('bookings')) == 1
        assert tx.get('trips', trip['id'])['driver_vehicle'] == users['driver']['vehicle']


@pytest.mark.parametrize('action', ['publish', 'accept', 'start_trip'])
def test_revocation_between_dispatch_check_and_write_is_rejected(tmp_path, monkeypatch, action):
    service, store, users, trip, found, booking = fixture(tmp_path)
    if action == 'publish':
        preview = act(service, 'preview', users['driver'], origin=KONDAPUR, destination=VIJAYAWADA,
                      departure=future_departure(), seats=1, max_detour_minutes=10)['preview']
        payload = {'preview_id':preview['id']}
    elif action == 'accept':
        payload = {'booking_id':booking['id']}
    else:
        act(service, 'accept', users['driver'], booking_id=booking['id'])
        payload = {'trip_id':trip['id']}
    original = getattr(service, '_'+action)
    def revoke_before_write(user, payload):
        change_driver(store, 'revoked')
        return original(user, payload)
    monkeypatch.setattr(service, '_'+action, revoke_before_write)
    with pytest.raises(DomainError) as denied:
        act(service, action, users['driver'], **payload)
    assert denied.value.status == 403
    with store.read() as tx:
        assert len(tx.list('trips')) == 1
        assert tx.get('trips', trip['id'])['status'] == 'published'
        if action == 'accept':
            assert tx.get('bookings', booking['id'])['status'] == 'pending'


def test_preview_revoked_during_routing_is_not_saved(tmp_path, monkeypatch):
    service, store, users, _ = make_service(tmp_path)
    original = service.router.route
    def route(points):
        result = original(points)
        change_driver(store, 'revoked')
        return result
    monkeypatch.setattr(service.router, 'route', route)
    with pytest.raises(DomainError) as denied:
        act(service, 'preview', users['driver'], origin=KONDAPUR, destination=VIJAYAWADA,
            departure=future_departure(), seats=1, max_detour_minutes=10)
    assert denied.value.status == 403
    with store.read() as tx:
        assert tx.list('previews') == []


def test_search_rechecks_approval_after_routing(tmp_path, monkeypatch):
    service, store, users, trip, _, _ = fixture(tmp_path)
    original = service.router.route
    def route(points):
        result = original(points)
        change_driver(store, 'revoked')
        return result
    monkeypatch.setattr(service.router, 'route', route)
    found = search(service, users['passenger2'], SURYAPET, NANDIGAMA, trip['departure'])
    assert found['matches'] == [] and found['metrics']['route_aware_match_count'] == 0
    with store.read() as tx:
        assert not any(m['request_id'] == found['request']['id'] for m in tx.list('matches'))


@pytest.mark.parametrize('change', ['revoked', 'expired', 'vehicle'])
def test_historical_booking_badges_are_current_without_rewriting_car(tmp_path, change):
    service, store, users, _ = make_service(tmp_path)
    with store.transaction() as tx:
        user = tx.get('users', 'driver')
        future = (datetime.now(timezone.utc)+timedelta(days=60)).isoformat()
        user['driver_approval'] = {'kind':'reviewed', 'expires_at':future,
                                  'document_expiries':dict.fromkeys(('dl','rc','insurance'), future)}
        user['verification'] = dict.fromkeys(('dl','rc','insurance','selfie','identity'), 'verified')
        tx.put('users', 'driver', user)
        for index, member in enumerate(tx.list('users')):
            if member.get('role') == 'member':
                member.update(development=False, auth_method='phone', auth_phone=f'+9198765432{index:02}', phone_verified=True,
                    identity_approval={'kind':'human_document_review','source':'identity_application','application_id':'fixture-id-'+member['id'],
                        'reviewed_at':datetime.now(timezone.utc).isoformat(),'expires_at':future})
                tx.put('users', member['id'], member)
    _, trip = publish(service, users['driver'], KONDAPUR, VIJAYAWADA)
    _, booking = booking_for(service, users['passenger'], SURYAPET, NANDIGAMA, trip['departure'])
    act(service, 'accept', users['driver'], booking_id=booking['id'])
    change_driver(store, change)
    state = act(service, 'state', users['passenger'])
    match = state['bookings'][0]['match']
    assert match['driver_available'] is False
    assert all(match['verification'][key] != 'verified' for key in ('dl','rc','insurance','selfie'))
    assert match['verification']['identity'] == 'verified'
    assert match['identity_review']['status'] == 'reviewed'
    assert match['vehicle'] == users['driver']['vehicle']
    with pytest.raises(DomainError):
        act(service, 'start_trip', users['driver'], trip_id=trip['id'])
    # Existing participants retain the safe cancellation path and historical identity.
    act(service, 'cancel_trip', users['driver'], trip_id=trip['id'], reason='Approval or listed vehicle changed')
    with store.read() as tx:
        assert tx.get('trips', trip['id'])['driver_vehicle'] == users['driver']['vehicle']


def test_changed_vehicle_invalidates_unpublished_preview(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    preview = act(service, 'preview', users['driver'], origin=KONDAPUR, destination=VIJAYAWADA,
                  departure=future_departure(), seats=1, max_detour_minutes=10)['preview']
    change_driver(store, 'vehicle')
    with pytest.raises(DomainError) as denied:
        act(service, 'publish', users['driver'], preview_id=preview['id'])
    assert denied.value.status == 409


def test_approval_expiring_during_accept_route_calculation_cannot_confirm(tmp_path, monkeypatch):
    import app.permissions as permissions
    service, store, users, trip, _, booking = fixture(tmp_path)
    real_now = datetime.now(timezone.utc)
    simulated_now = [real_now]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return simulated_now[0].astimezone(tz) if tz else simulated_now[0].replace(tzinfo=None)
    with store.transaction() as tx:
        driver = tx.get('users', 'driver')
        driver['driver_approval']['expires_at'] = (real_now+timedelta(minutes=1)).isoformat()
        tx.put('users', 'driver', driver)
    monkeypatch.setattr(permissions, 'datetime', Clock)
    original = service.router.route
    def route(points):
        result = original(points)
        simulated_now[0] = real_now+timedelta(minutes=2)
        return result
    monkeypatch.setattr(service.router, 'route', route)
    with pytest.raises(DomainError) as denied:
        act(service, 'accept', users['driver'], booking_id=booking['id'])
    assert denied.value.status == 403
    with store.read() as tx:
        assert tx.get('bookings', booking['id'])['status'] == 'pending'


def test_development_blank_vehicle_remains_consistent(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    with store.transaction() as tx:
        driver = tx.get('users', 'driver')
        driver['vehicle'] = {'model':'', 'plate':''}
        tx.put('users', 'driver', driver)
    _, trip = publish(service, users['driver'], KONDAPUR, VIJAYAWADA)
    assert trip['driver_available'] is True
    found = search(service, users['passenger'], SURYAPET, NANDIGAMA, trip['departure'])
    assert len(found['matches']) == 1
