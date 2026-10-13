"""Reviewed voice input uses ordinary persisted booking rules, not a privileged path.

The service/store are real; the road provider is the explicitly synthetic fixture.
These checks do not claim microphone, geocoding, or live-road validation.
"""
from datetime import timedelta

import pytest

from app.domain import DomainError, now
from app.store import Store
from test_lifecycle import (
    KONDAPUR, NANDIGAMA, SURYAPET, VIJAYAWADA,
    act, future_departure, make_service, publish, search,
)


def reviewed_search(tmp_path):
    service, store, users, path = make_service(tmp_path)
    departure = future_departure()
    _, trip = publish(service, users['driver'], KONDAPUR, VIJAYAWADA, departure)
    result = search(service, users['passenger'], SURYAPET, NANDIGAMA, departure)
    assert result['metrics']['complete'] is True
    return service, store, users, path, trip, result


def test_reviewed_resolved_points_search_then_selected_match_persists_once(tmp_path):
    service, store, users, path, trip, result = reviewed_search(tmp_path)
    selected = result['matches'][0]
    # Preparing/searching a draft must not silently request a seat.
    with store.read() as tx:
        assert tx.list('bookings') == []
    booking = act(service, 'request', users['passenger'], match_id=selected['id'])['booking']
    retry = act(service, 'request', users['passenger'], match_id=selected['id'])['booking']
    assert retry['id'] == booking['id']
    # Reopen SQLite, proving this is a stored result rather than client-only state.
    with Store(path).read() as tx:
        saved = tx.get('bookings', booking['id'])
        assert saved['trip_id'] == trip['id']
        assert saved['request_id'] == result['request']['id']
        assert saved['match_id'] == selected['id']
        assert saved['pickup'] == SURYAPET
        assert saved['dropoff'] == NANDIGAMA
        assert saved['window_start'] == result['request']['window_start']
        assert saved['window_end'] == result['request']['window_end']
        assert saved['seats'] == 1
        assert saved['status'] == 'pending'
        assert len(tx.list('bookings')) == 1
        assert len(tx.get('seat_request_limits', users['passenger']['id'])['timestamps']) == 1


def test_another_passenger_cannot_submit_the_reviewed_match(tmp_path):
    service, store, users, _path, _trip, result = reviewed_search(tmp_path)
    with pytest.raises(DomainError) as denied:
        act(service, 'request', users['passenger2'], match_id=result['matches'][0]['id'])
    assert denied.value.status == 403
    with store.read() as tx:
        assert tx.list('bookings') == []
        assert tx.get('seat_request_limits', users['passenger2']['id']) is None


def test_expired_reviewed_match_requires_new_search_without_creating_booking(tmp_path):
    service, store, users, _path, _trip, result = reviewed_search(tmp_path)
    match = result['matches'][0]
    with store.transaction() as tx:
        match['created_at'] = (now() - timedelta(minutes=21)).isoformat()
        tx.put('matches', match['id'], match)
    with pytest.raises(DomainError, match='expired') as expired:
        act(service, 'request', users['passenger'], match_id=match['id'])
    assert expired.value.status == 409
    with store.read() as tx:
        assert tx.list('bookings') == []
        assert tx.get('seat_request_limits', users['passenger']['id']) is None


def test_retry_after_match_expiry_returns_already_saved_booking(tmp_path):
    service, store, users, _path, _trip, result = reviewed_search(tmp_path)
    match = result['matches'][0]
    booking = act(service, 'request', users['passenger'], match_id=match['id'])['booking']
    with store.transaction() as tx:
        match['created_at'] = (now() - timedelta(minutes=21)).isoformat()
        tx.put('matches', match['id'], match)
    retry = act(service, 'request', users['passenger'], match_id=match['id'])['booking']
    assert retry['id'] == booking['id']
    with store.read() as tx:
        assert len(tx.list('bookings')) == 1
        assert len(tx.get('seat_request_limits', users['passenger']['id'])['timestamps']) == 1
