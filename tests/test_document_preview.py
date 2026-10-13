"""Actual bounded image/PDF rendering and transaction-bound staff inspection."""
from tests.review_helpers import complete_checklist
import base64
from datetime import datetime, timezone
from io import BytesIO
import importlib
import json
import subprocess

import pytest
from PIL import Image, PngImagePlugin
from cryptography.fernet import Fernet
from app import document_preview as preview
from app.driver_verification import DriverVerificationError, DriverVerificationService
from app.identity_verification import IdentityVerificationError, IdentityVerificationService
from app.store import Store

AT = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def image_bytes(size=(700, 900)):
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Secret', 'PRIVATE-METADATA-NOT-PIXELS')
    Image.new('RGB', size, 'white').save(buffer, format='PNG', pnginfo=metadata)
    return buffer.getvalue()


def pdf_bytes(pages=2):
    buffer = BytesIO()
    Image.new('RGB', (500, 700), 'white').save(buffer, format='PDF', save_all=True,
        append_images=[Image.new('RGB', (500, 700), 'blue') for _ in range(pages - 1)],
        title='PRIVATE-PDF-TITLE')
    return buffer.getvalue()


def test_flattened_metadata_free_jpeg_and_repeated_watermark():
    result = preview.render_preview(image_bytes(), 'image/png', 1, 'reviewer-123', AT)
    assert set(result) == {'image_data_url', 'page', 'page_count', 'watermark'}
    assert result['page_count'] == 1 and 'reviewer-123' in result['watermark'] and 'UTC' in result['watermark']
    data = base64.b64decode(result['image_data_url'].split(',', 1)[1])
    assert b'PRIVATE-METADATA' not in data
    with Image.open(BytesIO(data)) as rendered:
        assert rendered.format == 'JPEG' and max(rendered.size) <= preview.MAX_EDGE
        assert not rendered.getexif() and 'comment' not in rendered.info
        # Text is baked into multiple separated image regions, not a CSS overlay.
        for box in ((0, 0, 640, 100), (0, 340, 640, 440), (0, 680, 640, 780)):
            assert rendered.crop(box).getextrema()[0][0] < 220


def test_real_pdf_pages_have_distinct_flattened_pixels():
    data = pdf_bytes()
    first = preview.render_preview(data, 'application/pdf', 1, 'staff', AT)
    second = preview.render_preview(data, 'application/pdf', 2, 'staff', AT)
    assert first['page_count'] == second['page_count'] == 2
    assert first['image_data_url'] != second['image_data_url']
    assert b'%PDF' not in base64.b64decode(first['image_data_url'].split(',', 1)[1])
    with pytest.raises(preview.PreviewError) as caught:
        preview.render_preview(data, 'application/pdf', 3, 'staff', AT)
    assert caught.value.code == 'document_preview_page_invalid'


@pytest.mark.parametrize('page', [0, -1, True, 13, '01', '1.0', '1e0', '../1', '', None])
def test_strict_pages(page):
    with pytest.raises(preview.PreviewError): preview.page_number(page)


@pytest.mark.parametrize('raw,media', [(b'%PDF-1.7\nbroken', 'application/pdf'), (b'bad', 'image/png'),
    (b'x' * (preview.MAX_INPUT + 1), 'image/png'), (b'<svg><script>x</script></svg>', 'image/svg+xml')])
def test_invalid_documents_never_fall_back_to_originals(raw, media):
    with pytest.raises(preview.PreviewError): preview.render_preview(raw, media, 1, 'staff', AT)


def test_page_and_pixel_bombs_fail_closed():
    for data, media in ((pdf_bytes(13), 'application/pdf'), (image_bytes((4100, 4100)), 'image/png')):
        with pytest.raises(preview.PreviewError): preview.render_preview(data, media, 1, 'staff', AT)


