from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.payments import PaymentError, PaymentService
from app.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'payments.sqlite')
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    identity_review = {'kind': 'human_document_review', 'source': 'identity_application',
                       'application_id': 'synthetic-id-review', 'reviewed_at': datetime.now(timezone.utc).isoformat(), 'expires_at': expiry}
    identity = {'identity_approval': identity_review, 'role': 'member', 'development': False, 'auth_method': 'phone', 'phone_verified': True,
                'account_status': 'active'}
    users = {'driver': {'id': 'driver', **identity, 'auth_phone': '+919876543210', 'driver_approved': True,
                        'verification': {key: 'verified' for key in ('dl', 'rc', 'insurance', 'selfie', 'identity')},
                        'driver_approval': {'kind': 'reviewed', 'expires_at': expiry,
                            'document_expiries': {key: expiry for key in ('dl', 'rc', 'insurance')}}},
             'passenger': {'id': 'passenger', **identity, 'auth_phone': '+919876543211'},
             'outsider': {'id': 'outsider', 'role': 'member'}, 'staff': {'id': 'staff', 'role': 'staff'}}
    with store.transaction() as tx:
        for user in users.values(): tx.put('users', user['id'], user)
        tx.put('trips', 'trip', {'id': 'trip', 'driver_id': 'driver', 'status': 'published'})
        for bid in ('booking', 'booking2'):
            tx.put('bookings', bid, {'id': bid, 'trip_id': 'trip', 'driver_id': 'driver',
                                   'passenger_id': 'passenger', 'status': 'accepted'})
    service = PaymentService(store, enabled=True)
    service.dispatch('trip_budget_action', users['driver'], dict(trip_id='trip', action='set_budget',
        expected_version=0, idempotency_key='initial-budget', fuel_paise=50000, toll_paise=10000,
        owner_share_paise=10000, reason='Owner estimate of trip expenses'))
    return store, service, users


def command(service, users, role, action, version, key=None, bid='booking', **kwargs):
    return service.dispatch('payment_action', users[role], dict(booking_id=bid, action=action,
        expected_version=version, idempotency_key=key or f'{bid}-{action}-{version}', **kwargs))


def propose(service, users, bid='booking', **kwargs):
    payload = dict(amount_paise=12345, breakdown={'fuel_paise': 10000, 'toll_paise': 2345},
                   note='Shared actual fuel and toll', payee_name='Meera & Rao', upi_id='meera.rao@okbank')
    payload.update(kwargs)
    return command(service, users, 'driver', 'propose', 0, bid=bid, **payload)


def view(service, users, role='passenger', bid='booking'):
    return service.dispatch('payment', users[role], {'booking_id': bid})['payment']


def test_complete_cycle_twice_and_restart(setup):
    store, service, users = setup
    references = []
    for bid in ('booking', 'booking2'):
        assert view(service, users, bid=bid)['status'] == 'unquoted'
        proposed = propose(service, users, bid=bid)['payment']
        assert proposed['upi_id'] is None and proposed['upi_uri'] is None
        agreement = command(service, users, 'passenger', 'agree', 1, bid=bid)['payment']
        references.append(agreement['reference'])
        uri = urlparse(agreement['upi_uri'])
        assert (uri.scheme, uri.netloc) == ('upi', 'pay')
        assert parse_qs(uri.query) == {'pa': ['meera.rao@okbank'], 'pn': ['Meera & Rao'],
            'am': ['123.45'], 'cu': ['INR'], 'tn': ['Shared trip expense'], 'tr': [agreement['reference']]}
        # Visiting the payment or following an external link cannot change state.
        assert view(service, users, bid=bid)['status'] == 'agreed'
        assert view(service, users, 'driver', bid)['upi_uri'] is None
        paid = command(service, users, 'passenger', 'report_paid', 2, bid=bid)['payment']
        assert paid['status'] == 'passenger_reported' and paid['upi_uri'] is None
        confirmed = command(service, users, 'driver', 'confirm_received', 3, bid=bid)['payment']
        assert confirmed['status'] == 'owner_confirmed' and confirmed['verification'] == 'manual_only'
        command(service, users, 'passenger', 'request_refund', 4, bid=bid)
        command(service, users, 'driver', 'report_refund', 5, bid=bid)
        final = command(service, users, 'passenger', 'confirm_refund', 6, bid=bid)['payment']
        assert final['status'] == 'refunded' and len(final['events']) == 7
        assert final['reference'] == agreement['reference'] and final['allowed_actions'] == []
    assert len(set(references)) == 2
    restarted = PaymentService(Store(store.path), enabled=True)
    assert view(restarted, users)['status'] == 'refunded'
    with store.read() as tx:
        assert len(tx.list('payment_events')) == 14
        assert tx.list('events') == []
        assert all('note' not in e and 'upi_id' not in e for e in tx.list('payment_events'))
        assert 'upi_id' not in tx.get('users', 'driver') and 'amount_paise' not in tx.get('trips', 'trip')


