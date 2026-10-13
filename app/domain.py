"""Closed-beta application service. All booking mutations serialize in SQLite."""
import math
import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from .community import CommunityService
from .auth import is_active_account, current_actor_matches
from .matching import evaluate, inventory, Incompatible, distance, project
from .permissions import PermissionDenied, access_summary, authorize, can_drive, can_request, identity_review_summary
from .routing import RoutingError
from .user_projection import account_user, operations_user

IST = timezone(timedelta(hours=5, minutes=30))
BASELINE = '20 km endpoint-radius baseline among the same time-, detour- and capacity-eligible supply; not a replica of a competitor.'
PLACES = [
    ('Kondapur', 17.460, 78.357), ('LB Nagar', 17.3457, 78.5522),
    ('Suryapet', 17.139, 79.620), ('Kodad', 16.998, 79.966),
    ('Nandigama', 16.771, 80.285), ('Vijayawada', 16.506, 80.648),
    ('Shamshabad', 17.260, 78.388), ('Shadnagar', 17.071, 78.209),
    ('Jadcherla', 16.760, 78.145), ('Mahabubnagar', 16.748, 77.986),
    ('Addakal', 16.491, 77.950), ('Kothakota', 16.374, 77.971),
    ('Wanaparthy', 16.362, 78.062),
]
# Geography limits the local pilot; these polylines never determine matches.
CORRIDORS = [ [[78.357,17.460],[78.5522,17.3457],[79.620,17.139],[79.966,16.998],[80.285,16.771],[80.648,16.506]],
              [[78.357,17.460],[78.388,17.260],[78.209,17.071],[78.145,16.760],[77.950,16.491],[77.971,16.374],[78.062,16.362]],
              [[78.145,16.760],[77.986,16.748]] ]


class DomainError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def now():
    return datetime.now(timezone.utc)


def uid():
    return uuid.uuid4().hex


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DomainError(f'{name} must be a whole number from {low} to {high}.')
    return value


