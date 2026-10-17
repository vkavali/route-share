"""Search behavior when request-scoped routing limits are reached."""

import copy

import app.domain as domain
from app.routing import routing_budget
from test_lifecycle import (
    KONDAPUR,
    NANDIGAMA,
    SURYAPET,
    FixtureRoadProvider,
    future_departure,
    make_service,
    publish,
    search,
)


class BudgetAwareFixtureRouter(FixtureRoadProvider):
    """Deterministic local router that accounts for each simulated upstream call."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def route(self, points):
        # Match OSRMProvider's accounting without making any network requests.
        from app.routing import routing_checkpoint

        routing_checkpoint(consume_call=True)
        self.calls += 1
        return super().route(points)


def _add_trip_copies(store, trip, count):
    with store.transaction() as tx:
        for index in range(count):
            copied = copy.deepcopy(trip)
            copied["id"] = f"fixture-copy-{index:03d}"
            tx.put("trips", copied["id"], copied)


def _search_request(service, passenger, departure):
    return search(service, passenger, SURYAPET, NANDIGAMA, departure)


def _event_for(store, request_id):
    with store.read() as tx:
        return next(
            event for event in tx.list("events")
            if event.get("kind") in {"search_completed", "search_incomplete"}
            and event.get("object_id") == request_id
        )


def test_budget_exhaustion_preserves_matches_found_before_exhaustion(tmp_path, monkeypatch):
    router = BudgetAwareFixtureRouter()
    service, store, users, _ = make_service(tmp_path, router)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, NANDIGAMA, departure)
    _add_trip_copies(store, trip, 2)
    router.calls = 0
    monkeypatch.setattr(domain, "routing_budget", lambda: routing_budget(seconds=10, max_calls=3))

    result = _search_request(service, users["passenger"], departure)

    assert len(result["matches"]) == 1
    assert result["metrics"]["complete"] is False
    assert result["metrics"]["evaluation_errors"] == 1
    assert router.calls == 3
    with store.read() as tx:
        saved = tx.get("requests", result["request"]["id"])
        saved_matches = [m for m in tx.list("matches") if m["request_id"] == saved["id"]]
    assert saved["metrics"]["complete"] is False
    assert len(saved_matches) == 1
    event = _event_for(store, saved["id"])
    assert event["kind"] == "search_incomplete"
    assert event["details"]["errors"][0]["code"] == "search_budget_exceeded"


def test_exhaustion_before_first_match_is_persisted_as_incomplete(tmp_path, monkeypatch):
    router = BudgetAwareFixtureRouter()
    service, store, users, _ = make_service(tmp_path, router)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, NANDIGAMA, departure)
    router.calls = 0
    monkeypatch.setattr(domain, "routing_budget", lambda: routing_budget(seconds=10, max_calls=0))

    result = _search_request(service, users["passenger"], departure)

    assert result["matches"] == []
    assert result["metrics"]["complete"] is False
    assert result["metrics"]["evaluation_errors"] == 1
    assert router.calls == 0
    with store.read() as tx:
        saved = tx.get("requests", result["request"]["id"])
    assert saved["metrics"]["complete"] is False
    assert _event_for(store, saved["id"])["kind"] == "search_incomplete"


def test_search_attempt_cap_marks_partial_results_incomplete(tmp_path, monkeypatch):
    router = BudgetAwareFixtureRouter()
    service, store, users, _ = make_service(tmp_path, router)
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, NANDIGAMA, departure)
    _add_trip_copies(store, trip, 100)
    router.calls = 0
    # Keep the call budget above the 100-candidate guard so this tests the
    # search cap independently of time/upstream-call exhaustion.
    monkeypatch.setattr(domain, "routing_budget", lambda: routing_budget(seconds=30, max_calls=500))

    result = _search_request(service, users["passenger"], departure)

    assert len(result["matches"]) == 100
    assert result["metrics"]["complete"] is False
    assert result["metrics"]["evaluation_errors"] == 1
    assert router.calls == 200
    with store.read() as tx:
        saved = tx.get("requests", result["request"]["id"])
        saved_matches = [m for m in tx.list("matches") if m["request_id"] == saved["id"]]
    assert saved["metrics"]["complete"] is False
    assert len(saved_matches) == 100
    assert _event_for(store, saved["id"])["kind"] == "search_incomplete"


def test_fast_search_still_completes_normally(tmp_path):
    router = BudgetAwareFixtureRouter()
    service, store, users, _ = make_service(tmp_path, router)
    departure = future_departure()
    publish(service, users["driver"], KONDAPUR, NANDIGAMA, departure)
    router.calls = 0

    result = _search_request(service, users["passenger"], departure)

    assert len(result["matches"]) == 1
    assert result["metrics"]["complete"] is True
    assert result["metrics"]["evaluation_errors"] == 0
    assert router.calls == 2
    assert _event_for(store, result["request"]["id"])["kind"] == "search_completed"
