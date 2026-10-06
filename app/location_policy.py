"""Directional location windows; a GPS fix never completes a booking."""
from datetime import datetime, timedelta, timezone


def parsed(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def sharing_window(booking, trip, actor_id, at=None):
    at = at or datetime.now(timezone.utc)
    match = booking.get('match') or {}
    pickup = parsed(match.get('pickup_at')) or parsed(booking.get('window_start')) or parsed(trip.get('departure'))
    dropoff = parsed(match.get('dropoff_at')) or parsed(booking.get('window_end'))
    departure = parsed(trip.get('departure'))
    # A missing schedule fails closed; an old accepted booking cannot track forever.
    end = min(dropoff + timedelta(hours=2), departure + timedelta(hours=24)) if dropoff and departure else None
    is_driver = actor_id == booking.get('driver_id')
    start = pickup - timedelta(minutes=30 if is_driver else 15) if pickup else None
    actual_start = parsed(trip.get('started_at')) if trip.get('status') == 'started' else None
    if is_driver and actual_start:
        start = min(start, actual_start) if start else actual_start
    phase = 'onboard' if not is_driver and booking.get('boarded_at') else 'pickup'
    ended = bool(booking.get('live_location_ended_reason')) or booking.get('status') != 'accepted' or trip.get('status') not in ('published', 'started')
    expired = end is None or at >= end
    return {'start_allowed': bool(not ended and not expired and start and at >= start),
            'available_from': start.isoformat() if start else None,
            'hard_expires_at': end.isoformat() if end else None,
            'consent_phase': phase, 'expired': expired,
            'recipient_id': booking.get('passenger_id') if is_driver else booking.get('driver_id')}