def test_duplicate_and_race_do_not_double_apply(setup):
    store, service, users = setup
    first = propose(service, users)
    assert propose(service, users)['replayed'] is True
    assert view(service, users)['version'] == 1
    with pytest.raises(PaymentError) as error: propose(service, users, note='Changed same key')
    assert error.value.code == 'idempotency_conflict'
    def accept(key):
        try: return command(service, users, 'passenger', 'agree', 1, key=key)['payment']['status']
        except PaymentError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(accept, ['race-a', 'race-b']))
    assert sorted(outcomes) == ['agreed', 'version_conflict']
    with store.read() as tx: assert len(tx.list('payment_events')) == 2
    assert first['payment']['reference'] == view(service, users)['reference']


def test_wrong_roles_private_account_and_quote_freeze(setup):
    store, service, users = setup
    for role in ('outsider', 'staff'):
        with pytest.raises(PaymentError): view(service, users, role)
        with pytest.raises(PaymentError): command(service, users, role, 'propose', 0)
    with pytest.raises(PaymentError): command(service, users, 'passenger', 'propose', 0)
    propose(service, users)
    with pytest.raises(PaymentError): command(service, users, 'driver', 'agree', 1)
    command(service, users, 'passenger', 'agree', 1)
    with pytest.raises(PaymentError): command(service, users, 'driver', 'propose', 2, key='overwrite')
    with pytest.raises(PaymentError): command(service, users, 'driver', 'report_paid', 2)
    with pytest.raises(PaymentError): command(service, users, 'passenger', 'confirm_received', 2)
    with pytest.raises(PaymentError): service.dispatch('payout_account', users['passenger'], {'user_id': 'driver'})
    assert service.dispatch('payout_account', users['driver'], {})['payout_account']['upi_id'] == 'meera.rao@okbank'
    # Always reload role from persistence, rather than trust stale caller claims.
    with store.transaction() as tx: tx.put('users', 'passenger', {'id': 'passenger', 'role': 'staff'})
    with pytest.raises(PaymentError): view(service, users)


@pytest.mark.parametrize('change', ['blocked', 'cancelled', 'trip_cancelled'])
def test_pair_end_removes_payment_target_but_preserves_refund_rights(setup, change):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    command(service, users, 'passenger', 'report_paid', 2)
    with store.transaction() as tx:
        if change == 'blocked': tx.put('blocks', 'driver:passenger', {'id': 'driver:passenger'})
        elif change == 'cancelled':
            booking = tx.get('bookings', 'booking'); booking['status'] = 'cancelled'; tx.put('bookings', 'booking', booking)
        else:
            trip = tx.get('trips', 'trip'); trip['status'] = 'cancelled'; tx.put('trips', 'trip', trip)
    result = view(service, users)
    assert result['upi_uri'] is None and result['upi_id'] is None and result['payee_name'] is None
    # Historic receipt reconciliation remains available after collection eligibility ends.
    assert 'confirm_received' in view(service, users, 'driver')['allowed_actions']
    command(service, users, 'passenger', 'dispute', 3)
    command(service, users, 'passenger', 'request_refund', 4)
    command(service, users, 'driver', 'report_refund', 5)
    assert command(service, users, 'passenger', 'confirm_refund', 6)['payment']['status'] == 'refunded'


