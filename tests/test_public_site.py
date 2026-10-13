"""Public pages use actual capabilities, escape configuration and require no session."""
import pytest
from app import create_app
from app.public_site import COPY, public_site_context
from test_phone_http import SMSFixture


@pytest.fixture
def public_app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE_PATH': str(tmp_path / 'public.sqlite'),
                       'SECRET_KEY': 'public-page-fixture-only', 'VOICE_ENABLED': False,
                       'PHONE_AUTH_ENABLED': False, 'DIRECT_UPI_ENABLED': False,
                       'PUBLIC_OPERATOR_NAME': '', 'PUBLIC_SUPPORT_EMAIL': '',
                       'APP_DISPLAY_NAME': 'SeatPal'})


@pytest.mark.parametrize('path', ['/welcome', '/faq'])
@pytest.mark.parametrize('lang', ['en', 'te'])
def test_anonymous_complete_pages_no_session_and_localized_links(public_app, path, lang):
    client = public_app.test_client()
    response = client.get(path + '?lang=' + lang)
    assert response.status_code == 200
    assert 'Set-Cookie' not in response.headers
    assert client.get_cookie('session') is None
    html = response.get_data(as_text=True)
    assert '<html lang="' + lang + '">' in html
    assert 'href="/welcome?lang=' + lang + '"' in html
    assert 'href="/faq?lang=' + lang + '"' in html
    assert 'href="/?lang=' + lang + '#/login"' in html
    assert 'href="/terms?lang=' + lang + '"' in html
    assert 'href="/privacy?lang=' + lang + '"' in html
    assert 'mailto:' not in html
    if path == '/faq':
        assert html.count('<details ') == sum(len(g['items']) for g in COPY[lang]['faq_groups'])
        assert all(item['question'] in html for group in COPY[lang]['faq_groups'] for item in group['items'])
        assert 'data-faq-search hidden' in html
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_disabled_copy_and_service_not_merely_requested_config(public_app):
    public_app.config['PHONE_AUTH_ENABLED'] = True  # Runtime service remains unconfigured.
    client = public_app.test_client()
    for path in ['/welcome', '/faq']:
        html = client.get(path).get_data(as_text=True)
        assert 'Public phone sign-up is not available' in html
        assert 'Direct UPI payments are not available' in html
        assert 'Phone sign-up is enabled.' not in html
        assert 'Direct UPI is available after' not in html
    spa = client.get('/')
    assert spa.status_code == 200 and spa.data == client.get('/static/index.html').data


def test_enabled_service_copy_and_valid_support(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE_PATH': str(tmp_path / 'enabled.sqlite'),
                      'SECRET_KEY': 'public-page-fixture-only', 'VOICE_ENABLED': False,
                      'PHONE_AUTH_ENABLED': True, 'PHONE_AUTH_PROVIDER': SMSFixture(),
                      'PHONE_AUTH_HMAC_KEY': 'h' * 48, 'PHONE_AUTH_DAILY_LIMIT': 100,
                      'DIRECT_UPI_ENABLED': True, 'PUBLIC_OPERATOR_NAME': 'Test operator',
                      'PUBLIC_SUPPORT_EMAIL': 'support@example.test'})
    assert app.extensions['phone_auth'].enabled and app.extensions['payment_service'].enabled
    for path in ['/welcome', '/faq']:
        response = app.test_client().get(path)
        html = response.get_data(as_text=True)
        assert 'Phone sign-up is enabled.' in html
        assert 'Direct UPI is available after' in html
        assert 'mailto:support@example.test' in html
        assert 'Set-Cookie' not in response.headers
    faq = app.test_client().get('/faq').get_data(as_text=True)
    assert 'does not verify bank settlement' in faq
    assert 'not government or police clearance' in faq


@pytest.mark.parametrize('lang,expected', [('TE', 'te'), ('EN', 'en'), ('hi', 'en'), ('', 'en'),
                                          ('<script>alert(1)</script>', 'en'), ('t' * 1000, 'en')])
def test_language_is_bounded_enum_and_app_name_is_escaped(public_app, lang, expected):
    public_app.config['APP_DISPLAY_NAME'] = '<script>alert("brand")</script>'
    response = public_app.test_client().get('/faq', query_string={'lang': lang})
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and '<html lang="' + expected + '">' in html
    assert '<script>alert(' not in html
    assert '&lt;script&gt;' in html
    assert 'href="/welcome?lang=' + expected + '"' in html


def test_context_isolated_and_malformed_support_never_linked():
    args = dict(page='faq', language='te', app_name='SeatPal', registration_enabled=False,
                payments_enabled=False, support_email='x@example.test?subject=unsafe', operator_configured=True)
    result = public_site_context(**args)
    assert result['support_email'] == ''
    result['copy']['faq_groups'][0]['items'][0]['answer'] = 'changed'
    assert public_site_context(**args)['copy']['faq_groups'][0]['items'][0]['answer'] != 'changed'
    assert '{count}' in result['copy']['faq_result_count']


def test_policy_public_links_preserve_normalized_language(public_app):
    for path in ['/terms', '/privacy']:
        response = public_app.test_client().get(path + '?lang=TE')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'href="/welcome?lang=te"' in html
        assert 'href="/faq?lang=te"' in html
        assert 'Set-Cookie' not in response.headers


def test_policy_pages_use_respective_current_phone_consent_versions(public_app):
    service = public_app.extensions["phone_auth"]
    client = public_app.test_client()
    caps = client.get("/api/phone/capabilities").json
    assert caps["terms_version"] == caps["privacy_version"] == "2026-10-11"
    for field, path in [("terms_version", "/terms"), ("privacy_version", "/privacy")]:
        assert "Version " + caps[field] in client.get(path).text
    service.terms_version = "terms-next"
    service.privacy_version = "privacy-next"
    caps = client.get("/api/phone/capabilities").json
    for field, other, path in [("terms_version", "privacy_version", "/terms"),
                                ("privacy_version", "terms_version", "/privacy")]:
        response = client.get(path)
        assert "Version " + caps[field] in response.text
        assert "Version " + caps[other] not in response.text
        assert "Set-Cookie" not in response.headers


def test_policies_disclose_identity_review_and_actual_evidence_limits(public_app):
    client = public_app.test_client()
    privacy = client.get("/privacy").text
    terms = client.get("/terms").text
    assert "driving licence, passport or voter ID" in privacy and "selfie" in privacy
    assert "watermarked page previews" in privacy and "cannot prevent screenshots" in privacy
    assert "30 days after upload" in privacy and "when the identity service is accessed" in privacy
    assert "withdraw your identity application" in privacy
    assert "uploaded identity and driver evidence" in privacy
    assert "Requesting a seat with a real member account requires verified phone sign-in" in terms
    assert "current identity approval" in terms and "not government authentication" in terms
