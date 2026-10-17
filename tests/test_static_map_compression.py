import gzip

import pytest

from app import create_app


URL = "/static/maps/india-soi-boundaries.geojson"


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-signing-key",
        "DATABASE_PATH": str(tmp_path / "beta.sqlite3"),
        "BETA_PASSWORD": "correct-horse-battery",
    })


@pytest.fixture
def client(app):
    return app.test_client()


def map_assets(app, tmp_path, *, compressed=True):
    static = tmp_path / "static"
    maps = static / "maps"
    maps.mkdir(parents=True)
    raw = b'{"type":"FeatureCollection","features":[]}\n'
    raw_path = maps / "india-soi-boundaries.geojson"
    raw_path.write_bytes(raw)
    if compressed:
        (maps / "india-soi-boundaries.geojson.gz").write_bytes(gzip.compress(raw))
    app.static_folder = str(static)
    return raw


def test_boundary_route_negotiates_gzip_and_keeps_conditional_headers(app, client, tmp_path):
    raw = map_assets(app, tmp_path)

    compressed = client.get(URL, headers={"Accept-Encoding": "gzip"})
    assert compressed.status_code == 200
    assert compressed.headers["Content-Type"].startswith("application/geo+json")
    assert compressed.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in compressed.headers["Vary"]
    assert compressed.headers["ETag"]
    assert gzip.decompress(compressed.data) == raw

    not_accepted = client.get(URL, headers={"Accept-Encoding": "gzip;q=0, identity"})
    assert not_accepted.status_code == 200
    assert "Content-Encoding" not in not_accepted.headers
    assert not_accepted.data == raw
    assert not_accepted.headers["ETag"]
    assert not_accepted.headers["ETag"] != compressed.headers["ETag"]

    conditional = client.get(
        URL,
        headers={"Accept-Encoding": "gzip", "If-None-Match": compressed.headers["ETag"]},
    )
    assert conditional.status_code == 304
    assert "Accept-Encoding" in conditional.headers["Vary"]
    assert conditional.headers["ETag"] == compressed.headers["ETag"]

    head = client.head(URL, headers={"Accept-Encoding": "gzip"})
    assert head.status_code == 200
    assert head.data == b""
    assert head.headers["Content-Length"] == str(len(compressed.data))
    assert head.headers["ETag"] == compressed.headers["ETag"]


def test_boundary_route_falls_back_to_raw_when_sidecar_is_missing(app, client, tmp_path):
    raw = map_assets(app, tmp_path, compressed=False)

    response = client.get(URL, headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/geo+json")
    assert "Content-Encoding" not in response.headers
    assert "Accept-Encoding" in response.headers["Vary"]
    assert response.data == raw


def test_boundary_route_keeps_global_security_headers(client, app, tmp_path):
    map_assets(app, tmp_path)

    response = client.get(URL, headers={"Accept-Encoding": "gzip"})

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    assert "Accept-Encoding" in response.headers["Vary"]