def test_disabled_and_stale_replay_do_not_reveal_payment_target(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    disabled = PaymentService(store)
    result = disabled.dispatch('payments', users['passenger'], {})
    assert result['enabled'] is False
    assert all(row['upi_uri'] is None and row['upi_id'] is None and row['allowed_actions'] == [] for row in result['payments'])
    with pytest.raises(PaymentError) as error: command(disabled, users, 'passenger', 'report_paid', 2)
    assert error.value.code == 'payments_disabled'
    with store.transaction() as tx: tx.put('blocks', 'passenger:driver', {'id': 'passenger:driver'})
    replay = command(service, users, 'passenger', 'agree', 1)
    assert replay['replayed'] is True and replay['payment']['upi_uri'] is None


@pytest.mark.parametrize('override', [
    {'amount_paise': True}, {'amount_paise': 12.5}, {'amount_paise': '12345'}, {'amount_paise': 0},
    {'amount_paise': -1}, {'amount_paise': 10_000_001}, {'breakdown': {'fuel_paise': 12345, 'toll_paise': True}},
    {'breakdown': {'fuel_paise': 12345, 'toll_paise': 1}}, {'breakdown': {'fuel_paise': 12345, 'tax_paise': 0}},
    {'upi_id': 'https://evil.example'}, {'upi_id': 'meera@bank&am=1'}, {'upi_id': 'meera@bank\n'},
    {'payee_name': '<test>\n'}, {'note': 'x'*241},
])
def test_invalid_proposal_is_atomic(setup, override):
    store, service, users = setup
    with pytest.raises(PaymentError): propose(service, users, **override)
    with store.read() as tx:
        assert not tx.list('payments') and not tx.list('payment_events') and not tx.list('payout_accounts')


def test_no_refund_claim_on_unpaid_dispute_and_completed_eligible(setup):
    store, service, users = setup
    propose(service, users)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking'); booking['status'] = 'segment_completed'; tx.put('bookings', 'booking', booking)
        trip = tx.get('trips', 'trip'); trip['status'] = 'completed'; tx.put('trips', 'trip', trip)
    assert command(service, users, 'passenger', 'agree', 1)['payment']['upi_uri']
    command(service, users, 'passenger', 'dispute', 2)
    for role, action in [('passenger', 'request_refund'), ('driver', 'report_refund')]:
        with pytest.raises(PaymentError): command(service, users, role, action, 3)
    assert view(service, users)['upi_uri'] is None


def test_approval_expiry_blocks_new_quote_but_not_reconciliation(setup):
    store, service, users = setup
    with store.transaction() as tx:
        driver = tx.get('users', 'driver'); driver['driver_approval']['expires_at'] = '2020-01-01T00:00:00+00:00'; tx.put('users', 'driver', driver)
    with pytest.raises(PaymentError): propose(service, users)


def test_revision_before_agreement_and_snapshot_after_account_change(setup):
    store, service, users = setup
    initial = propose(service, users)['payment']
    revised = command(service, users, 'driver', 'propose', 1, key='revision', amount_paise=9000,
        breakdown={'fuel_paise': 8000, 'toll_paise': 1000}, note='Revised expense',
        payee_name='Meera', upi_id='meera@okbank')['payment']
    assert revised['reference'] == initial['reference'] and revised['version'] == 2
    agreed = command(service, users, 'passenger', 'agree', 2)['payment']
    propose(service, users, bid='booking2', upi_id='different@bank')
    assert view(service, users)['upi_id'] == 'meera@okbank'
    assert view(service, users)['upi_uri'] == agreed['upi_uri']
    assert service.dispatch('payout_account', users['driver'], {})['payout_account']['upi_id'] == 'different@bank'


@pytest.mark.parametrize('status', ['pending', 'declined', 'cancelled'])
def test_unaccepted_booking_cannot_quote_or_agree(setup, status):
    store, service, users = setup
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking'); booking['status'] = status; tx.put('bookings', 'booking', booking)
    assert view(service, users)['allowed_actions'] == []
    with pytest.raises(PaymentError): propose(service, users)
    assert all(p['booking_id'] != 'booking' for p in service.dispatch('payments', users['passenger'], {})['payments'])


def test_invalid_version_and_idempotency_key(setup):
    _, service, users = setup
    for version in (True, -1, '0', 1.1):
        with pytest.raises(PaymentError): command(service, users, 'driver', 'propose', version)
    for key in ('contains spaces', 'x'*81, 'bad\nkey'):
        with pytest.raises(PaymentError): command(service, users, 'driver', 'propose', 0, key=key)


@pytest.mark.parametrize('change',['revoke','vehicle'])
@pytest.mark.parametrize('stage',['before_agree','before_payment'])
def test_current_approval_and_vehicle_required_to_continue_transfer(setup,change,stage):
    store,service,users=setup
    propose(service,users)
    version=1
    if stage=='before_payment':
        command(service,users,'passenger','agree',1)
        assert view(service,users)['upi_uri']
        version=2
    with store.transaction() as tx:
        driver=tx.get('users','driver')
        if change=='revoke':driver['driver_approved']=False
        else:driver['vehicle']={'model':'Different car','plate':'CHANGED123'}
        tx.put('users','driver',driver)
    current=view(service,users)
    assert current['upi_uri'] is None
    if stage == 'before_agree':
        assert 'agree' not in current['allowed_actions']
        with pytest.raises(PaymentError) as error:
            command(service,users,'passenger','agree',version)
        assert error.value.status==409
    else:
        # Recording an already-made transfer remains possible after approval or
        # vehicle eligibility is lost; the UI offers no new payment link.
        assert 'report_paid' in current['allowed_actions']
        command(service,users,'passenger','report_paid',version)
    with pytest.raises(PaymentError):
        command(service,users,'driver','propose',version,key='replacement-after-change',amount_paise=100,
                breakdown={'fuel_paise':100,'toll_paise':0},payee_name='Owner',upi_id='owner@bank')


@pytest.mark.parametrize('change',['revoke','vehicle'])
def test_paid_refund_rights_survive_approval_or_vehicle_change(setup,change):
    store,service,users=setup
    propose(service,users);command(service,users,'passenger','agree',1)
    command(service,users,'passenger','report_paid',2)
    with store.transaction() as tx:
        driver=tx.get('users','driver')
        if change=='revoke':driver['driver_approved']=False
        else:driver['vehicle']={'model':'Different car','plate':'CHANGED123'}
        tx.put('users','driver',driver)
    assert view(service,users)['upi_uri'] is None
    command(service,users,'passenger','dispute',3)
    assert 'request_refund' in view(service,users)['allowed_actions']
    command(service,users,'passenger','request_refund',4)
    assert 'report_refund' in view(service,users,'driver')['allowed_actions']
    command(service,users,'driver','report_refund',5)
    assert command(service,users,'passenger','confirm_refund',6)['payment']['status']=='refunded'


@pytest.mark.parametrize('action',[[],{},None,True,4])
def test_malformed_action_is_400_not_unhashable_crash(setup,action):
    _,service,users=setup
    with pytest.raises(PaymentError) as error:
        service.dispatch('payment_action',users['passenger'],{'booking_id':'booking','action':action,
            'expected_version':0,'idempotency_key':'malformed-action'})
    assert error.value.status==400


def budget(service, users, *, role='driver', version=1, key='updated-budget', **changes):
    payload = dict(trip_id='trip', action='set_budget', expected_version=version, idempotency_key=key,
                   fuel_paise=40000, toll_paise=10000, owner_share_paise=10000, reason='Updated owner estimate')
    payload.update(changes)
    return service.dispatch('trip_budget_action', users[role], payload)


def budget_view(service, users, role='driver'):
    return service.dispatch('trip_budget', users[role], {'trip_id': 'trip'})


def test_budget_requires_owner_declaration_and_blocks_new_transfer_without_it(setup):
    store, service, users = setup
    with store.transaction() as tx: tx.delete('trip_expense_budgets', 'trip')
    assert budget_view(service, users)['budget'] is None
    assert view(service, users, 'driver')['can_manage_budget'] is True
    assert view(service, users, 'passenger')['can_manage_budget'] is False
    assert 'propose' not in view(service, users, 'driver')['allowed_actions']
    with pytest.raises(PaymentError): propose(service, users)
    declared = budget(service, users, version=0)['budget']
    assert declared['declaration'] == 'owner_declared_unverified'
    assert declared['total_paise'] == 50000 and declared['passenger_cap_paise'] == 40000
    assert declared['reserved_paise'] == 0 and declared['remaining_paise'] == 40000
    propose(service, users)
    assert view(service, users)['budget']['reserved_paise'] == 12345
    with store.read() as tx:
        assert 'fuel_paise' not in tx.get('trips', 'trip')
        assert 'owner_share_paise' not in tx.get('users', 'driver')


@pytest.mark.parametrize('changes', [
    {'fuel_paise': True}, {'toll_paise': -1}, {'owner_share_paise': 0}, {'owner_share_paise': 50001},
    {'fuel_paise': 0, 'toll_paise': 0}, {'fuel_paise': 10000000}, {'owner_share_paise': '10'},
    {'fuel_paise': 1.5}, {'reason': ''}, {'reason': 'x' * 241}, {'reason': 'bad\nreason'},
])
def test_invalid_budget_changes_are_atomic(setup, changes):
    store, service, users = setup
    before = budget_view(service, users)
    with pytest.raises(PaymentError): budget(service, users, **changes)
    assert budget_view(service, users) == before
    with store.read() as tx:
        assert len(tx.list('trip_budget_events')) == 1


def test_budget_private_actor_and_idempotent_versioned_history(setup):
    store, service, users = setup
    for role in ('passenger', 'outsider', 'staff'):
        with pytest.raises(PaymentError): budget(service, users, role=role)
    for role in ('outsider', 'staff'):
        with pytest.raises(PaymentError): budget_view(service, users, role)
    assert budget_view(service, users, 'passenger')['allowed_actions'] == []
    updated = budget(service, users)
    assert updated['applied_version'] == 2
    assert budget(service, users)['replayed'] is True
    with pytest.raises(PaymentError) as e: budget(service, users, reason='Different same key')
    assert e.value.code == 'idempotency_conflict'
    with pytest.raises(PaymentError) as e: budget(service, users, key='stale-new-key')
    assert e.value.code == 'version_conflict'
    with store.read() as tx: assert len(tx.list('trip_budget_events')) == 2
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking'); booking['status'] = 'pending'; tx.put('bookings', 'booking', booking)
        booking = tx.get('bookings', 'booking2'); booking['status'] = 'pending'; tx.put('bookings', 'booking2', booking)
    with pytest.raises(PaymentError): budget_view(service, users, 'passenger')


def test_aggregate_cap_includes_proposals_revisions_and_never_mutates_agreements(setup):
    _, service, users = setup
    budget(service, users, fuel_paise=20000, toll_paise=5000, owner_share_paise=5000)
    propose(service, users)
    with pytest.raises(PaymentError) as e: propose(service, users, bid='booking2')
    assert e.value.code == 'expense_cap_exceeded'
    command(service, users, 'driver', 'propose', 1, key='lower', amount_paise=7000,
            breakdown={'fuel_paise': 6000, 'toll_paise': 1000}, payee_name='Owner', upi_id='owner@bank')
    propose(service, users, bid='booking2')
    agreed = command(service, users, 'passenger', 'agree', 2)['payment']
    assert agreed['budget']['reserved_paise'] == 19345
    before = {k: agreed[k] for k in ('amount_paise', 'breakdown', 'note', 'budget_at_agreement')}
    with pytest.raises(PaymentError) as e:
        budget(service, users, version=2, key='too-low', fuel_paise=20000, toll_paise=0, owner_share_paise=10000)
    assert e.value.code == 'expense_cap_exceeded'
    budget(service, users, version=2, key='increase-budget', fuel_paise=40000)
    after = view(service, users)
    assert {k: after[k] for k in before} == before
    assert after['budget']['version'] == 3


def test_simultaneous_bookings_cannot_overreserve_trip(setup):
    store, service, users = setup
    budget(service, users, fuel_paise=20000, toll_paise=0, owner_share_paise=5000)
    def reserve(bid):
        try: return propose(service, users, bid=bid)['payment']['status']
        except PaymentError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ['booking', 'booking2']))
    assert sorted(results) == ['expense_cap_exceeded', 'proposed']
    assert budget_view(service, users)['budget']['reserved_paise'] == 12345
    with store.read() as tx: assert len(tx.list('payments')) == 1


