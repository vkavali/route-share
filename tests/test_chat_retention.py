"""90-day primary chat retention, independently of backup/legal retention."""
from datetime import datetime, timedelta, timezone

import pytest

import app.community as module
from app.community import CommunityError, CommunityService
from app.store import Store


@pytest.fixture
def chat(tmp_path, monkeypatch):
    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(module, '_now', lambda: now)
    store = Store(tmp_path / 'retention.sqlite')
    users = {key: {'id': key, 'name': key, 'role': 'member'} for key in ('driver', 'rider', 'other')}
    with store.transaction() as tx:
        for actor in users.values(): tx.put('users', actor['id'], actor)
        tx.put('trips', 'trip', {'id': 'trip', 'driver_id': 'driver', 'status': 'started'})
        tx.put('bookings', 'booking', {'id': 'booking', 'trip_id': 'trip', 'driver_id': 'driver',
            'passenger_id': 'rider', 'status': 'accepted', 'match': {'dropoff_at': (now + timedelta(hours=1)).isoformat()}})
    return store, CommunityService(store), users, now


def put_message(store, identity, created, *, text='PRIVATE-CHAT', client_id=None):
    with store.transaction() as tx:
        tx.put('messages', identity, {'id': identity, 'booking_id': 'booking', 'sender_id': 'rider',
            'sender_name': 'rider', 'recipient_id': 'driver', 'text': text, 'client_message_id': client_id or identity,
            'created_at': created.isoformat() if isinstance(created, datetime) else created, 'read_at': None})
        tx.put('notifications', 'note-' + identity, {'id': 'note-' + identity, 'booking_id': 'booking',
            'recipient_id': 'driver', 'type': 'chat_message', 'message_id': identity,
            'created_at': created.isoformat() if isinstance(created, datetime) else created, 'read_at': None})


def test_exact_utc_boundary_primary_cleanup_preserves_legal_and_other_notifications(chat):
    store, service, users, now = chat
    cutoff = now - timedelta(days=90)
    put_message(store, 'before', cutoff - timedelta(microseconds=1))
    put_message(store, 'exact', cutoff.astimezone(timezone(timedelta(hours=5, minutes=30))))
    put_message(store, 'retained', cutoff + timedelta(microseconds=1))
    with store.transaction() as tx:
        tx.put('safety_reports', 'evidence', {'id': 'evidence', 'text': 'PRESERVED-SAFETY-EVIDENCE'})
        tx.put('notifications', 'lifecycle', {'id': 'lifecycle', 'type': 'trip_completed', 'recipient_id': 'driver',
            'created_at': (cutoff - timedelta(days=20)).isoformat(), 'read_at': None})
    result = service.maintenance(now)
    assert result == {'messages_deleted': 2, 'notifications_deleted': 2, 'messages_scanned': 3, 'notifications_scanned': 4}
    assert all(type(value) is int for value in result.values())
    with store.read() as tx:
        assert [r['id'] for r in tx.list('messages')] == ['retained']
        assert tx.get('safety_reports', 'evidence')['text'] == 'PRESERVED-SAFETY-EVIDENCE'
        assert tx.get('notifications', 'lifecycle')
        assert tx.get('expired_message_ids', 'exact') == {'id': 'exact'}
    restarted = CommunityService(Store(store.path))
    assert [m['id'] for m in restarted.dispatch('chat', users['driver'], {'booking_id': 'booking'})['messages']] == ['retained']


def test_maintenance_is_bounded_and_resumes_after_restart(chat, monkeypatch):
    store, service, _, now = chat
    monkeypatch.setattr(module, 'RETENTION_BATCH_SIZE', 2)
    for index in range(7): put_message(store, f'old-{index}', now - timedelta(days=91))
    first = service.maintenance(now)
    assert first['messages_scanned'] == first['notifications_scanned'] == 2
    assert first['messages_deleted'] == first['notifications_deleted'] == 2
    with store.read() as tx: assert len(tx.list('messages')) == 5
    restarted = CommunityService(Store(store.path))
    for _ in range(4):
        result = restarted.maintenance(now)
        assert max(result.values()) <= 2
    with store.read() as tx:
        assert tx.list('messages') == [] and tx.list('notifications') == []
        assert len(tx.list('expired_message_ids')) == 7


