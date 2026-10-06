"""Integration checks for the anonymous, same-origin trusted-trip viewer."""

from app import create_app

def make_app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "viewer-test-secret",
        "DATABASE_PATH": str(tmp_path / "viewer.sqlite3"),
        "BETA_PASSWORD": "viewer-test-only",
    })


def test_share_page_uses_private_static_module_and_security_headers(tmp_path):
    app = make_app(tmp_path)
    response = app.test_client().get("/trip-share")
    assert response.status_code == 200
    assert b"/static/trip-share.js" in response.data
    assert b"name=\"referrer\" content=\"no-referrer\"" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]

