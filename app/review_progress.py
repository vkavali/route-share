"""Private reviewer-scoped checklist; caller holds the service access transaction."""
import hashlib
import re

from .auth import current_actor_matches
from .document_preview import inspection_complete

COLLECTION = 'document_review_progress'
SCHEMAS = {
    'identity': (('identity_document', ('document_readable', 'name_matches', 'adult_confirmed')),
                 ('selfie', ('photo_matches',))),
    'driver': (('dl', ('dl',)), ('rc', ('rc',)), ('insurance', ('insurance',)),
               ('selfie', ('identity_match',))),
}


def discard_application(tx, namespace, application_id):
    for row in tx.list(COLLECTION):
        if row.get('namespace') == namespace and row.get('application_id') == application_id:
            tx.delete(COLLECTION, row['id'])


def discard_user(tx, user_id):
    for row in tx.list(COLLECTION):
        if row.get('user_id') == user_id or row.get('actor_id') == user_id:
            tx.delete(COLLECTION, row['id'])


def _key(namespace, actor, app):
    return hashlib.sha256(f'{namespace}:{actor["id"]}:{app["id"]}:{app["version"]}'.encode()).hexdigest()


def _invalid(error):
    error('Supply the exact checklist fields and explicit boolean checks.', 400, 'review_progress_invalid')


def application(tx, namespace, actor, application_id, error, expected=None):
    if not isinstance(application_id, str) or not re.fullmatch(r'[a-f0-9]{32}', application_id):
        _invalid(error)
    app = tx.get(namespace + '_applications', application_id)
    if not app:
        error('Application not found.', 404)
    if app['user_id'] == actor['id']:
        error('You cannot review your own application.', 403,
              'identity_self_review' if namespace == 'identity' else 'verification_self_review')
    target = tx.get('users', app['user_id'])
    if not target or target.get('role') != 'member' or not current_actor_matches(target, target):
        error('Application not found.', 404)
    if expected is not None and app['version'] != expected:
        error('Application changed. Reload its current documents.', 409, 'review_progress_version_conflict')
    if app.get('status') != 'submitted' or app.get('document_consent') is not True:
        error('Only a submitted, consented application can be checked.', 409, 'review_progress_locked')
    docs = {d['kind']: d for d in tx.list(namespace + '_documents')
            if d.get('application_id') == app['id'] and d.get('user_id') == app['user_id']}
    if set(docs) != {key for key, _ in SCHEMAS[namespace]}:
        error('Current documents are required.', 409, 'review_progress_locked')
    return app, docs


def get(tx, namespace, actor, app, docs):
    row = tx.get(COLLECTION, _key(namespace, actor, app)) or {}
    saved = row.get('steps', {})
    receipts = tx.list(namespace + '_document_access')
    steps, current = [], None
    for key, fields in SCHEMAS[namespace]:
        entry = saved.get(key, {})
        values = entry.get('checks', {}) if entry.get('document_id') == docs[key]['id'] else {}
        checks = {field: values.get(field) is True for field in fields}
        complete = (current is None and all(checks.values()) and
                    inspection_complete(receipts, actor['id'], app, [docs[key]]))
        if not complete and current is None:
            current = key
        steps.append(dict(key=key, document_id=docs[key]['id'], checks=checks, complete=complete))
    return dict(application_id=app['id'], application_version=app['version'],
                revision=row.get('revision', 0), steps=steps, current_step=current,
                ready_for_approval=current is None)


def validate(payload, namespace, error):
    if not isinstance(payload, dict) or set(payload) != {'application_id', 'expected_version', 'expected_revision', 'step', 'checks'}:
        _invalid(error)
    if any(type(payload[k]) is not int or not 0 <= payload[k] <= 2**53 - 1
           for k in ('expected_version', 'expected_revision')):
        _invalid(error)
    schema = dict(SCHEMAS[namespace])
    step, checks = payload['step'], payload['checks']
    if (not isinstance(step, str) or step not in schema or not isinstance(checks, dict)
            or set(checks) != set(schema[step]) or any(type(v) is not bool for v in checks.values())):
        _invalid(error)


def save(tx, namespace, actor, app, docs, payload, at, error):
    progress = get(tx, namespace, actor, app, docs)
    if progress['revision'] != payload['expected_revision']:
        error('Checklist changed in another tab. Reload it.', 409, 'review_progress_revision_conflict')
    keys = [key for key, _ in SCHEMAS[namespace]]
    index = keys.index(payload['step'])
    first = keys.index(progress['current_step']) if progress['current_step'] else len(keys)
    if index > first:
        error('Complete the earlier document checks first.', 409, 'review_progress_step_locked')
    checks = payload['checks']
    if all(checks.values()) and not inspection_complete(tx.list(namespace + '_document_access'), actor['id'], app, [docs[payload['step']]]):
        error('View every page of this current document first.', 409, 'review_progress_documents_unread')
    row_id = _key(namespace, actor, app)
    row = tx.get(COLLECTION, row_id) or dict(id=row_id, namespace=namespace,
        actor_id=actor['id'], user_id=app['user_id'], application_id=app['id'],
        application_version=app['version'], steps={})
    stamp = at.isoformat()
    row['steps'][payload['step']] = dict(document_id=docs[payload['step']]['id'],
        checks=dict(checks), updated_at=stamp, completed_at=stamp if all(checks.values()) else None)
    if not all(checks.values()):
        for later in keys[index + 1:]:
            row['steps'].pop(later, None)
    row.update(revision=progress['revision'] + 1, updated_at=stamp)
    tx.put(COLLECTION, row_id, row)
    return get(tx, namespace, actor, app, docs)


def approval_snapshot(tx, namespace, actor, app, docs, error):
    progress = get(tx, namespace, actor, app, docs)
    if not progress['ready_for_approval']:
        error('Complete and save every document checklist before approval.', 409, 'review_progress_incomplete')
    row = tx.get(COLLECTION, _key(namespace, actor, app))
    return dict(application_version=app['version'], revision=progress['revision'], steps=row['steps'])
