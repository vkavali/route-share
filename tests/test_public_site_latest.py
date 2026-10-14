"""Reversible approved landing integration stays anonymous and uses live services."""
import re
import pytest
from app import create_app
from app.public_site_latest import public_site_latest_context
from test_public_site import public_app
from test_phone_http import SMSFixture


@pytest.mark.parametrize('lang', ['en', 'te'])
@pytest.mark.parametrize('path', ['/welcome', '/welcome/latest', '/welcome/previous'])
def test_variants_language_links_assets_and_no_session(public_app, path, lang):
    client = public_app.test_client()
    response = client.get(path, query_string={'lang': lang})
    assert response.status_code == 200 and 'Set-Cookie' not in response.headers
    assert client.get_cookie('session') is None
    html = response.get_data(as_text=True)
    assert f'<html lang="{lang}">' in html
    assert f'href="{path}?lang=en"' in html
    assert f'href="{path}?lang=te"' in html
    assert f'href="/?lang={lang}#/login"' in html
    assert f'href="/faq?lang={lang}"' in html
    assert f'href="/terms?lang={lang}"' in html and f'href="/privacy?lang={lang}"' in html
    if path.endswith('/previous'):
        assert 'data-five-stage-journey' not in html
        assert f'href="/welcome/latest?lang={lang}"' in html
        assert '/static/landing-layered.css' in html and '/static/landing-latest.css' not in html
    else:
        assert f'href="/welcome/previous?lang={lang}"' in html
        assert 'data-seatpal-brand' in html and 'data-ride-story' in html
        assert '/static/seatpal-landing-brand.css' in html
        assert '/static/seatpal-landing-brand.js' in html
        assert html.count('data-journey-stage=') == 5
        for key in ('plan', 'offer', 'driver', 'request', 'chat', 'live', 'costs', 'reviews', 'account'):
            assert f'id="feature-{key}"' in html
        assert '/static/assets/seatpal/seatpal-mark.svg' in html
        assert '/static/landing-latest.css' in html and '/static/journey-scenes-latest.js' in html
        assert 'seatpal-seat.svg' not in html
    for asset in set(re.findall(r'(?:src|href)="(/static/[^"?#]+)', html)):
        fetched = client.get(asset)
        assert fetched.status_code == 200, asset
        assert 'Set-Cookie' not in fetched.headers


def test_latest_uses_runtime_capabilities_and_escapes_brand(public_app, tmp_path):
    public_app.config.update(PHONE_AUTH_ENABLED=True, DIRECT_UPI_ENABLED=True,
                             APP_DISPLAY_NAME='<script>not-trusted</script>')
    for path in ('/welcome', '/welcome/latest', '/welcome/previous'):
        html = public_app.test_client().get(path).get_data(as_text=True)
        assert 'Public phone sign-up is not available' in html
        assert 'Direct UPI payments are not available' in html
        assert '<script>not-trusted</script>' not in html and '&lt;script&gt;not-trusted&lt;/script&gt;' in html
    enabled = create_app({'TESTING': True, 'DATABASE_PATH': str(tmp_path / 'enabled.sqlite'),
                         'SECRET_KEY': 'public-latest-fixture', 'VOICE_ENABLED': False,
                         'PHONE_AUTH_ENABLED': True, 'PHONE_AUTH_PROVIDER': SMSFixture(),
                         'PHONE_AUTH_HMAC_KEY': 'h' * 48, 'PHONE_AUTH_DAILY_LIMIT': 100,
                         'DIRECT_UPI_ENABLED': True, 'PUBLIC_OPERATOR_NAME': 'Fixture operator',
                         'PUBLIC_SUPPORT_EMAIL': 'support@example.test'})
    assert enabled.extensions['phone_auth'].enabled and enabled.extensions['payment_service'].enabled
    for path in ('/welcome', '/welcome/latest', '/welcome/previous'):
        response = enabled.test_client().get(path)
        html = response.get_data(as_text=True)
        assert 'Phone sign-up is enabled.' in html and 'Direct UPI is available after' in html
        assert 'mailto:support@example.test' in html
        assert 'Set-Cookie' not in response.headers


def test_latest_context_isolation_and_shared_faq(public_app):
    args = dict(page='landing', language='te', app_name='SeatPal', registration_enabled=False,
                payments_enabled=False, support_email='bad@example.test?unsafe', operator_configured=True)
    context = public_site_latest_context(**args)
    assert context['support_email'] == ''
    context['copy']['five_stage']['stages'][0]['name'] = 'changed'
    assert public_site_latest_context(**args)['copy']['five_stage']['stages'][0]['name'] != 'changed'
    faq = public_app.test_client().get('/faq?lang=te').get_data(as_text=True)
    assert '/static/public-site.js' in faq and 'journey-scenes-latest.js' not in faq
    assert 'data-five-stage-journey' not in faq