def test_backlog_never_leaks_into_threads_unread_notifications_or_cursors(chat, monkeypatch):
    store, service, users, now = chat
    monkeypatch.setattr(module, 'RETENTION_BATCH_SIZE', 1)
    for index in range(20): put_message(store, f'a-{index:02}', now - timedelta(days=91))
    put_message(store, 'z-expired', now - timedelta(days=90))
    put_message(store, 'z-new', now, text='Current message')
    result = service.dispatch('chat', users['driver'], {'booking_id': 'booking'})
    assert [m['text'] for m in result['messages']] == ['Current message']
    threads = service.dispatch('chats', users['driver'], {})['chats']
    assert threads[0]['latest_message']['text'] == 'Current message' and threads[0]['unread_count'] == 1
    assert service.unread_counts('driver') == {'notification_unread_count': 1, 'chat_unread_count': 1}
    notes = service.dispatch('notifications', users['driver'], {})['notifications']
    assert [note['message_id'] for note in notes] == ['z-new']
    with pytest.raises(CommunityError) as error:
        service.dispatch('mark_chat_read', users['driver'], {'booking_id': 'booking', 'upto_message_id': 'z-expired'})
    assert error.value.status == 404
    with pytest.raises(CommunityError) as error:
        service.dispatch('mark_notification_read', users['driver'], {'notification_id': 'note-z-expired'})
    assert error.value.status == 404
    service.dispatch('mark_chat_read', users['driver'], {'booking_id': 'booking', 'upto_message_id': 'z-new'})
    assert service.unread_counts('driver')['chat_unread_count'] == 0
    with store.read() as tx:
        assert tx.get('messages', 'z-expired') is not None  # Still in bounded backlog, but never exposed.


def test_expired_client_identifier_cannot_resurrect_message_after_deletion(chat):
    store, service, users, now = chat
    client_id = 'expired-client-id'
    identity = service._message_id('booking', 'rider', client_id)
    put_message(store, identity, now - timedelta(days=90), client_id=client_id)
    service.maintenance(now)
    service = CommunityService(Store(store.path))
    for text in ('PRIVATE-CHAT', 'Attempt replacement'):
        with pytest.raises(CommunityError) as error:
            service.dispatch('send_message', users['rider'], {'booking_id': 'booking', 'client_message_id': client_id, 'text': text})
        assert error.value.code == 'message_expired'
    with store.read() as tx: assert tx.get('messages', identity) is None
    fresh = service.dispatch('send_message', users['rider'], {'booking_id': 'booking', 'client_message_id': 'new-message', 'text': 'New message'})
    assert fresh['message']['text'] == 'New message'
    assert service.dispatch('send_message', users['rider'], {'booking_id': 'booking', 'client_message_id': 'new-message', 'text': 'New message'}) == fresh


def test_expired_thread_becomes_empty_and_unauthorized_actor_sees_nothing(chat):
    store, service, users, now = chat
    put_message(store, 'only-old', now - timedelta(days=91))
    assert service.dispatch('chat', users['driver'], {'booking_id': 'booking'})['messages'] == []
    thread = service.dispatch('chats', users['driver'], {})['chats'][0]
    assert thread['latest_message'] is None and thread['unread_count'] == 0
    assert service.dispatch('notifications', users['driver'], {})['notifications'] == []
    with pytest.raises(CommunityError) as error:
        service.dispatch('chat', users['other'], {'booking_id': 'booking'})
    assert error.value.status == 403
    put_message(store, 'recent', now)
    with store.transaction() as tx:
        actor = tx.get('users', 'driver'); actor['auth_epoch'] = 1; tx.put('users', 'driver', actor)
    for action, payload in [('chat', {'booking_id': 'booking'}), ('chats', {}), ('notifications', {})]:
        with pytest.raises(CommunityError) as error: service.dispatch(action, users['driver'], payload)
        assert error.value.status == 401


def test_invalid_dates_hidden_without_guessing_age_and_cleanup_does_not_touch_safety(chat):
    store, service, users, now = chat
    put_message(store, 'unknown-date', 'not-a-date')
    assert service.dispatch('chat', users['driver'], {'booking_id': 'booking'})['messages'] == []
    assert service.dispatch('notifications', users['driver'], {})['notifications'] == []
    with store.read() as tx:
        assert tx.get('messages', 'unknown-date') is not None  # Unknown age is not invented.


def test_expired_retry_is_rejected_even_before_its_cleanup_page(chat):
    store, service, users, now = chat
    identity = service._message_id('booking', 'rider', 'old-retry')
    put_message(store, identity, now - timedelta(days=91), client_id='old-retry')
    with store.transaction() as tx:
        tx.put('community_maintenance', 'chat_retention', {'id': 'chat_retention', 'message_cursor': 'z'})
    with pytest.raises(CommunityError) as error:
        service.dispatch('send_message', users['rider'], {'booking_id': 'booking', 'client_message_id': 'old-retry', 'text': 'PRIVATE-CHAT'})
    assert error.value.code == 'message_expired'
    with store.read() as tx:
        assert tx.get('messages', identity) is not None
        assert tx.get('expired_message_ids', identity) is None


def test_send_path_performs_cleanup_and_accepts_fresh_message(chat):
    store, service, users, now = chat
    put_message(store, 'old-primary', now - timedelta(days=91))
    result = service.dispatch('send_message', users['rider'],
        {'booking_id': 'booking', 'client_message_id': 'fresh-after-cleanup', 'text': 'Current pickup message'})
    assert result['message']['text'] == 'Current pickup message'
    with store.read() as tx:
        assert tx.get('messages', 'old-primary') is None
        assert tx.get('notifications', 'note-old-primary') is None
