"""Participant review history and a strictly allowlisted public driver profile."""
from datetime import datetime, timezone

from .permissions import can_drive, identity_review_summary
from .auth import is_active_account, current_actor_matches


class ReviewsError(Exception):
    def __init__(self, message, status=400, code='reviews_invalid'):
        super().__init__(message)
        self.status, self.code = status, code


def _blocked(tx, first, second):
    return bool(tx.get('blocks', first + ':' + second) or tx.get('blocks', second + ':' + first))


def _name(user):
    value = user.get('name') if isinstance(user, dict) else None
    return value if isinstance(value, str) else ''


def _point(value):
    return {k: value[k] for k in ('label', 'lat', 'lon') if k in value} if isinstance(value, dict) else None


def _verification(user):
    allowed = {'not_checked', 'pending', 'verified', 'rejected', 'expired'}
    raw = user.get('verification') if isinstance(user.get('verification'), dict) else {}
    checks = {k: raw.get(k) if isinstance(raw.get(k), str) and raw.get(k) in allowed else 'not_checked'
              for k in ('phone', 'identity', 'dl', 'rc', 'insurance', 'selfie')}
    identity = identity_review_summary(user)
    checks['identity'] = {'reviewed': 'verified', 'expired': 'expired'}.get(identity['status'], 'not_checked')
    approval = user.get('driver_approval') if isinstance(user.get('driver_approval'), dict) else {}
    expiry = None
    try:
        parsed = datetime.fromisoformat(approval.get('expires_at', '').replace('Z', '+00:00'))
        if parsed.tzinfo:
            expiry = parsed
    except (AttributeError, TypeError, ValueError):
        pass
    document_expired = False
    document_expiries = approval.get('document_expiries')
    if isinstance(document_expiries, dict):
        for key in ('dl', 'rc', 'insurance'):
            try:
                stamp = datetime.fromisoformat(document_expiries.get(key, '').replace('Z', '+00:00'))
                if stamp.tzinfo and stamp <= datetime.now(timezone.utc):
                    document_expired = True
                    checks[key] = 'expired'
            except (AttributeError, TypeError, ValueError):
                pass
    current = can_drive(user)
    status = ('development' if approval.get('kind') == 'development' else 'reviewed') if current else (
        'expired' if identity['status'] == 'expired' or document_expired or (expiry and expiry <= datetime.now(timezone.utc)) else 'not_verified')
    if expiry and expiry <= datetime.now(timezone.utc):
        for key in ('dl', 'rc', 'insurance'):
            if checks[key] == 'verified':
                checks[key] = 'expired'
    if user.get('development') is True:
        checks = {key: 'not_checked' if value == 'verified' else value for key, value in checks.items()}
    return {'status': status, 'expires_at': expiry.isoformat() if expiry else None, 'checks': checks, 'identity_review': identity}