def test_busy_and_timeout_are_bounded_and_release_slot(monkeypatch):
    with preview._SLOT:
        with pytest.raises(preview.PreviewError) as caught:
            preview.render_preview(image_bytes(), 'image/png', 1, 'staff', AT)
        assert caught.value.code == 'document_preview_busy'
    class Slow:
        killed = False
        def communicate(self, *args, **kwargs):
            if not self.killed: raise subprocess.TimeoutExpired('synthetic', 10)
        def kill(self): self.killed = True
    child = Slow()
    monkeypatch.setattr(preview.subprocess, 'Popen', lambda *a, **k: child)
    with pytest.raises(preview.PreviewError) as caught:
        preview.render_preview(image_bytes(), 'image/png', 1, 'staff', AT)
    assert caught.value.code == 'document_preview_timeout' and child.killed
    assert preview._SLOT.acquire(blocking=False)
    preview._SLOT.release()


@pytest.fixture(params=['identity', 'driver'])
def case(tmp_path, request):
    kind = request.param
    store = Store(tmp_path / (kind + '.sqlite'))
    owner = {'id': 'owner', 'role': 'member', 'development': False,
             'auth_method': 'phone', 'auth_phone': '+919876543210', 'phone_verified': True}
    staff = {'id': 'staff', 'role': 'staff', 'staff_capabilities': ['verify.review']}
    outsider = {'id': 'outsider', 'role': 'member'}
    with store.transaction() as tx:
        for user in (owner, staff, outsider): tx.put('users', user['id'], user)
    service = (IdentityVerificationService(store, encryption_key=Fernet.generate_key(), clock=lambda: AT)
               if kind == 'identity' else DriverVerificationService(store, encryption_key=Fernet.generate_key(), clock=lambda: AT))
    payload = {'legal_name': 'Synthetic Applicant', 'adult_attested': True, 'document_consent': True, 'expected_version': 0}
    payload.update({'document_type': 'passport'} if kind == 'identity' else
                   {'vehicle': {'model': 'Synthetic', 'plate': 'TS01AB1234'}, 'planned_trip_attested': True, 'applicant_note': ''})
    app = service.save_application(owner, payload)['application']
    kinds = ('identity_document', 'selfie') if kind == 'identity' else ('dl', 'rc', 'insurance', 'selfie')
    for index, doc_kind in enumerate(kinds):
        app = service.upload_document(owner, kind=doc_kind, expires_on=None if doc_kind == 'selfie' else '2027-01-01',
            filename='secret-source.pdf' if index == 0 else 'secret-source.png',
            content=pdf_bytes() if index == 0 else image_bytes(), expected_version=app['version'])['application']
    app = service.submit_application(owner, {'expected_version': app['version']})['application']
    return kind, store, service, owner, staff, outsider, app


def test_acl_all_pages_required_and_originals_remain_owner_only(case):
    kind, store, service, owner, staff, outsider, app = case
    documents = app['documents']
    for doc in documents:
        assert service.get_document(owner, doc['id'])['content']
        for user in (staff, outsider):
            with pytest.raises((DriverVerificationError, IdentityVerificationError)) as caught: service.get_document(user, doc['id'])
            assert caught.value.status == 404
        with pytest.raises((DriverVerificationError, IdentityVerificationError)) as caught: service.get_document_preview(owner, doc['id'])
        assert caught.value.status == 403
    checks = {'document_readable': True, 'name_matches': True, 'photo_matches': True, 'adult_confirmed': True} if kind == 'identity' else dict.fromkeys(('dl', 'rc', 'insurance', 'identity_match'), True)
    decision = dict(application_id=app['id'], expected_version=app['version'], decision='approved',
                    reason='Manually inspected synthetic evidence.', checks=checks, idempotency_key='preview-approval-test')
    for doc in documents: service.get_document_preview(staff, doc['id'], 1)
    with pytest.raises((DriverVerificationError, IdentityVerificationError)) as caught: service.review_application(staff, decision)
    assert caught.value.code.endswith('documents_unread')
    pdf = next(d for d in documents if d['kind'] in ('dl', 'identity_document'))
    service.get_document_preview(staff, pdf['id'], 2)
    complete_checklist(service, staff, app)
    assert service.review_application(staff, decision)['application']['status'] == 'approved'
    with store.read() as tx:
        rows = tx.list(kind + '_document_access')
        assert len(rows) == len(documents) + 1
        assert all(r['mode'] == 'watermarked_preview' and r['application_version'] == app['version'] for r in rows)
        assert 'image_data_url' not in json.dumps(rows)


