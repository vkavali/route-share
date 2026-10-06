"""Route projection, ordered stop insertion, time windows and half-open seat intervals."""
import math
from datetime import datetime, timedelta


class Incompatible(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def distance(a, b):
    x1, y1 = math.radians(a['lon']), math.radians(a['lat'])
    x2, y2 = math.radians(b['lon']), math.radians(b['lat'])
    d = math.sin((y2-y1)/2)**2 + math.cos(y1)*math.cos(y2)*math.sin((x2-x1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(d)))


def project(point, coordinates):
    """Closest point on the actual route geometry; chainage in metres."""
    best = (float('inf'), 0.0)
    traversed = 0.0
    scale_x = 111195 * math.cos(math.radians(point['lat']))
    scale_y = 111195
    for a, b in zip(coordinates, coordinates[1:]):
        ax, ay = (a[0]-point['lon'])*scale_x, (a[1]-point['lat'])*scale_y
        bx, by = (b[0]-point['lon'])*scale_x, (b[1]-point['lat'])*scale_y
        dx, dy = bx-ax, by-ay
        length = math.hypot(dx, dy)
        fraction = max(0, min(1, -(ax*dx+ay*dy)/(length*length))) if length else 0
        lateral = math.hypot(ax+dx*fraction, ay+dy*fraction)
        segment_m = distance({'lon':a[0],'lat':a[1]}, {'lon':b[0],'lat':b[1]})
        along = traversed + fraction * segment_m
        if lateral < best[0]:
            best = lateral, along
        traversed += segment_m
    return {'off_route_m': best[0], 'along_m': best[1], 'length_m': traversed}


def occupied(bookings):
    # Completed segments remain occupied in history: completion must never reopen
    # an overlapping earlier segment for a second passenger.
    return [b for b in bookings if b['status'] in ('accepted', 'segment_completed')]


def inventory(trip, bookings):
    rows = occupied(bookings)
    length = project(trip['destination'], trip['route']['coordinates'])['length_m']
    boundaries = sorted({0.0, length, *(float(b['start_m']) for b in rows), *(float(b['end_m']) for b in rows)})
    result = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b - a < .01:
            continue
        used = sum(x['seats'] for x in rows if x['start_m'] < b-.01 and x['end_m'] > a+.01)
        result.append({'from_m': round(a, 2), 'to_m': round(b, 2), 'occupied': used, 'available': trip['seats']-used})
    return result


def available_capacity(trip, bookings, start_m, end_m):
    segments = inventory(trip, bookings)
    overlap = [s['available'] for s in segments if s['from_m'] < end_m-.01 and s['to_m'] > start_m+.01]
    return min(overlap) if overlap else trip['seats']


def itinerary(trip, rows, router, pickup_only=None):
    """Stable order along original geometry; drop before pickup at equal chainage."""
    events = []
    for row in rows:
        events.append((row['start_m'], 1, row['id'], 'pickup', row['pickup']))
        if row['id'] != pickup_only:
            events.append((row['end_m'], 0, row['id'], 'dropoff', row['dropoff']))
    events.sort(key=lambda e: (round(e[0], 2), e[1], e[2]))
    points = [trip['origin']] + [e[4] for e in events] + [trip['destination']]
    route = router.route(points) if events else trip['route']
    elapsed, times = 0.0, {}
    for index, (event, duration) in enumerate(zip(events, route['leg_durations_s'])):
        elapsed += duration
        stop = times.setdefault(event[2], {})
        stop[event[3]] = elapsed
        waypoints = route.get('waypoints', [])
        snapped = waypoints[index+1] if len(waypoints) == len(points) else {}
        location = snapped.get('location', [event[4]['lon'], event[4]['lat']])
        stop[event[3]+'_point'] = {'label':event[4]['label'],'lon':location[0],'lat':location[1]}
        stop[event[3]+'_snap_m'] = round(snapped.get('distance', 0), 1)
    return route, times


def evaluate(trip, request, bookings, router):
    start = project(request['origin'], trip['route']['coordinates'])
    end = project(request['destination'], trip['route']['coordinates'])
    if start['off_route_m'] > 15000 or end['off_route_m'] > 15000:
        raise Incompatible('Pickup or drop is too far from this route.')
    if end['along_m'] - start['along_m'] < 100:
        raise Incompatible('The passenger segment runs against the driver route or is too short.')
    capacity = available_capacity(trip, bookings, start['along_m'], end['along_m'])
    if capacity < request['seats']:
        raise Incompatible('There are not enough seats on the overlapping segment.', {'available_seats':capacity,'requested_seats':request['seats']})
    rows = occupied(bookings)
    candidate = {'id': 'candidate:' + request['id'], 'start_m': start['along_m'], 'end_m': end['along_m'],
                 'pickup': request['origin'], 'dropoff': request['destination'],
                 'window_start': request['window_start'], 'window_end': request['window_end']}
    current_route, _ = itinerary(trip, rows, router)
    proposed_route, times = itinerary(trip, rows+[candidate], router)
    detour_s = max(0, proposed_route['duration_s'] - trip['route']['duration_s'])
    if detour_s > trip['max_detour_minutes']*60 + 0.1:
        raise Incompatible('The cumulative detour exceeds the driver limit.', {'calculated_detour_minutes':round(detour_s/60,2),'maximum_detour_minutes':trip['max_detour_minutes'],'provider':proposed_route['provider']})
    departure = datetime.fromisoformat(trip['departure'])
    for row in rows+[candidate]:
        arrival = departure + timedelta(seconds=times[row['id']]['pickup'])
        if not datetime.fromisoformat(row['window_start']) <= arrival <= datetime.fromisoformat(row['window_end']):
            raise Incompatible('This itinerary would miss a passenger pickup window.', {'pickup_at':arrival.isoformat(),'window_start':row['window_start'],'window_end':row['window_end']})
    pickup_route, _ = itinerary(trip, rows+[candidate], router, pickup_only=candidate['id'])
    # Signed, sequential marginal differences. They sum exactly to total added time;
    # negative values can result from a provider selecting a different road route.
    pickup_added = pickup_route['duration_s'] - current_route['duration_s']
    drop_added = proposed_route['duration_s'] - pickup_route['duration_s']
    extra = proposed_route['duration_s'] - current_route['duration_s']
    timing = times[candidate['id']]
    baseline = distance(trip['origin'], request['origin']) <= 20000 and distance(trip['destination'], request['destination']) <= 20000
    # Configurable research UX estimate, not a fare or validated cost split.
    segment_km = (end['along_m']-start['along_m'])/1000
    return {'start_m': start['along_m'], 'end_m': end['along_m'], 'available_seats': capacity,
            'routed_pickup':timing['pickup_point'], 'routed_dropoff':timing['dropoff_point'],
            'pickup_snap_m':timing['pickup_snap_m'], 'dropoff_snap_m':timing['dropoff_snap_m'],
            'pickup_at': (departure+timedelta(seconds=timing['pickup'])).isoformat(),
            'dropoff_at': (departure+timedelta(seconds=timing['dropoff'])).isoformat(),
            'pickup_detour_minutes': round(pickup_added/60, 2), 'dropoff_detour_minutes': round(drop_added/60, 2),
            'incremental_detour_minutes': round(extra/60, 2), 'total_driver_detour_minutes': round(detour_s/60, 2),
            'contribution_inr': round(segment_km*2*request['seats']),
            'contribution_note': 'Illustrative estimate at ₹2 per passenger-km; no payment',
            'baseline_match': baseline, 'proposed_route': proposed_route, 'pickup_schedule': times}