def point(value):
    try:
        if not isinstance(value, dict) or isinstance(value.get('lat'), bool) or isinstance(value.get('lon'), bool):
            raise ValueError()
        lat, lon = float(value['lat']), float(value['lon'])
        label = str(value.get('label', '')).strip()
        if not label or len(label) > 120 or not math.isfinite(lat+lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError()
        p = {'label': label, 'lat': lat, 'lon': lon}
        if min(project(p, line)['off_route_m'] for line in CORRIDORS) > 35000:
            raise DomainError('Choose a point in the Hyderabad east or south pilot corridors.')
        return p
    except (ValueError, TypeError, KeyError):
        raise DomainError('Enter a place label and valid latitude and longitude.')


def timestamp(value, name):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise DomainError(f'{name} needs a date, time and timezone.')


def safe_user(user):
    return account_user(user)


class Service:
    def __init__(self, store, router):
        self.store, self.router = store, router
        self.community = CommunityService(store)

    def dispatch(self, action, user, payload):
        if action == 'bootstrap':
            return {'places': [{'label': n, 'lat': a, 'lon': o} for n,a,o in PLACES]}
        if not user:
            raise DomainError('Sign in to your invited development account.', 401)
        if not isinstance(payload, dict):
            raise DomainError('Send a JSON object.')
        public_actions = {'state', 'operations', 'preview', 'publish', 'search', 'request',
                          'accept', 'decline', 'cancel_booking', 'start_trip', 'complete_segment',
                          'complete_trip', 'cancel_trip', 'rate', 'report_safety', 'block_person', 'resolve_report',
                          'board_segment',
                          'profile', 'update_profile', 'contact', 'chat', 'chats', 'send_message',
                          'mark_chat_read', 'notifications', 'mark_notification_read'}
        if action not in public_actions:
            raise DomainError('Unknown action.', 404)
        user_id = user.get('id') if isinstance(user, dict) else None
        if not user_id:
            raise DomainError('Sign in to your invited development account.', 401)
        # Never authorize from the request's possibly stale actor snapshot.
        with self.store.read() as tx:
            current_user = tx.get('users', user_id)
        if not current_actor_matches(current_user, user):
            raise DomainError('This account is no longer available.', 401)
        user = safe_user(current_user)
        try:
            authorize(current_user, action)
        except PermissionDenied as exc:
            raise DomainError(str(exc), 403) from exc
        if action in {'profile', 'update_profile', 'contact', 'chat', 'chats', 'send_message',
                      'mark_chat_read', 'notifications', 'mark_notification_read'}:
            return self.community.dispatch(action, user, payload)
        method = getattr(self, '_' + action, None)
        if method is None or action.startswith('_'):
            raise DomainError('Unknown action.', 404)
        try:
            result = method(user, payload)
            if action == 'state' and isinstance(result, dict):
                with self.store.read() as tx:
                    result['access'] = access_summary(tx.get('users', user['id']) or {})
            return result
        except RoutingError as exc:
            raise DomainError(str(exc), 503) from exc

    def _get(self, tx, collection, id):
        row = tx.get(collection, id)
        if not row:
            raise DomainError('This record was not found. Refresh and try again.', 404)
        return row

    def _event(self, tx, user, kind, object_id, details=None):
        actor = tx.get('users', user['id']) or {}
        row = {'id':uid(),'actor_id':user['id'],'kind':kind,'object_id':object_id,
               'at':now().isoformat(),'details':details or {},'development':actor.get('development') is True}
        tx.put('events',row['id'],row)
        self.community.notify_lifecycle(tx, kind, object_id, user['id'], row['at'])

    def _route_log(self, tx, route, reason, object_id):
        row = {'id':uid(),'object_id':object_id,'reason':reason,'provider':route['provider'],
               'distance_m':route['distance_m'],'duration_s':route['duration_s'],
               'calculated_at':route['calculated_at'],'calculation_id':route.get('calculation_id'),
               'traffic':False}
        tx.put('route_calculations',row['id'],row)

    def _current_actor(self, tx, user, action):
        actor = tx.get('users', user['id'])
        if not current_actor_matches(actor, user):
            raise DomainError('This account is no longer available.', 401)
        try:
            authorize(actor, action)
        except PermissionDenied as exc:
            raise DomainError(str(exc), 403) from exc
        return safe_user(actor)

    @staticmethod
    def _vehicle_identity(value):
        if not isinstance(value, dict):
            return None
        fields = [value.get(key, '') for key in ('model', 'plate')]
        if any(not isinstance(field, str) for field in fields):
            return None
        return tuple(field.strip().casefold() for field in fields)

    def _driver_available(self, tx, trip):
        driver = tx.get('users', trip.get('driver_id', ''))
        return bool(driver and can_drive(driver)
                    and self._vehicle_identity(trip.get('driver_vehicle', {})) is not None
                    and self._vehicle_identity(trip.get('driver_vehicle', {})) == self._vehicle_identity(driver.get('vehicle', {})))

    @staticmethod
    def _same_account_pool(tx, first_id, second_id):
        """Development fixtures and actual members never form a booking pair."""
        first, second = tx.get('users', first_id), tx.get('users', second_id)
        return bool(is_active_account(first) and is_active_account(second)
                    and first.get('role') == second.get('role') == 'member'
                    and (first.get('development') is True) == (second.get('development') is True))

    @staticmethod
    def _require_passenger_identity(tx, booking):
        passenger = tx.get('users', booking.get('passenger_id', '')) or {}
        if not can_request(passenger):
            raise DomainError('A passenger needs a current identity review before this ride can continue.', 409)

    def _require_available(self, tx, trip):
        if not self._driver_available(tx, trip):
            raise DomainError('This trip no longer has current approval for its listed vehicle.', 409)

    def _current_driver_projection(self, trip):
        # Stored trip/car identity is immutable. Only current trust status is projected.
        from .reviews import _verification
        with self.store.read() as tx:
            driver = tx.get('users', trip.get('driver_id', '')) or {}
            available = self._driver_available(tx, trip)
            summary = _verification(driver)
        checks = dict(summary['checks'])
        if not available:
            for key in ('dl', 'rc', 'insurance', 'selfie'):
                if checks[key] == 'verified':
                    checks[key] = 'expired' if summary['status'] == 'expired' else 'not_checked'
        return {'identity_review': identity_review_summary(driver), 'verification': checks, 'verification_status': summary['status'] if available else (
                    'expired' if summary['status'] == 'expired' else 'not_verified'),
                'driver_available': available}

    def _trip_view(self, trip, bookings):
        return {**trip, **self._current_driver_projection(trip),
                'inventory':inventory(trip,[b for b in bookings if b['trip_id']==trip['id']])}

    def _booking_view(self, booking, trip, viewer_id):
        counterpart_id = booking['passenger_id'] if viewer_id == booking['driver_id'] else booking['driver_id']
        view = {**booking, 'trip_status':trip['status'], 'trip_departure':trip['departure'],
                'counterpart_summary':self.community.public_summary(counterpart_id)}
        view['match'] = {**(booking.get('match') or {}), **self._current_driver_projection(trip)}
        view['can_contact'] = self.community.contact_available(booking, trip, viewer_id)
        return view

    @staticmethod
    def _flag_late_cancellation(booking, at=None):
        if not booking.get('accepted_at'):
            return
        pickup_at = (booking.get('match') or {}).get('pickup_at')
        if not isinstance(pickup_at, str):
            return
        try:
            pickup = timestamp(pickup_at, 'Pickup time')
        except DomainError:
            return
        at = at or now()
        if at > pickup - timedelta(hours=2):
            booking['late_cancellation'] = True
            booking['late_cancellation_at'] = at.isoformat()

    def _state(self, user, payload):
        with self.store.read() as tx:
            trips, bookings = tx.list('trips'), tx.list('bookings')
            tripmap = {t['id']:t for t in trips}
            own = [b for b in bookings if user['id'] in (b['driver_id'],b['passenger_id'])]
            return {'trips':[self._trip_view(t,bookings) for t in trips if t['driver_id']==user['id']],
                    'bookings':[self._booking_view(b,tripmap[b['trip_id']],user['id']) for b in own],
                    'requests':[r for r in tx.list('requests') if r['passenger_id']==user['id']],
                    'ratings':[r for r in tx.list('ratings') if user['id'] in (r['author_id'],r['subject_id'])],
                    'safety_reports':[r for r in tx.list('safety_reports') if r['reporter_id']==user['id']],
                    'blocks':[b for b in tx.list('blocks') if b['blocker_id']==user['id']]}

    def _preview(self, user, payload):
        origin, destination = point(payload.get('origin')), point(payload.get('destination'))
        departure = timestamp(payload.get('departure'), 'Departure')
        if not now() < departure < now()+timedelta(days=90):
            raise DomainError('Choose a future departure within the next 90 days.')
        seats = integer(payload.get('seats'), 'Seats', 1, 6)
        detour = integer(payload.get('max_detour_minutes'), 'Maximum detour', 0, 15)
        if detour not in (0,5,10,15):
            raise DomainError('Choose a detour of 0, 5, 10 or 15 minutes.')
        if distance(origin,destination) < 1000:
            raise DomainError('Choose two different points at least 1 km apart.')
        route = self.router.route([origin,destination])
        row = {'id':uid(),'driver_id':user['id'],'origin':origin,'destination':destination,
               'departure':departure.astimezone(IST).isoformat(),'seats':seats,'max_detour_minutes':detour,
               'route':route,'expires_at':(now()+timedelta(minutes=20)).isoformat()}
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'preview')
            row['driver_vehicle'] = user.get('vehicle', {})
            tx.put('previews',row['id'],row)
            self._route_log(tx,route,'driver_preview',row['id'])
        return {'preview':row}

    def _publish(self, user, payload):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'publish')
            preview = self._get(tx,'previews',payload.get('preview_id'))
            if preview['driver_id'] != user['id']:
                raise DomainError('Only the preview owner can publish it.',403)
            self._require_available(tx, preview)
            if preview.get('trip_id'):
                return {'trip':self._trip_view(tx.get('trips',preview['trip_id']),tx.list('bookings'))}
            if timestamp(preview['expires_at'],'Expiry') < now() or timestamp(preview['departure'],'Departure') < now():
                raise DomainError('The route preview expired. Calculate it again.',409)
            trip = {k:v for k,v in preview.items() if k not in ('expires_at',)}
            trip.update(id=uid(),driver_name=user['name'],driver_vehicle=user.get('vehicle',{}),
                        verification=user.get('verification',{}),status='published',created_at=now().isoformat(),
                        version=1,detour_minutes=0,development=user.get('development') is True)
            tx.put('trips',trip['id'],trip)
            preview['trip_id']=trip['id']; tx.put('previews',preview['id'],preview)
            self._event(tx,user,'trip_published',trip['id'])
            return {'trip':self._trip_view(trip,[])}

    def _new_match(self, trip, request, calculation, completed=0):
        from .route_preview import passenger_route_preview
        preview = passenger_route_preview(calculation.get('proposed_route'),
                                          calculation.get('routed_pickup'), calculation.get('routed_dropoff'))
        return {'id':uid(),'request_id':request['id'],'trip_id':trip['id'],'driver_name':trip['driver_name'],
                'vehicle':trip.get('driver_vehicle',{}), **self._current_driver_projection(trip),
                'pickup':request['origin'],'dropoff':request['destination'],'passenger_seats':request['seats'],
                'route_provider':trip['route']['provider'],'created_at':now().isoformat(),
                'driver_completed_trips':completed,
                **({'preview_route': preview} if preview is not None else {}),
                **{k:v for k,v in calculation.items() if k not in ('proposed_route','pickup_schedule')}}

    def _search(self, user, payload):
        origin,destination = point(payload.get('origin')),point(payload.get('destination'))
        start,end = timestamp(payload.get('window_start'),'Window start'),timestamp(payload.get('window_end'),'Window end')
        if end <= start or end-start > timedelta(hours=12) or end < now() or start > now()+timedelta(days=90):
            raise DomainError('Choose a future pickup window up to 12 hours, within 90 days.')
        if distance(origin,destination) < 1000:
            raise DomainError('Choose points at least 1 km apart.')
        request = {'id':uid(),'passenger_id':user['id'],'passenger_name':user['name'],'origin':origin,'destination':destination,
                   'window_start':start.astimezone(IST).isoformat(),'window_end':end.astimezone(IST).isoformat(),
                   'seats':integer(payload.get('seats'),'Seats',1,1),'created_at':now().isoformat(),'development':user.get('development') is True}
        with self.store.read() as tx:
            trips,bookings=tx.list('trips'),tx.list('bookings')
            available_trip_ids = {trip['id'] for trip in trips if self._driver_available(tx, trip)
                                  and self._same_account_pool(tx, user['id'], trip['driver_id'])}
            blocked_pairs={(b['blocker_id'],b['blocked_id']) for b in tx.list('blocks')}
        matches, errors, logs, evaluations = [],[],[],[]
        for trip in trips:
            if trip['id'] not in available_trip_ids:
                continue
            if (user['id'],trip['driver_id']) in blocked_pairs or (trip['driver_id'],user['id']) in blocked_pairs:
                continue
            departure=timestamp(trip['departure'],'Departure')
            if trip['status'] != 'published' or trip['driver_id']==user['id'] or departure < now() or departure > end:
                continue
            # Avoid irrelevant dates without claiming traffic-aware timing.
            if departure+timedelta(seconds=trip['route']['duration_s']+trip['max_detour_minutes']*60) < start:
                continue
            try:
                calculation=evaluate(trip,request,[b for b in bookings if b['trip_id']==trip['id']],self.router)
                completed=sum(t['status']=='completed' and t['driver_id']==trip['driver_id'] for t in trips)
                match=self._new_match(trip,request,calculation,completed)
                match['driver_summary']=self.community.public_summary(trip['driver_id'])
                matches.append(match)
                logs.append(calculation['proposed_route'])
                evaluations.append({'trip_id':trip['id'],'outcome':'matched','total_detour_minutes':calculation['total_driver_detour_minutes']})
            except Incompatible as exc:
                evaluations.append({'trip_id':trip['id'],'outcome':'incompatible','reason':str(exc),'details':exc.details})
                continue
            except RoutingError as exc:
                errors.append({'trip_id':trip['id'],'error':str(exc)})
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'search')
            request['development'] = user.get('development') is True
            current_trips = {t['id']: t for t in tx.list('trips')}
            matches = [m for m in matches if m['trip_id'] in current_trips
                       and current_trips[m['trip_id']]['status'] == 'published'
                       and self._driver_available(tx, current_trips[m['trip_id']])
                       and self._same_account_pool(tx, user['id'], current_trips[m['trip_id']]['driver_id'])
                       and not self._pair_blocked(tx, user['id'], current_trips[m['trip_id']]['driver_id'])]
            for match in matches:
                match.update(self._current_driver_projection(current_trips[match['trip_id']]))
            traditional=sum(m['baseline_match'] for m in matches)
            metrics={'traditional_match_count':traditional,'route_aware_match_count':len(matches),
                     'incremental_matches':len(matches)-traditional,
                     'match_lift_percentage':round((len(matches)-traditional)/traditional*100,2) if traditional and not errors else None,
                     'complete':not errors,'evaluation_errors':len(errors),'baseline_definition':BASELINE}
            request['metrics']=metrics
            matched_trip_ids = {match['trip_id'] for match in matches}
            request['evaluations'] = [({**row, 'outcome':'unavailable', 'reason':'Availability changed during search'}
                                       if row['outcome'] == 'matched' and row['trip_id'] not in matched_trip_ids else row)
                                      for row in evaluations]
            tx.put('requests',request['id'],request)
            for match in matches: tx.put('matches',match['id'],match)
            for route in logs: self._route_log(tx,route,'passenger_search',request['id'])
            self._event(tx,user,'search_completed' if not errors else 'search_incomplete',request['id'],{'metrics':metrics,'errors':errors})
        return {'request':request,'matches':sorted(matches,key=lambda m:m['pickup_at']),'metrics':metrics}

    def _request(self, user, payload):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'request')
            match=self._get(tx,'matches',payload.get('match_id'))
            request=self._get(tx,'requests',match['request_id'])
            if request['passenger_id'] != user['id']:
                raise DomainError('This match belongs to another passenger.',403)
            if request.get('seats') != 1:
                raise DomainError('A seat request is for one passenger. Search again for one seat.')
            trip=self._get(tx,'trips',match['trip_id'])
            self._require_available(tx, trip)
            if not self._same_account_pool(tx, user['id'], trip['driver_id']):
                raise DomainError('This ride is no longer available.',409)
            if self._pair_blocked(tx,user['id'],trip['driver_id']):
                raise DomainError('This ride is no longer available.',409)
            allbookings = tx.list('bookings')
            # A passenger may hold only one pending or accepted segment per trip,
            # even if they have created more than one search request.
            for booking in allbookings:
                if (booking.get('passenger_id') == user['id'] and booking.get('trip_id') == trip['id']
                        and booking.get('status') in {'pending', 'accepted'}):
                    return {'booking':self._booking_view(booking,trip,user['id'])}
            # Preserve terminal outcomes for retries of the original request.
            for booking in allbookings:
                if booking['request_id']==request['id'] and booking['trip_id']==trip['id']:
                    return {'booking':self._booking_view(booking,trip,user['id'])}
            if trip['status']!='published' or timestamp(trip['departure'],'Departure')<now():
                raise DomainError('This trip is no longer accepting requests.',409)
            if now()-timestamp(match['created_at'],'Match date')>timedelta(minutes=20):
                raise DomainError('This match has expired. Search again.',409)
            pending = sum(booking.get('passenger_id') == user['id'] and booking.get('status') == 'pending'
                          for booking in allbookings)
            if pending >= 5:
                raise DomainError('You already have five pending seat requests. Wait for a response before requesting another.', 429)
            limit = tx.get('seat_request_limits', user['id']) or {'id': user['id'], 'timestamps': []}
            cutoff = now().timestamp() - 3600
            recent = [stamp for stamp in limit.get('timestamps', [])
                      if isinstance(stamp, (int, float)) and stamp > cutoff]
            if len(recent) >= 10:
                raise DomainError('You have reached the hourly seat-request limit. Try again later.', 429)
            recent.append(now().timestamp())
            limit['timestamps'] = recent
            tx.put('seat_request_limits', user['id'], limit)
            booking={'id':uid(),'trip_id':trip['id'],'request_id':request['id'],'match_id':match['id'],
                     'driver_id':trip['driver_id'],'passenger_id':user['id'],'driver_name':trip['driver_name'],
                     'passenger_name':user['name'],'pickup':request['origin'],'dropoff':request['destination'],
                     'seats':request['seats'],'status':'pending','match':match,'start_m':match['start_m'],'end_m':match['end_m'],
                     'window_start':request['window_start'],'window_end':request['window_end'],
                     'created_at':now().isoformat(),'development':user.get('development') is True}
            tx.put('bookings',booking['id'],booking)
            self._event(tx,user,'seat_requested',booking['id'])
            return {'booking':self._booking_view(booking,trip,user['id'])}

    def _accept(self, user, payload):
        # BEGIN IMMEDIATE is deliberately held through road re-evaluation in this small
        # local slice. Other processes cannot confirm capacity using a stale snapshot.
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'accept')
            booking=self._get(tx,'bookings',payload.get('booking_id'))
            trip=self._get(tx,'trips',booking['trip_id'])
            if trip['driver_id']!=user['id']: raise DomainError('Only the driver can accept.',403)
            self._require_available(tx, trip)
            self._require_passenger_identity(tx, booking)
            if not self._same_account_pool(tx, booking['driver_id'], booking['passenger_id']):
                raise DomainError('This ride is no longer available.',409)
            if self._pair_blocked(tx,booking['driver_id'],booking['passenger_id']):
                raise DomainError('This ride is no longer available.',409)
            if booking['status']=='accepted': return {'booking':self._booking_view(booking,trip,user['id'])}
            if booking['status']!='pending' or trip['status']!='published' or timestamp(trip['departure'],'Departure')<now():
                raise DomainError('This request or trip is no longer available.',409)
            allbookings=tx.list('bookings')
            if any(b['request_id']==booking['request_id'] and b['status'] in ('accepted','segment_completed') for b in allbookings):
                raise DomainError('Another driver has already confirmed this passenger request.',409)
            if any(b['id'] != booking['id'] and b['passenger_id']==booking['passenger_id']
                   and b['trip_id']==trip['id'] and b['status']=='accepted' for b in allbookings):
                raise DomainError('This passenger already has an accepted booking on this trip.',409)
            request=self._get(tx,'requests',booking['request_id'])
            try:
                calculation=evaluate(trip,request,[b for b in allbookings if b['trip_id']==trip['id']],self.router)
            except Incompatible as exc:
                raise DomainError('Availability changed: '+str(exc),409)
            # Routing can take seconds even while this write transaction excludes revocation.
            # Recheck wall-clock expiry immediately before accepting the seat.
            user = self._current_actor(tx, user, 'accept')
            self._require_available(tx, trip)
            self._require_passenger_identity(tx, booking)
            booking.update(status='accepted',accepted_at=now().isoformat())
            booking['match']={**booking['match'],**{k:v for k,v in calculation.items() if k not in ('proposed_route','pickup_schedule')}}
            tx.put('bookings',booking['id'],booking)
            for alternative in allbookings:
                if alternative['id']!=booking['id'] and alternative['request_id']==booking['request_id'] and alternative['status']=='pending':
                    alternative.update(status='cancelled',reason='Passenger request confirmed on another trip',cancelled_by='system')
                    tx.put('bookings',alternative['id'],alternative)
                    self._event(tx,user,'booking_cancelled',alternative['id'],{'reason':alternative['reason']})
            trip['version']+=1
            trip['detour_minutes']=calculation['total_driver_detour_minutes']
            trip['current_route']=calculation['proposed_route']
            # Keep every accepted booking's latest promised pickup/drop time consistent.
            departure=timestamp(trip['departure'],'Departure')
            for old in allbookings:
                if old['trip_id']==trip['id'] and old['status']=='accepted':
                    times=calculation['pickup_schedule'][old['id']]
                    old['match']['pickup_at']=(departure+timedelta(seconds=times['pickup'])).isoformat()
                    old['match']['dropoff_at']=(departure+timedelta(seconds=times['dropoff'])).isoformat()
                    tx.put('bookings',old['id'],old)
            tx.put('trips',trip['id'],trip)
            self._route_log(tx,calculation['proposed_route'],'acceptance_recheck',booking['id'])
            self._event(tx,user,'seat_accepted',booking['id'],{'detour_minutes':trip['detour_minutes'],'trip_version':trip['version']})
            return {'booking':self._booking_view(booking,trip,user['id'])}

    def _decline(self,user,payload):
        return self._change_booking(user,payload,'declined')

    def _cancel_booking(self,user,payload):
        return self._change_booking(user,payload,'cancelled')

    def _change_booking(self,user,payload,status):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'decline' if status == 'declined' else 'cancel_booking')
            booking=self._get(tx,'bookings',payload.get('booking_id')); trip=self._get(tx,'trips',booking['trip_id'])
            if status=='declined' and user['id']!=booking['driver_id']: raise DomainError('Only the driver can decline.',403)
            if user['id'] not in (booking['driver_id'],booking['passenger_id']): raise DomainError('This booking belongs to other people.',403)
            if booking['status']==status: return {'booking':self._booking_view(booking,trip,user['id'])}
            if booking['status'] not in ('pending','accepted') or (status=='declined' and booking['status']!='pending') or trip['status']!='published':
                raise DomainError('This booking can no longer be changed. In-progress trips require operator assistance.',409)
            reason=str(payload.get('reason','')).strip()
            if status=='cancelled' and not reason: raise DomainError('Add a cancellation reason.')
            booking.update(status=status,reason=reason[:500],cancelled_by=user['id'],updated_at=now().isoformat())
            if status == 'cancelled':
                self._flag_late_cancellation(booking)
            tx.put('bookings',booking['id'],booking)
            trip['version']+=1
            # Preserve the last committed stop plan after cancellation. Removing stops
            # could make another passenger's pickup earlier than their agreed window.
            # On next acceptance evaluate() explicitly validates all remaining windows.
            trip['schedule_note']='Last accepted timetable; cancellation released only the seat segment.'
            tx.put('trips',trip['id'],trip)
            self._event(tx,user,'booking_'+status,booking['id'],{'reason':reason[:500]})
            return {'booking':self._booking_view(booking,trip,user['id'])}

    def _start_trip(self,user,payload):
        return self._trip_transition(user,payload,'started')

    def _complete_trip(self,user,payload):
        return self._trip_transition(user,payload,'completed')

    def _cancel_trip(self,user,payload):
        return self._trip_transition(user,payload,'cancelled')

    def _trip_transition(self,user,payload,status):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, {'started':'start_trip','completed':'complete_trip','cancelled':'cancel_trip'}[status])
            if status == 'started':
                user = self._current_actor(tx, user, 'start_trip')
            trip=self._get(tx,'trips',payload.get('trip_id'))
            if trip['driver_id']!=user['id']: raise DomainError('Only the driver can change this trip.',403)
            if status == 'started':
                self._require_available(tx, trip)
            bookings=[b for b in tx.list('bookings') if b['trip_id']==trip['id']]
            if status == 'started':
                for passenger_booking in bookings:
                    if passenger_booking['status'] == 'accepted':
                        self._require_passenger_identity(tx, passenger_booking)
            if trip['status']==status: return {'trip':self._trip_view(trip,bookings)}
            allowed={'started':'published','completed':'started','cancelled':'published'}
            if trip['status']!=allowed[status]: raise DomainError('This trip status cannot make that transition.',409)
            if status=='completed' and any(b['status']=='accepted' for b in bookings):
                raise DomainError('Complete every accepted passenger segment before completing the trip.',409)
            if status=='cancelled' and not str(payload.get('reason','')).strip(): raise DomainError('Add a cancellation reason.')
            trip.update(status=status,version=trip['version']+1)
            trip[status+'_at']=now().isoformat()
            for b in bookings:
                if (status=='cancelled' and b['status'] in ('pending','accepted')) or (status=='started' and b['status']=='pending'):
                    was_accepted = b['status'] == 'accepted'
                    b.update(status='cancelled',cancelled_by=user['id'],reason='Trip cancelled' if status=='cancelled' else 'Trip started before acceptance')
                    if status == 'cancelled' and was_accepted:
                        self._flag_late_cancellation(b)
                    tx.put('bookings',b['id'],b)
                    self._event(tx,user,'booking_cancelled',b['id'],{'reason':b['reason']})
            tx.put('trips',trip['id'],trip)
            self._event(tx,user,'trip_'+status,trip['id'],{'reason':str(payload.get('reason',''))[:500]})
            return {'trip':self._trip_view(trip,bookings)}

    def _complete_segment(self,user,payload):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'complete_segment')
            booking=self._get(tx,'bookings',payload.get('booking_id')); trip=self._get(tx,'trips',booking['trip_id'])
            if user['id'] not in (booking['passenger_id'],booking['driver_id']): raise DomainError('Only the passenger or driver can confirm this segment.',403)
            if booking['status']=='segment_completed': return {'booking':self._booking_view(booking,trip,user['id'])}
            if trip['status']!='started' or booking['status']!='accepted': raise DomainError('Start the trip before completing an accepted segment.',409)
            booking.update(status='segment_completed',completed_at=now().isoformat(),completed_by=user['id'])
            tx.put('bookings',booking['id'],booking)
            self._event(tx,user,'segment_completed',booking['id'])
            return {'booking':self._booking_view(booking,trip,user['id'])}

    def _board_segment(self, user, payload):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'board_segment')
            booking = self._get(tx, 'bookings', payload.get('booking_id'))
            trip = self._get(tx, 'trips', booking['trip_id'])
            if user['id'] != booking.get('passenger_id'):
                raise DomainError('Only the passenger can confirm boarding.', 403)
            if booking.get('boarded_at'):
                return {'booking': self._booking_view(booking, trip, user['id'])}
            if booking.get('status') != 'accepted' or trip.get('status') != 'started':
                raise DomainError('Boarding can be confirmed only for an accepted segment on a started trip.', 409)
            booking['boarded_at'] = now().isoformat()
            booking['boarded_by'] = user['id']
            tx.put('bookings', booking['id'], booking)
            self._event(tx, user, 'seat_boarded', booking['id'])
            return {'booking': self._booking_view(booking, trip, user['id'])}

    def _rate(self,user,payload):
        if user.get('role') != 'member':
            raise DomainError('Only member participants may rate a booking.',403)
        comment=payload.get('comment','')
        if not isinstance(comment,str) or len(comment)>500:
            raise DomainError('Review comment must be text of at most 500 characters.')
        publish_comment=payload.get('publish_comment',False)
        if not isinstance(publish_comment,bool):
            raise DomainError('Choose whether to publish your review comment.')
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'rate')
            booking=self._get(tx,'bookings',payload.get('booking_id')); trip=self._get(tx,'trips',booking['trip_id'])
            if user['id'] not in (booking['passenger_id'],booking['driver_id']): raise DomainError('Only participants may rate this booking.',403)
            if trip['status']!='completed' or booking['status']!='segment_completed': raise DomainError('Ratings open after the completed journey.',409)
            stars=integer(payload.get('stars'),'Rating',1,5)
            id=booking['id']+':'+user['id']
            existing=tx.get('ratings',id)
            if existing: return {'rating':existing}
            rating={'id':id,'booking_id':booking['id'],'author_id':user['id'],
                    'subject_id':booking['driver_id'] if user['id']==booking['passenger_id'] else booking['passenger_id'],
                    'stars':stars,'comment':comment,'publish_comment':publish_comment,'created_at':now().isoformat()}
            tx.put('ratings',id,rating); self._event(tx,user,'rating_created',id)
            return {'rating':rating}


    @staticmethod
    def _pair_blocked(tx, first, second):
        return bool(tx.get('blocks', first+':'+second) or tx.get('blocks', second+':'+first))

    def _safety_participants(self, tx, user, booking_id):
        booking=self._get(tx,'bookings',booking_id)
        if user['id'] not in (booking['driver_id'],booking['passenger_id']):
            raise DomainError('Only participants can use safety controls for this booking.',403)
        subject=booking['passenger_id'] if user['id']==booking['driver_id'] else booking['driver_id']
        return booking,subject

    def _report_safety(self,user,payload):
        category=payload.get('category')
        details=payload.get('details')
        key=payload.get('idempotency_key')
        if category not in ('unsafe_driving','harassment','identity_mismatch','other'):
            raise DomainError('Choose a safety report category.')
        if not isinstance(details,str) or not 10 <= len(details.strip()) <= 1000:
            raise DomainError('Describe the concern in 10 to 1000 characters.')
        if not isinstance(key,str) or not 8 <= len(key) <= 100 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in key):
            raise DomainError('A valid report request identifier is required.')
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'report_safety')
            booking,subject=self._safety_participants(tx,user,payload.get('booking_id'))
            report_id=user['id']+':'+key
            existing=tx.get('safety_reports',report_id)
            if existing:
                if (existing['booking_id'],existing['category'],existing['details']) != (booking['id'],category,details.strip()):
                    raise DomainError('This report request was already used. Refresh and try again.',409)
                return {'report':existing}
            report={'id':report_id,'booking_id':booking['id'],'reporter_id':user['id'],
                    'subject_id':subject,'category':category,'details':details.strip(),
                    'status':'open','created_at':now().isoformat(),
                    'development':(tx.get('users',user['id']) or {}).get('development') is True}
            tx.put('safety_reports',report_id,report)
            # Free-text details stay in the access-controlled report, not event logs.
            self._event(tx,user,'safety_report_created',report_id,{'category':category})
            return {'report':report}

    def _block_person(self,user,payload):
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'block_person')
            source,subject=self._safety_participants(tx,user,payload.get('booking_id'))
            block_id=user['id']+':'+subject
            block=tx.get('blocks',block_id)
            if not block:
                block={'id':block_id,'blocker_id':user['id'],'blocked_id':subject,
                       'booking_id':source['id'],'created_at':now().isoformat()}
                tx.put('blocks',block_id,block)
                self._event(tx,user,'person_blocked',block_id)
            affected=[]
            active_unchanged=False
            changed_trips={}
            for booking in tx.list('bookings'):
                if {booking['driver_id'],booking['passenger_id']} != {user['id'],subject}:
                    continue
                if booking['status'] not in ('pending','accepted'):
                    continue
                trip=changed_trips.get(booking['trip_id']) or self._get(tx,'trips',booking['trip_id'])
                booking['live_location_ended_at']=now().isoformat()
                booking['live_location_ended_reason']='blocked'
                if trip['status']=='published':
                    booking.update(status='cancelled',cancelled_by=user['id'],reason='Booking cancelled for safety',updated_at=now().isoformat())
                    trip['version']+=1
                    trip['schedule_note']='Last accepted timetable; cancellation released only the seat segment.'
                    changed_trips[trip['id']]=trip
                    self._event(tx,user,'booking_cancelled',booking['id'],{'reason':'safety_control'})
                elif trip['status']=='started':
                    active_unchanged=True
                tx.put('bookings',booking['id'],booking)
                affected.append(booking['id'])
            for trip in changed_trips.values():
                tx.put('trips',trip['id'],trip)
            return {'block':block,'affected_booking_ids':affected,'active_journey_unchanged':active_unchanged}

    def _resolve_report(self,user,payload):
        resolution=payload.get('resolution')
        if not isinstance(resolution,str) or not 10 <= len(resolution.strip()) <= 1000:
            raise DomainError('Add a resolution in 10 to 1000 characters.')
        with self.store.transaction() as tx:
            user = self._current_actor(tx, user, 'resolve_report')
            report=self._get(tx,'safety_reports',payload.get('report_id'))
            if report['status']=='resolved':
                return {'report':report}
            report.update(status='resolved',resolution=resolution.strip(),resolved_at=now().isoformat(),resolved_by=user['id'])
            tx.put('safety_reports',report['id'],report)
            self._event(tx,user,'safety_report_resolved',report['id'])
            return {'report':report}

    def _operations(self,user,payload):
        can_read_safety='safety.act' in access_summary(user)['staff_capabilities']
        with self.store.read() as tx:
            data={c:tx.list(c) for c in ('users','trips','requests','matches','bookings','ratings','events','route_calculations')}
            data['safety_reports']=tx.list('safety_reports') if can_read_safety else []
        if not can_read_safety:
            # Case audit targets and actors are case access too, even without report text.
            data['events']=[event for event in data['events'] if not event.get('kind','').startswith('safety_report_')]
        # Operations needs rating facts, never participant-only review prose.
        rating_fields=('id','booking_id','author_id','subject_id','stars','created_at')
        data['ratings']=[{key:row[key] for key in rating_fields if key in row} for row in data['ratings']]
        data['users']=[operations_user(u) for u in data['users']]
        data['trips']=[self._trip_view(t,data['bookings']) for t in data['trips']]
        complete=[r for r in data['requests'] if r.get('metrics',{}).get('complete')]
        baseline=sum(r['metrics']['traditional_match_count'] for r in complete)
        route=sum(r['metrics']['route_aware_match_count'] for r in complete)
        matched=sum(r['metrics']['route_aware_match_count']>0 for r in complete)
        accepted=[b for b in data['bookings'] if b.get('accepted_at')]
        declined=[b for b in data['bookings'] if b['status']=='declined']
        finished=[t for t in data['trips'] if t['status']=='completed']
        completed_segments=[b for b in data['bookings'] if b['status']=='segment_completed']
        pct=lambda a,b: round(a/b*100,2) if b else None
        # One final committed detour per trip avoids weighting trips by passenger count.
        detours=[t['detour_minutes'] for t in data['trips'] if any(b['trip_id']==t['id'] for b in accepted)]
        driver_counts=Counter(t['driver_id'] for t in finished)
        passenger_counts=Counter(passenger for passenger, trip_id in {(b['passenger_id'],b['trip_id']) for b in completed_segments})
        data['metrics']={'searches':len(data['requests']),'complete_searches':len(complete),'matched_searches':matched,
            'passenger_match_success_rate':pct(matched,len(complete)),'traditional_match_count':baseline,
            'route_aware_match_count':route,'incremental_matches':route-baseline,'match_lift_percentage':pct(route-baseline,baseline),
            'median_driver_detour_minutes':statistics.median(detours) if detours else None,
            'accepted_bookings':len(accepted),'completed_segments':len(completed_segments),'completed_trips':len(finished),
            'driver_acceptance_rate':pct(len(accepted),len(accepted)+len(declined)),
            'booking_conversion':pct(len({b['request_id'] for b in accepted}),len(data['requests'])),
            'driver_cancellations':sum(b['status']=='cancelled' and bool(b.get('accepted_at')) and b.get('cancelled_by')==b['driver_id'] for b in data['bookings']),
            'passenger_cancellations':sum(b['status']=='cancelled' and bool(b.get('accepted_at')) and b.get('cancelled_by')==b['passenger_id'] for b in data['bookings']),
            'repeat_drivers':sum(n>=2 for n in driver_counts.values()),'repeat_passengers':sum(n>=2 for n in passenger_counts.values()),
            'baseline_definition':BASELINE,
            'development_data_only':all(row.get('development') is True for collection in ('trips','requests','bookings') for row in data[collection]),
            'incomplete_searches_excluded':len(data['requests'])-len(complete)}
        return data