@pytest.mark.parametrize('change', ['grant', 'epoch', 'version', 'withdraw', 'blob'])
def test_no_pixels_or_receipt_after_mid_render_revocation_or_change(case, monkeypatch, change):
    kind, store, service, owner, staff, outsider, app = case
    module = importlib.import_module('app.' + kind + '_verification')
    real_render = module.render_preview
    def mutate(*args):
        rendered = real_render(*args)
        with store.transaction() as tx:
            if change in ('grant', 'epoch'):
                user = tx.get('users', staff['id'])
                user.update({'staff_capabilities': []} if change == 'grant' else {'auth_epoch': 99})
                tx.put('users', staff['id'], user)
            elif change == 'blob':
                tx._connection.execute('UPDATE ' + kind + '_document_blobs SET content=? WHERE id=?', (b'changed', app['documents'][0]['id']))
            else:
                current = tx.get(kind + '_applications', app['id'])
                current.update({'version': current['version'] + 1} if change == 'version' else {'document_consent': False})
                tx.put(kind + '_applications', app['id'], current)
        return rendered
    monkeypatch.setattr(module, 'render_preview', mutate)
    with pytest.raises((DriverVerificationError, IdentityVerificationError)):
        service.get_document_preview(staff, app['documents'][0]['id'])
    with store.read() as tx: assert tx.list(kind + '_document_access') == []


def test_legacy_and_previous_version_receipts_cannot_approve():
    app = {'id': 'app', 'version': 2}; doc = {'id': 'doc'}
    receipt = {'actor_id': 'staff', 'application_id': 'app', 'document_id': 'doc'}
    assert not preview.inspection_complete([receipt], 'staff', app, [doc])
    receipt.update(mode='watermarked_preview', application_version=1, page=1, page_count=1)
    assert not preview.inspection_complete([receipt], 'staff', app, [doc])


def test_corrupt_render_records_no_inspection(case):
    kind, store, service, owner, staff, outsider, app = case
    document = app['documents'][0]
    raw = b'%PDF-1.7\nThis is corrupt, not evidence.'
    stored = service._cipher.encrypt(raw)
    with store.transaction() as tx:
        tx._connection.execute('UPDATE ' + kind + '_document_blobs SET content=? WHERE id=?', (stored, document['id']))
    with pytest.raises((DriverVerificationError, IdentityVerificationError)) as caught:
        service.get_document_preview(staff, document['id'])
    assert caught.value.code == ('document_preview_invalid' if kind == 'identity' else 'verification_evidence_unavailable')
    with store.read() as tx: assert tx.list(kind + '_document_access') == []


def test_owner_promoted_to_reviewer_cannot_self_inspect(case):
    kind, store, service, owner, staff, outsider, app = case
    with store.transaction() as tx:
        current = tx.get('users', owner['id'])
        current.update(role='staff', staff_capabilities=['verify.review'])
        tx.put('users', owner['id'], current)
    with pytest.raises((DriverVerificationError, IdentityVerificationError)) as caught:
        service.get_document_preview(current, app['documents'][0]['id'])
    assert caught.value.status == 403 and caught.value.code.endswith('self_review')
    with store.read() as tx: assert tx.list(kind + '_document_access') == []


def test_worker_environment_does_not_inherit_application_secrets(monkeypatch):
    monkeypatch.setenv('IDENTITY_EVIDENCE_KEY', 'synthetic-secret-do-not-pass')
    monkeypatch.setenv('SECRET_KEY', 'synthetic-secret-do-not-pass')
    real = preview.subprocess.Popen
    observed = []
    def capture(*args, **kwargs):
        observed.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(preview.subprocess, 'Popen', capture)
    preview.render_preview(image_bytes(), 'image/png', 1, 'staff', AT)
    assert set(observed[0]['env']) == {'PATH', 'LANG'}
    assert observed[0]['stderr'] == subprocess.DEVNULL and observed[0]['close_fds'] is True