class ReviewsService:
    def __init__(self, store):
        self.store = store

    def dispatch(self, action, user, payload):
        if not isinstance(user, dict) or not isinstance(user.get('id'), str):
            raise ReviewsError('Authentication required.', 401, 'authentication_required')
        if not isinstance(payload, dict):
            raise ReviewsError('Send a valid review request.')
        with self.store.read() as tx:
            actor = tx.get('users', user['id'])
            if not current_actor_matches(actor, user):
                raise ReviewsError('Authentication required.', 401, 'authentication_required')
            if actor.get('role') != 'member':
                raise ReviewsError('Reviews are available only to member accounts.', 403, 'member_required')
            if action == 'reviews':
                return self._reviews(tx, actor)
            if action == 'driver_profile':
                return self._driver_profile(tx, actor, payload)
            raise ReviewsError('Review action not found.', 404, 'not_found')

    @staticmethod
    def _completed(tx):
        trips = {t['id']: t for t in tx.list('trips')}
        users = {u['id']: u for u in tx.list('users')}
        bookings = {b['id']: b for b in tx.list('bookings')
                    if b.get('status') == 'segment_completed'
                    and trips.get(b.get('trip_id'), {}).get('status') == 'completed'
                    and trips.get(b.get('trip_id'), {}).get('driver_id') == b.get('driver_id')
                    and b.get('driver_id') != b.get('passenger_id')
                    and all(users.get(b.get(k), {}).get('role') == 'member' for k in ('driver_id', 'passenger_id'))}
        return trips, users, bookings

    @staticmethod
    def _valid_ratings(tx, bookings):
        valid, seen = [], set()
        for row in sorted(tx.list('ratings'), key=lambda r: (str(r.get('created_at', '')), str(r.get('id', '')))):
            booking = bookings.get(row.get('booking_id'))
            stars = row.get('stars')
            if not booking or type(stars) is not int or not 1 <= stars <= 5:
                continue
            pair = (row.get('author_id'), row.get('subject_id'))
            participants = (booking['passenger_id'], booking['driver_id'])
            if pair != participants and pair != participants[::-1]:
                continue
            key = (booking['id'], row['author_id'])
            if key in seen:
                continue
            seen.add(key)
            valid.append(row)
        return valid

    def _reviews(self, tx, actor):
        _, users, bookings = self._completed(tx)
        ratings = self._valid_ratings(tx, bookings)
        own_id = actor['id']
        def private(row):
            return {'id': row['id'], 'booking_id': row['booking_id'], 'stars': row['stars'],
                    'comment': row.get('comment') if isinstance(row.get('comment'), str) else '',
                    'created_at': row.get('created_at'), 'author_name': _name(users.get(row['author_id'])),
                    'subject_name': _name(users.get(row['subject_id'])), 'subject_id': row['subject_id'],
                    'publish_comment': row.get('publish_comment') is True}
        given = [private(row) for row in ratings if row['author_id'] == own_id]
        received = [private(row) for row in ratings if row['subject_id'] == own_id]
        rated = {row['booking_id'] for row in ratings if row['author_id'] == own_id}
        eligible = []
        for booking in bookings.values():
            if own_id not in (booking['passenger_id'], booking['driver_id']) or booking['id'] in rated:
                continue
            subject = booking['driver_id'] if own_id == booking['passenger_id'] else booking['passenger_id']
            eligible.append({'booking_id': booking['id'], 'subject_id': subject, 'subject_name': _name(users.get(subject)),
                             'origin': _point(booking.get('pickup')), 'destination': _point(booking.get('dropoff'))})
        return {'given': given[::-1], 'received': received[::-1], 'eligible': eligible}

    def _driver_profile(self, tx, actor, payload):
        target_id = payload.get('user_id')
        if not isinstance(target_id, str) or not target_id or len(target_id) > 100:
            raise ReviewsError('Choose a driver profile.')
        driver = tx.get('users', target_id)
        trips, users, bookings = self._completed(tx)
        driven = [trip for trip in trips.values() if trip.get('driver_id') == target_id]
        if (not is_active_account(driver) or driver.get('role') != 'member' or _blocked(tx, actor['id'], target_id)
                or not (driven or driver.get('driver_approval'))):
            raise ReviewsError('Driver profile not found.', 404, 'not_found')
        ratings = [row for row in self._valid_ratings(tx, bookings)
                   if row['subject_id'] == target_id and bookings[row['booking_id']]['driver_id'] == target_id
                   and row['author_id'] == bookings[row['booking_id']]['passenger_id']]
        stars = [row['stars'] for row in ratings]
        public = []
        for row in reversed(ratings):
            if _blocked(tx, actor['id'], row['author_id']):
                continue
            review = {'author_name': (_name(users.get(row['author_id'])).split() or [''])[0],
                      'stars': row['stars'], 'created_at': row.get('created_at')}
            if row.get('publish_comment') is True and isinstance(row.get('comment'), str):
                review['comment'] = row['comment']
            public.append(review)
        vehicle = driver.get('vehicle') if isinstance(driver.get('vehicle'), dict) else {}
        return {'driver': {'id': target_id, 'name': _name(driver), 'development': bool(driver.get('development', True)),
                           'vehicle_model': vehicle.get('model') if isinstance(vehicle.get('model'), str) else '',
                           'verification': _verification(driver), 'identity_review': identity_review_summary(driver),
                           'rating_average': round(sum(stars) / len(stars), 2) if len(stars) >= 3 else None,
                           'rating_count': len(stars),
                           'completed_trip_count': sum(t.get('status') == 'completed' for t in driven)},
                'reviews': public}
