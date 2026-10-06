"""Replaceable road routing. Failure is never replaced by straight-line driving."""
import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError


class RoutingError(Exception):
    pass


class OSRMProvider:
    name = 'OSRM road routing (no live traffic)'

    def __init__(self, store=None, base_url=None, timeout=8):
        self.store = store
        self.base_url = (base_url or os.environ.get('ROUTING_BASE_URL', 'https://router.project-osrm.org')).rstrip('/')
        self.timeout = timeout
        self.cache = {}

    def route(self, points):
        coords = ';'.join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in points)
        key = hashlib.sha256((self.base_url + coords).encode()).hexdigest()
        if key in self.cache:
            return self.cache[key]
        url = self.base_url + '/route/v1/driving/' + coords + '?overview=full&geometries=geojson&steps=false&radiuses=' + ';'.join('500' for _ in points)
        try:
            with urlopen(Request(url, headers={'User-Agent': 'RouteShare-LocalEvaluation/0.1'}), timeout=self.timeout) as response:
                payload = json.load(response)
            if payload.get('code') != 'Ok' or not payload.get('routes'):
                raise RoutingError('No road route found within 500 m of the selected points. Choose a reachable meeting point.')
            route = payload['routes'][0]
            waypoints = payload.get('waypoints', [])
            if len(waypoints) != len(points) or any(w.get('distance', 99999) > 500 for w in waypoints):
                raise RoutingError('A point is too far from a reachable road. Choose another exact point.')
            result = {'coordinates': route['geometry']['coordinates'], 'distance_m': route['distance'],
                      'duration_s': route['duration'], 'leg_durations_s': [x['duration'] for x in route['legs']],
                      'waypoints': waypoints, 'provider': self.name,
                      'calculated_at': datetime.now(timezone.utc).isoformat(), 'calculation_id': key,
                      'traffic': False, 'snap_limit_m': 500}
            if len(result['coordinates']) < 2 or len(result['leg_durations_s']) != len(points) - 1:
                raise RoutingError('Routing returned an incomplete route. Retry your calculation.')
            self.cache[key] = result
            return result
        except RoutingError:
            raise
        except (URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
            raise RoutingError('Road routing is unavailable. Nothing has been confirmed; retry shortly.') from exc
