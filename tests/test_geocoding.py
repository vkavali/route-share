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
    assert first == second == [{"label": "Suryapet", "lat": 17.14, "lon": 79.62}]
    assert len(calls) == 1
    query = parse_qs(urlparse(calls[0][0]).query)
    assert query == {"q": ["Suryapet"], "format": ["jsonv2"], "countrycodes": ["in"], "limit": ["6"]}
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
