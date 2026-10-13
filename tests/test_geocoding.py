import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.geocoding import GeocodingError, NominatimGeocoder, clear_geocode_cache_for_tests
from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "geocoder-test-key", "DATABASE_PATH": str(tmp_path / "beta.sqlite3"), "BETA_PASSWORD": "correct-horse-battery"})


@pytest.fixture
def client(app):
    return app.test_client()


def login(client):
    token = client.get("/api/bootstrap").json["csrf_token"]
    return client.post("/api/login", json={"account": "driver", "password": "correct-horse-battery"},
                       headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": token})


@pytest.fixture(autouse=True)
def clear_cache():
    clear_geocode_cache_for_tests()


def test_nominatim_search_uses_manual_query_headers_and_caches_for_24h():
    now = [1000.0]
    calls = []

    def fetch(url, headers, timeout):
        calls.append((url, headers, timeout))
        return json.dumps([{"name": "Suryapet", "lat": "17.14", "lon": "79.62"}]).encode()

    geocoder = NominatimGeocoder("https://nominatim.example/search", fetcher=fetch, clock=lambda: now[0], sleeper=lambda _: None)
    first = geocoder.search("Suryapet", "te")
    second = geocoder.search("  SURYAPET  ", "te")
    assert first == second
    assert {key: first[0][key] for key in ("label", "lat", "lon")} == {"label": "Suryapet", "lat": 17.14, "lon": 79.62}
    assert len(calls) == 1
    query = parse_qs(urlparse(calls[0][0]).query)
    assert query == {"q": ["suryapet"], "format": ["jsonv2"], "countrycodes": ["in"], "limit": ["6"], "addressdetails": ["1"]}
    assert calls[0][1] == {"User-Agent": "RouteShareLocalPrototype/0.1", "Accept-Language": "te"}
    assert calls[0][2] == 8

    now[0] += 24 * 60 * 60 + 1
    geocoder.search("Suryapet", "te")
    assert len(calls) == 2


def test_cache_is_bounded_to_256_entries():
    calls = []
    geocoder = NominatimGeocoder(
        "https://nominatim.example/search",
        fetcher=lambda url, _headers, _timeout: (calls.append(url) or b"[]"),
        clock=lambda: 10_000.0,
        sleeper=lambda _: None,
    )
    for index in range(257):
        geocoder.search(f"Place {index:03d}", "en")
    assert len(calls) == 257
    geocoder.search("Place 000", "en")
    assert len(calls) == 258  # the least-recent entry was evicted


def test_upstream_failures_are_reported_as_actionable_errors():
    def fail(_url, _headers, _timeout):
        raise TimeoutError("private transport detail")

    geocoder = NominatimGeocoder("https://nominatim.example/search", fetcher=fail, clock=lambda: 1, sleeper=lambda _: None)
    with pytest.raises(GeocodingError, match="temporarily unavailable"):
        geocoder.search("Hyderabad", "en")


def test_distinct_upstream_searches_are_process_wide_rate_limited():
    now = [500.0]
    starts, waits = [], []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    def fetch(_url, _headers, _timeout):
        starts.append(now[0])
        return b"[]"

    first = NominatimGeocoder("https://nominatim.example/search", fetcher=fetch, clock=lambda: now[0], sleeper=sleep)
    second = NominatimGeocoder("https://nominatim.example/search", fetcher=fetch, clock=lambda: now[0], sleeper=sleep)
    first.search("Hyderabad", "en")
    second.search("Warangal", "en")
    assert starts == [500.0, 501.0]
    assert waits == [1.0]


def test_places_endpoint_requires_auth_validates_manual_query_and_returns_six_places(client, app, monkeypatch):
    assert client.get("/api/places?q=Hyderabad&lang=en").status_code == 401
    assert login(client).status_code == 200
    for query in ("ab", "x" * 161):
        response = client.get(f"/api/places?q={query}&lang=en")
        assert response.status_code == 400
        assert response.json["error"]
    coordinate_query = client.get("/api/places?q=17.385%2C78.4867&lang=en")
    assert coordinate_query.status_code == 400
    assert coordinate_query.json["error"] == "Choose the point on the map."
    assert client.get("/api/places?q=Hyderabad&lang=fr").status_code == 400

    class StubGeocoder:
        def search(self, query, language):
            assert (query, language) == ("Hyderabad", "te")
            return [{"label": f"Place {i}", "lat": 17.0, "lon": 78.0} for i in range(6)]

    monkeypatch.setitem(app.extensions, "geocoder", StubGeocoder())
    response = client.get("/api/places?q=Hyderabad&lang=te")
    assert response.status_code == 200
    assert len(response.json["places"]) == 6


def test_places_endpoint_returns_json_503_without_upstream_details(client, app, monkeypatch):
    assert login(client).status_code == 200

    class BrokenGeocoder:
        def search(self, _query, _language):
            raise GeocodingError("Place search is temporarily unavailable. Try again shortly.")

    monkeypatch.setitem(app.extensions, "geocoder", BrokenGeocoder())
    response = client.get("/api/places?q=Hyderabad&lang=en")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json["error"]
    assert "private" not in str(response.json)


def provider_place(**changes):
    return {"osm_type": "relation", "osm_id": 1234, "name": "Hyderabad",
            "display_name": "Hyderabad, Telangana, India", "addresstype": "city",
            "lat": "17.36", "lon": "78.47", "address": {"country_code": "in"},
            "boundingbox": ["17.1", "17.6", "78.2", "78.8"], **changes}


def test_enriched_results_keep_distinct_objects_and_defensively_copy_bbox():
    rows = [provider_place(), provider_place(osm_id=5678, addresstype="county"),
            provider_place(), provider_place(lat="nan"), provider_place(lon="inf"),
            provider_place(address={"country_code": "gb"})]
    geocoder = NominatimGeocoder(fetcher=lambda *_: json.dumps(rows))
    result = geocoder.search("Hyderabad", "en")
    assert len(result) == 2
    assert result[0] == {"id": "osm:relation:1234", "label": "Hyderabad", "name": "Hyderabad",
                         "address": "Hyderabad, Telangana, India", "kind": "city",
                         "lat": 17.36, "lon": 78.47, "bbox": [17.1, 17.6, 78.2, 78.8]}
    assert result[1]["id"] != result[0]["id"]
    result[0]["bbox"][0] = -90
    assert geocoder.search("Hyderabad", "en")[0]["bbox"][0] == 17.1


@pytest.mark.parametrize("bbox", [[18, 17, 78, 79], [17, 18, 79, 78], [17, 18, 78, float("nan")], [1], None])
def test_invalid_bbox_is_ignored_without_losing_valid_place(bbox):
    geocoder = NominatimGeocoder(fetcher=lambda *_: json.dumps([provider_place(boundingbox=bbox)]))
    assert geocoder.search("Hyderabad", "en")[0]["bbox"] is None


def test_only_exact_validated_telugu_city_alias_is_rewritten():
    requests = []
    geocoder = NominatimGeocoder(fetcher=lambda url, headers, _: requests.append((parse_qs(urlparse(url).query), headers)) or "[]",
                                clock=lambda: 100, sleeper=lambda _: None)
    geocoder.search("  హైదరాబాద్  ", "te")
    geocoder.search("హైదరాబాద్ పబ్లిక్ స్కూల్", "te")
    geocoder.search("విజయవాడ", "te")
    assert [item[0]["q"][0] for item in requests] == ["Hyderabad", "హైదరాబాద్ పబ్లిక్ స్కూల్", "విజయవాడ"]
    assert all(item[1]["Accept-Language"] == "te" for item in requests)
    assert all(item[0]["countrycodes"] == ["in"] for item in requests)


def test_reverse_contract_cached_coordinates_and_global_search_rate():
    now, starts, urls = [1000.0], [], []
    def fetch(url, headers, timeout):
        starts.append(now[0]); urls.append(url)
        return json.dumps(provider_place() if "/reverse?" in url else [provider_place()])
    geocoder = NominatimGeocoder("https://nominatim.example/api/search", fetcher=fetch,
                                clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
    geocoder.search("Hyderabad", "en")
    point = geocoder.reverse(17.360001, 78.470001, "en")
    assert geocoder.reverse(17.36000101, 78.47000101, "en") == point
    assert starts == [1000.0, 1001.0]
    assert urlparse(urls[1]).path == "/api/reverse"
    assert parse_qs(urlparse(urls[1]).query) == {"lat": ["17.360001"], "lon": ["78.470001"], "format": ["jsonv2"], "addressdetails": ["1"], "zoom": ["18"]}
    assert point["lat"] == 17.36  # nearby object, not a claimed pin snap


@pytest.mark.parametrize("payload, expected", [({"error": "Unable to geocode"}, None), (provider_place(address={"country_code": "gb"}), None)])
def test_reverse_no_coverage_or_outside_india_returns_no_place(payload, expected):
    geocoder = NominatimGeocoder(fetcher=lambda *_: json.dumps(payload))
    assert geocoder.reverse(17, 78, "en") == expected


@pytest.mark.parametrize("payload", [[], {"error": "private unexpected error"}, provider_place(lat="nan"), provider_place(address=None)])
def test_malformed_reverse_is_actionable_and_sanitized(payload):
    geocoder = NominatimGeocoder(fetcher=lambda *_: json.dumps(payload))
    with pytest.raises(GeocodingError, match="temporarily unavailable"):
        geocoder.reverse(17, 78, "en")


def test_reverse_endpoint_auth_input_validation_and_never_changes_provider_point(client, app, monkeypatch):
    assert client.get("/api/places/reverse?lat=17&lon=78").status_code == 401
    assert login(client).status_code == 200
    calls = []
    class StubGeocoder:
        def reverse(self, lat, lon, language):
            calls.append((lat, lon, language))
            return {"label": "Nearby road", "lat": 17.01, "lon": 78.01}
    monkeypatch.setitem(app.extensions, "geocoder", StubGeocoder())
    for args in ({}, {"lat": "nan", "lon": "78"}, {"lat": "17", "lon": "inf"},
                 {"lat": "91", "lon": "78"}, {"lat": "17", "lon": "-181"},
                 {"lat": "", "lon": "78"}, {"lat": "17", "lon": "78", "lang": "fr"}):
        assert client.get("/api/places/reverse", query_string=args).status_code == 400
    assert calls == []
    response = client.get("/api/places/reverse?lat=17&lon=78&lang=te")
    assert response.status_code == 200
    assert response.json == {"place": {"label": "Nearby road", "lat": 17.01, "lon": 78.01}}
    assert calls == [(17.0, 78.0, "te")]


def test_cached_hit_does_not_wait_for_unrelated_network_and_matching_miss_coalesces():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    started, release = Event(), Event()
    calls = []
    def fetch(url, *_):
        term = parse_qs(urlparse(url).query)["q"][0]
        calls.append(term)
        if term == "slow":
            started.set()
            assert release.wait(3)
        return json.dumps([provider_place(name=term)])
    geocoder = NominatimGeocoder(fetcher=fetch, clock=lambda: 100, sleeper=lambda _: None)
    geocoder.search("cached", "en")
    with ThreadPoolExecutor(max_workers=3) as pool:
        slow = pool.submit(geocoder.search, "slow", "en")
        assert started.wait(1)
        duplicate = pool.submit(geocoder.search, "SLOW", "en")
        try:
            hit = pool.submit(geocoder.search, "cached", "en")
            assert hit.result(timeout=.5)[0]["name"] == "cached"
        finally:
            release.set()
        assert slow.result(timeout=2) == duplicate.result(timeout=2)
    assert calls == ["cached", "slow"]


def test_distinct_inflight_search_and_reverse_keep_separate_results_and_one_schedule():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    started, release = Event(), Event()
    now, starts = [500.0], []
    def fetch(url, *_):
        starts.append(now[0])
        if "/search?" in url:
            started.set()
            assert release.wait(3)
            return json.dumps([provider_place(name="City")])
        return json.dumps(provider_place(name="Road"))
    first = NominatimGeocoder(fetcher=fetch, clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
    second = NominatimGeocoder(fetcher=fetch, clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
    with ThreadPoolExecutor(max_workers=2) as pool:
        search = pool.submit(first.search, "Hyderabad", "en")
        assert started.wait(1)
        reverse = pool.submit(second.reverse, 17, 78, "te")
        release.set()
        assert search.result(timeout=2)[0]["name"] == "City"
        assert reverse.result(timeout=2)["name"] == "Road"
    assert starts == [500.0, 501.0]


def test_queue_is_bounded_and_errors_release_schedule(monkeypatch):
    import app.geocoding as module
    monkeypatch.setattr(module, "_QUEUE_TIMEOUT", .01)
    geocoder = NominatimGeocoder(fetcher=lambda *_: b"[]")
    with module._upstream_lock:
        with pytest.raises(GeocodingError, match="temporarily unavailable"):
            geocoder.search("Hyderabad", "en")
    assert geocoder.search("Hyderabad", "en") == []


def test_reverse_mobile_bearer_and_logout_revocation(client, app, monkeypatch):
    token = client.post('/api/mobile/login', json={"account": "passenger", "password": "correct-horse-battery"}).json['token']
    class StubGeocoder:
        def reverse(self, *_):
            return None
    monkeypatch.setitem(app.extensions, 'geocoder', StubGeocoder())
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get('/api/places/reverse?lat=17&lon=78', headers=headers)
    assert response.status_code == 200 and response.json == {"place": None}
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'Access-Control-Allow-Origin' not in response.headers
    assert client.post('/api/mobile/logout', json={}, headers=headers).status_code == 200
    assert client.get('/api/places/reverse?lat=17&lon=78', headers=headers).status_code == 401


def test_reverse_failure_is_not_cached_and_releases_schedule():
    calls = []
    def fetch(*_):
        calls.append(True)
        if len(calls) == 1:
            raise TimeoutError('private details')
        return json.dumps(provider_place())
    geocoder = NominatimGeocoder(fetcher=fetch, clock=lambda: 100, sleeper=lambda _: None)
    with pytest.raises(GeocodingError, match='temporarily unavailable'):
        geocoder.reverse(17, 78, 'te')
    assert geocoder.reverse(17, 78, 'te')['kind'] == 'city'
    assert len(calls) == 2


def test_long_provider_name_keeps_context_but_label_fits_domain_limit():
    name = "Public meeting entrance " * 10
    address = name + ", Hyderabad, Telangana, India"
    geocoder = NominatimGeocoder(fetcher=lambda *_: json.dumps([provider_place(name=name, display_name=address)]))
    point = geocoder.search("Public meeting entrance", "en")[0]
    assert len(point["label"]) == 120
    assert point["name"] == name.strip()[:240]
    assert point["address"] == address
