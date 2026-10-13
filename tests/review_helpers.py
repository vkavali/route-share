"""Complete real saved reviewer checks after the fixture has viewed every page."""
def complete_checklist(service, reviewer, app):
    progress = service.get_review_progress(reviewer, app['id'])
    for step in progress['steps']:
        progress = service.save_review_progress(reviewer, dict(application_id=app['id'],
            expected_version=app['version'], expected_revision=progress['revision'], step=step['key'],
            checks={key: True for key in step['checks']}))
    assert progress['ready_for_approval']
    return progress
