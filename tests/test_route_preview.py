"""Privacy and geometry checks; all coordinates/providers below are synthetic."""
from copy import deepcopy
import json

import pytest

from app import create_app
from app.route_preview import passenger_route_preview
from test_lifecycle import FixtureRoadProvider, KONDAPUR, VIJAYAWADA, SURYAPET, NANDIGAMA, future_departure, publish, search

P = {'lon': 79.0, 'lat': 17.0}
D = {'lon': 79.02, 'lat': 17.0}
ROAD = {'provider': 'SYNTHETIC TEST ROAD', 'coordinates': [[78.99,17.0],[79.0,17.0],[79.01,17.004],[79.02,17.0],[79.03,17.0]],
        'waypoints': [{'secret': 'other passenger'}], 'pickup_schedule': {'private': 'schedule'},
        'driver_id': 'private-owner', 'live_coordinates': [1,2]}


def test_only_original_interior_road_vertices_and_explicit_estimate_are_returned():
    original = deepcopy(ROAD)
    result = passenger_route_preview(ROAD, P, D)
    assert result == {'provider': ROAD['provider'], 'coordinates': ROAD['coordinates'][1:4], 'preview': True, 'estimated': True}
    assert ROAD == original
    result['coordinates'][0][0] = 0
    assert ROAD == original


def test_dense_clusters_trim_inward_without_creating_endpoint_connectors():
    route = {'provider': 'fixture', 'coordinates': [[78.99,17],[78.99995,17],[79,17],[79.00005,17],
                                                 [79.01,17.004],[79.01995,17],[79.02,17],[79.02005,17],[79.03,17]]}
    result = passenger_route_preview(route, P, D)
    assert result['coordinates'] == route['coordinates'][3:6]


@pytest.mark.parametrize('bad', [None, {}, [], [[79,17]], [[79,17],[True,17]], [[79,17],[float('nan'),17]],
    [[79,17],[float('inf'),17]], [[79,17],[10**1000,17]], [[79,17],[181,17]], [[79,17],[79,91]], [[79,17],['79.02',17]],
    [[79,17],[79.02,17,0]], [[79,17],None]])
def test_malformed_geometry_fails_closed(bad):
    assert passenger_route_preview({'provider':'fixture','coordinates':bad}, P, D) is None


@pytest.mark.parametrize('pickup,dropoff', [({},D),(P,{}),({'lon':True,'lat':17},D),
    ({'lon':79,'lat':17.001},D),(D,P),(P,P)])
def test_invalid_mismatched_reversed_or_overlapping_endpoints_fail_closed(pickup, dropoff):
    assert passenger_route_preview(ROAD, pickup, dropoff) is None


@pytest.mark.parametrize('coordinates', [
    [[79,17],[79.01,17.004],[79,17],[79.02,17]],
    [[79,17],[79.02,17],[79.01,17.004],[79.02,17]],
    [[79,17],[79,17]],
])
def test_repeat_visits_loops_and_degenerate_slices_fail_closed(coordinates):
    assert passenger_route_preview({'provider':'fixture','coordinates':coordinates},P,D) is None


def test_preview_does_not_search_for_far_vertex_or_interpolate_a_sparse_line():
    assert passenger_route_preview({'provider':'fixture','coordinates':[[78.99,17],[79.03,17]]},P,D) is None


def test_match_omits_preview_and_all_upstream_route_metadata_when_geometry_is_ambiguous(tmp_path):
    from test_lifecycle import make_service
    service, _, users, _ = make_service(tmp_path)
    trip = {'id':'trip','driver_name':'driver','route':{'provider':'fixture'}}
    request = {'id':'request','origin':P,'destination':D,'seats':1}
    calculation = {'proposed_route':{**ROAD,'coordinates':[[79,17],[79.01,17],[79,17],[79.02,17]]},
                   'pickup_schedule':{'another-passenger':'private'},'routed_pickup':P,'routed_dropoff':D}
    result = service._new_match(trip, request, calculation)
    assert 'preview_route' not in result
    assert 'coordinates' not in json.dumps(result)
    assert 'proposed_route' not in result and 'pickup_schedule' not in result
    assert 'another-passenger' not in json.dumps(result)


class CountingProvider(FixtureRoadProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def route(self, points):
        self.calls += 1
        route = super().route(points)
        route['private_extra'] = {'driver':'never-return', 'schedule':'never-return'}
        return route


def test_authenticated_search_preview_is_passenger_only_and_adds_no_provider_calls(tmp_path):
    app = create_app({'TESTING':True,'SECRET_KEY':'route-preview-test','DATABASE_PATH':str(tmp_path/'api.sqlite3'),
                      'BETA_PASSWORD':'local-preview-test-only'})
    service = app.extensions['beta_service']
    provider = CountingProvider()
    service.router = provider
    store = app.extensions['beta_store']
    with store.read() as tx:
        driver = tx.get('users','driver')
    departure = future_departure()
    _, trip = publish(service, driver, KONDAPUR, VIJAYAWADA, departure, seats=2)
    client = app.test_client()
    token = client.get('/api/bootstrap').json['csrf_token']
    headers = {'Origin':'http://localhost','X-CSRF-Token':token}
    assert client.post('/api/login', json={'account':'passenger','password':'local-preview-test-only'},headers=headers).status_code == 200
    from datetime import datetime, timedelta
    at = datetime.fromisoformat(departure)
    before = provider.calls
    response = client.post('/api/search',json={'origin':SURYAPET,'destination':NANDIGAMA,'window_start':departure,
                                               'window_end':(at+timedelta(hours=8)).isoformat(),'seats':1},headers=headers)
    assert response.status_code == 200
    assert provider.calls - before == 2  # Existing proposed itinerary + pickup-only estimate; no preview RPC.
    match = response.json['matches'][0]
    preview = match['preview_route']
    assert set(preview) == {'coordinates','provider','preview','estimated'}
    assert preview['coordinates'] == [[SURYAPET['lon'],SURYAPET['lat']],[NANDIGAMA['lon'],NANDIGAMA['lat']]]
    assert [KONDAPUR['lon'],KONDAPUR['lat']] not in preview['coordinates']
    assert [VIJAYAWADA['lon'],VIJAYAWADA['lat']] not in preview['coordinates']
    serialized = json.dumps(match)
    for forbidden in ('proposed_route','pickup_schedule','waypoints','private_extra','never-return'):
        assert forbidden not in serialized
    with store.read() as tx:
        assert tx.get('matches',match['id'])['preview_route'] == preview
    assert client.get('/api/state').json['trips'] == []
    pending = client.post('/api/request',json={'match_id':match['id']},headers=headers)
    assert pending.status_code == 200
    booking_id = pending.json['booking']['id']
    service.dispatch('accept',driver,{'booking_id':booking_id})
    accepted = next(row for row in client.get('/api/state').json['bookings'] if row['id'] == booking_id)
    assert set(accepted['route']) == {'coordinates','provider'}  # Committed API segment is authoritative.
    assert accepted['route']['coordinates'] == preview['coordinates']
    assert accepted['match']['preview_route']['estimated'] is True
    unrelated = app.test_client()
    assert unrelated.post('/api/search',json={}).status_code in (401,403)