def test_budget_reduction_racing_quote_never_overreserves(setup):
    _, service, users = setup
    def operate(action):
        try:
            if action == 'quote': return propose(service, users)['payment']['status']
            return budget(service, users, fuel_paise=10000, toll_paise=0, owner_share_paise=5000)['budget']['version']
        except PaymentError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(operate, ['quote', 'reduce']))
    assert results.count('expense_cap_exceeded') == 1
    state = budget_view(service, users)['budget']
    assert state['reserved_paise'] <= state['passenger_cap_paise']


def test_legacy_transfer_reporting_and_refund_without_budget_and_cap_release(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx: tx.delete('trip_expense_budgets', 'trip')
    legacy = view(service, users)
    assert legacy['collection_available'] is False and legacy['upi_uri'] is None and legacy['upi_id'] is None
    assert 'report_paid' in legacy['allowed_actions']
    with pytest.raises(PaymentError) as e:
        budget(service, users, version=0, fuel_paise=10000, toll_paise=0, owner_share_paise=1)
    assert e.value.code == 'expense_cap_exceeded'
    command(service, users, 'passenger', 'report_paid', 2)
    command(service, users, 'driver', 'confirm_received', 3)
    command(service, users, 'passenger', 'request_refund', 4)
    command(service, users, 'driver', 'report_refund', 5)
    restored = budget(service, users, version=0)['budget']
    assert restored['reserved_paise'] == 12345
    command(service, users, 'passenger', 'confirm_refund', 6)
    assert budget_view(service, users)['budget']['reserved_paise'] == 0


@pytest.mark.parametrize('terminal_kind,status', [('booking', 'segment_completed'), ('booking', 'cancelled'),
    ('booking', 'declined'), ('trip', 'completed'), ('trip', 'cancelled')])
def test_void_unpaid_owner_terminal_only_audited_and_frees_cap(setup, terminal_kind, status):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with pytest.raises(PaymentError): command(service, users, 'driver', 'void_unpaid', 2, reason='No payment received')
    with store.transaction() as tx:
        collection = 'bookings' if terminal_kind == 'booking' else 'trips'
        identity = 'booking' if terminal_kind == 'booking' else 'trip'
        record = tx.get(collection, identity); record['status'] = status; tx.put(collection, identity, record)
    with pytest.raises(PaymentError): command(service, users, 'passenger', 'void_unpaid', 2, reason='No payment')
    with pytest.raises(PaymentError): command(service, users, 'driver', 'void_unpaid', 2, reason='')
    result = command(service, users, 'driver', 'void_unpaid', 2, reason='No transfer received')['payment']
    assert result['status'] == 'voided_unpaid' and result['void_reason'] == 'No transfer received'
    passenger = view(service, users)
    assert passenger['upi_uri'] is None and passenger['upi_id'] is None and passenger['collection_available'] is False
    assert 'report_paid' in passenger['allowed_actions'] and passenger['events'][-1]['reason'] == 'No transfer received'
    assert passenger['amount_paise'] == 12345 and passenger['budget']['reserved_paise'] == 0
    assert command(service, users, 'driver', 'void_unpaid', 2, reason='No transfer received')['replayed'] is True


def test_reported_transfer_cannot_be_voided_and_race_is_atomic(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking'); booking['status'] = 'segment_completed'; tx.put('bookings', 'booking', booking)
    def operate(action):
        try:
            role = 'driver' if action == 'void_unpaid' else 'passenger'
            return command(service, users, role, action, 2, reason='Owner states no transfer')['payment']['status']
        except PaymentError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(operate, ['report_paid', 'void_unpaid']))
    assert results.count('version_conflict') == 1
    final = view(service, users)
    assert final['status'] in {'passenger_reported', 'voided_unpaid'}
    if final['status'] == 'passenger_reported':
        assert 'void_unpaid' not in view(service, users, 'driver')['allowed_actions']
        with pytest.raises(PaymentError): command(service, users, 'driver', 'void_unpaid', 3, reason='No transfer')
    assert len(final['events']) == 3


def test_zero_passenger_cap_and_full_cap_keep_actions_truthful(setup):
    _, service, users = setup
    budget(service, users, fuel_paise=10000, toll_paise=0, owner_share_paise=10000)
    assert 'propose' not in view(service, users, 'driver')['allowed_actions']
    budget(service, users, version=2, key='one-quote-cap', fuel_paise=13000, toll_paise=0, owner_share_paise=655)
    propose(service, users)
    assert budget_view(service, users)['budget']['remaining_paise'] == 0
    assert 'propose' in view(service, users, 'driver')['allowed_actions']
    assert 'propose' not in view(service, users, 'driver', 'booking2')['allowed_actions']


def test_confirmed_disputed_refund_claims_reserve_until_recipient_confirmation(setup):
    _, service, users = setup
    propose(service, users)
    for role, action, version in [('passenger', 'agree', 1), ('passenger', 'report_paid', 2),
        ('driver', 'confirm_received', 3), ('passenger', 'dispute', 4),
        ('passenger', 'request_refund', 5), ('driver', 'report_refund', 6)]:
        command(service, users, role, action, version)
        assert budget_view(service, users)['budget']['reserved_paise'] == 12345
    command(service, users, 'passenger', 'confirm_refund', 7)
    assert budget_view(service, users)['budget']['reserved_paise'] == 0


@pytest.mark.parametrize('change', [{'account_status': 'closed'}, {'status': 'disabled'},
    {'disabled': True}, {'suspended': True}, {'is_active': False}, {'auth_epoch': 1}])
def test_budget_and_payment_reads_writes_replays_recheck_current_actor(setup, change):
    store, service, users = setup
    propose(service, users)
    with store.transaction() as tx:
        actor = tx.get('users', 'driver'); actor.update(change); tx.put('users', 'driver', actor)
    for call in [lambda: budget_view(service, users), lambda: budget(service, users),
                 lambda: view(service, users, 'driver'), lambda: propose(service, users)]:
        with pytest.raises(PaymentError) as error: call()
        assert error.value.status == 403
    with store.read() as tx:
        assert len(tx.list('payment_events')) == 1
        assert len(tx.list('trip_budget_events')) == 1


def test_budget_new_actor_epoch_works_and_other_trip_cannot_be_addressed(setup):
    store, service, users = setup
    with store.transaction() as tx:
        actor = tx.get('users', 'driver'); actor['auth_epoch'] = 1; tx.put('users', 'driver', actor)
        tx.put('trips', 'other-trip', {'id': 'other-trip', 'driver_id': 'outsider', 'status': 'published'})
    users['driver']['auth_epoch'] = 1
    assert budget(service, users)['budget']['version'] == 2
    with pytest.raises(PaymentError):
        service.dispatch('trip_budget', users['driver'], {'trip_id': 'other-trip'})


@pytest.mark.parametrize('participant', ['driver', 'passenger'])
@pytest.mark.parametrize('change', [
    {'development': True}, {'development': None}, {'development': 0}, {'auth_method': 'password'},
    {'phone_verified': False}, {'phone_verified': 'true'}, {'auth_phone': ''}, {'auth_phone': '9876543210'},
    {'auth_phone': '+915876543210'}, {'auth_phone': '+91９876543210'}, {'account_status': 'closed'},
])
def test_either_nonindividual_participant_cannot_start_collection(setup, participant, change):
    store, service, users = setup
    with store.transaction() as tx:
        record = tx.get('users', participant); record.update(change); tx.put('users', participant, record)
    other = 'passenger' if participant == 'driver' else 'driver'
    current = view(service, users, other)
    assert current['collection_available'] is False and current['upi_uri'] is None
    assert current['collection_eligibility'] == {'eligible': False, 'reason': 'verified_individual_accounts_required'}
    with pytest.raises(PaymentError): propose(service, users)
    if participant == 'driver':
        with pytest.raises(PaymentError): budget(service, users)
    with store.read() as tx: assert not tx.list('payments')


@pytest.mark.parametrize('approval_change', [
    {'kind': 'development'}, {'kind': 'unknown'}, {'expires_at': '2020-01-01T00:00:00+00:00'},
    {'document_expiries': {}},
])
def test_reviewed_current_driver_required_despite_verified_phone(setup, approval_change):
    store, service, users = setup
    with store.transaction() as tx:
        record = tx.get('users', 'driver'); record['driver_approval'].update(approval_change); tx.put('users', 'driver', record)
    assert view(service, users)['collection_eligibility']['reason'] == 'reviewed_driver_required'
    assert budget_view(service, users)['eligibility']['reason'] == 'reviewed_driver_required'
    with pytest.raises(PaymentError): propose(service, users)
    with pytest.raises(PaymentError): budget(service, users)


@pytest.mark.parametrize('participant', ['driver', 'passenger'])
def test_identity_loss_blocks_acceptance_and_existing_upi_then_restoration_recovers(setup, participant):
    store, service, users = setup
    propose(service, users)
    with store.transaction() as tx:
        record = tx.get('users', participant); record['development'] = True; tx.put('users', participant, record)
    assert 'agree' not in view(service, users)['allowed_actions']
    with pytest.raises(PaymentError): command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        record = tx.get('users', participant); record['development'] = False; tx.put('users', participant, record)
    agreed = command(service, users, 'passenger', 'agree', 1)['payment']
    assert agreed['upi_uri'] and agreed['collection_eligibility'] == {'eligible': True, 'reason': None}
    with store.transaction() as tx:
        record = tx.get('users', participant); record['phone_verified'] = False; tx.put('users', participant, record)
    current = view(service, users)
    assert current['upi_uri'] is None and current['upi_id'] is None and current['collection_available'] is False
    # Replayed agreement uses the current eligibility projection too.
    assert command(service, users, 'passenger', 'agree', 1)['payment']['upi_uri'] is None
    command(service, users, 'passenger', 'report_paid', 2)
    command(service, users, 'driver', 'confirm_received', 3)
    command(service, users, 'passenger', 'dispute', 4)
    command(service, users, 'passenger', 'request_refund', 5)
    command(service, users, 'driver', 'report_refund', 6)
    assert command(service, users, 'passenger', 'confirm_refund', 7)['payment']['status'] == 'refunded'


def test_owner_review_withdrawal_allows_existing_manual_receipt_and_refund(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        owner = tx.get('users', 'driver'); owner['driver_approved'] = False; tx.put('users', 'driver', owner)
    assert view(service, users)['collection_eligibility']['reason'] == 'reviewed_driver_required'
    assert view(service, users)['upi_uri'] is None
    command(service, users, 'passenger', 'report_paid', 2)
    command(service, users, 'driver', 'confirm_received', 3)
    command(service, users, 'passenger', 'request_refund', 4)
    command(service, users, 'driver', 'report_refund', 5)
    assert command(service, users, 'passenger', 'confirm_refund', 6)['payment']['status'] == 'refunded'


def test_legacy_demo_agreement_may_be_voided_without_renewed_collection(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        owner = tx.get('users', 'driver'); owner['development'] = True; tx.put('users', 'driver', owner)
        booking = tx.get('bookings', 'booking'); booking['status'] = 'cancelled'; tx.put('bookings', 'booking', booking)
    assert view(service, users)['upi_uri'] is None
    result = command(service, users, 'driver', 'void_unpaid', 2, reason='No transfer; cancelled old test agreement')['payment']
    assert result['status'] == 'voided_unpaid' and result['budget']['reserved_paise'] == 0


@pytest.mark.parametrize('saved_quote', [
    {'currency': 'INR', 'amount_paise': 0},
    {'currency': 'USD', 'amount_paise': 12345},
    {'currency': 'INR', 'amount_paise': True},
    {'currency': 'INR', 'amount_paise': '12345'},
    {'currency': 'INR'},
    'malformed',
])
def test_saved_booking_quote_must_match_proposal_atomically(setup, saved_quote):
    store, service, users = setup
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['price_quote'] = saved_quote
        tx.put('bookings', 'booking', booking)
    with pytest.raises(PaymentError) as error:
        propose(service, users)
    assert error.value.code == 'booking_price_mismatch'
    with store.read() as tx:
        assert not tx.list('payments')
        assert not tx.list('payment_events')
        assert not tx.list('payout_accounts')


def test_exact_saved_booking_quote_can_be_agreed_and_used(setup):
    store, service, users = setup
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['price_quote'] = {'currency': 'INR', 'amount_paise': 12345}
        tx.put('bookings', 'booking', booking)
    proposed = propose(service, users)['payment']
    assert proposed['amount_paise'] == 12345
    agreed = command(service, users, 'passenger', 'agree', 1)['payment']
    assert agreed['upi_uri'] and parse_qs(urlparse(agreed['upi_uri']).query)['am'] == ['123.45']


def test_legacy_proposal_rechecks_new_booking_quote_before_agreement(setup):
    store, service, users = setup
    propose(service, users)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['price_quote'] = {'currency': 'INR', 'amount_paise': 9999}
        tx.put('bookings', 'booking', booking)
    current = view(service, users)
    # A proposed quote has no transferable UPI target; agreement is the point
    # where a newly saved booking fare is rechecked.
    assert current['upi_uri'] is None and current['upi_id'] is None
    with pytest.raises(PaymentError) as error:
        command(service, users, 'passenger', 'agree', 1)
    assert error.value.code == 'booking_price_mismatch'
    assert view(service, users)['status'] == 'proposed'
    with store.read() as tx:
        assert len(tx.list('payment_events')) == 1


def test_legacy_agreement_price_mismatch_hides_target_but_allows_reconciliation(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['price_quote'] = {'currency': 'INR', 'amount_paise': 9999}
        tx.put('bookings', 'booking', booking)
    current = view(service, users)
    assert current['collection_eligibility']['reason'] == 'booking_price_mismatch'
    assert current['upi_uri'] is None and current['upi_id'] is None
    assert 'report_paid' in current['allowed_actions']
    command(service, users, 'passenger', 'report_paid', 2)
    assert 'confirm_received' in view(service, users, 'driver')['allowed_actions']
    command(service, users, 'driver', 'confirm_received', 3)
    assert view(service, users)['status'] == 'owner_confirmed'


def test_cancelled_booking_late_report_reconciles_refund_after_restart(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['status'] = 'cancelled'
        tx.put('bookings', 'booking', booking)
    current = view(service, users)
    assert current['upi_uri'] is None and current['upi_id'] is None
    assert 'report_paid' in current['allowed_actions']
    reported = command(service, users, 'passenger', 'report_paid', 2)['payment']
    assert reported['status'] == 'passenger_reported' and reported['upi_uri'] is None
    assert command(service, users, 'passenger', 'report_paid', 2)['replayed'] is True
    restarted = PaymentService(Store(store.path), enabled=True)
    assert view(restarted, users)['status'] == 'passenger_reported'
    command(restarted, users, 'driver', 'confirm_received', 3)
    command(restarted, users, 'passenger', 'request_refund', 4)
    command(restarted, users, 'driver', 'report_refund', 5)
    final = command(restarted, users, 'passenger', 'confirm_refund', 6)['payment']
    assert final['status'] == 'refunded' and final['upi_uri'] is None


def test_late_report_after_owner_void_restores_cap_without_reopening_collection(setup):
    store, service, users = setup
    propose(service, users)
    command(service, users, 'passenger', 'agree', 1)
    with store.transaction() as tx:
        booking = tx.get('bookings', 'booking')
        booking['status'] = 'cancelled'
        tx.put('bookings', 'booking', booking)
    voided = command(service, users, 'driver', 'void_unpaid', 2,
                     reason='Owner believes transfer was not made')['payment']
    assert voided['status'] == 'voided_unpaid' and voided['budget']['reserved_paise'] == 0
    assert voided['upi_uri'] is None and voided['upi_id'] is None
    assert 'report_paid' in view(service, users)['allowed_actions']
    budget(service, users, version=1, key='lower-cap-after-void', fuel_paise=12000,
           toll_paise=0, owner_share_paise=2000)
    restarted = PaymentService(Store(store.path), enabled=True)
    reported = command(restarted, users, 'passenger', 'report_paid', 3)['payment']
    assert reported['status'] == 'passenger_reported'
    assert reported['upi_uri'] is None and reported['upi_id'] is None
    assert reported['budget']['reserved_paise'] == 12345
    assert reported['budget']['remaining_paise'] == 0
    assert reported['collection_available'] is False
    assert reported['collection_eligibility']['reason'] == 'booking_ineligible'
    assert command(restarted, users, 'passenger', 'report_paid', 3)['replayed'] is True
    confirmed = command(restarted, users, 'driver', 'confirm_received', 4)['payment']
    assert confirmed['status'] == 'owner_confirmed' and confirmed['upi_uri'] is None
    assert confirmed['budget']['reserved_paise'] == 12345
