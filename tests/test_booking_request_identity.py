"""Booking request retries preserve request identity and immutable terms."""
from concurrent.futures import ThreadPoolExecutor
import secrets

import pytest

from app import create_app
from app.auth import issue_web_session_in
from app.domain import DomainError
from test_lifecycle import (
    NANDIGAMA,
    SURYAPET,
    VIJAYAWADA,
    act,
    future_departure,
    make_service,
    FixtureRoadProvider,
)
from test_ride_options import _bags, _publish, _search


def _match(service, passenger, departure, origin, destination, bags):
    result = _search(service, passenger, departure, origin=origin,
                     destination=destination, bags=bags)
    assert result["matches"], "fixture route should produce a route-aware match"
    return result, result["matches"][0]


def test_same_request_retry_returns_original_booking_and_quote(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure,
                       capacity=_bags(2, 1), price=12_500)
    result, original_match = _match(service, users["passenger"], departure,
                                    SURYAPET, NANDIGAMA, _bags(1, 0))
    booking = act(service, "request", users["passenger"],
                  match_id=original_match["id"])["booking"]

    replay = act(service, "request", users["passenger"],
                 match_id=original_match["id"])["booking"]

    assert replay["id"] == booking["id"]
    assert replay["request_id"] == result["request"]["id"]
    assert replay["price_quote"] == booking["price_quote"]
    assert replay["pickup"] == booking["pickup"]
    assert replay["baggage"] == _bags(1, 0)
    with store.read() as tx:
        assert len([row for row in tx.list("bookings") if row["trip_id"] == trip["id"]]) == 1


@pytest.mark.parametrize("existing_status", ["pending", "accepted"])
def test_new_search_for_different_segment_or_bags_conflicts_with_active_booking(tmp_path, existing_status):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure,
                       capacity=_bags(2, 1), price=12_500)
    _, first_match = _match(service, users["passenger"], departure,
                            SURYAPET, NANDIGAMA, _bags(1, 0))
    original = act(service, "request", users["passenger"],
                    match_id=first_match["id"])["booking"]
    if existing_status == "accepted":
        original = act(service, "accept", users["driver"], booking_id=original["id"])["booking"]
    _, changed_match = _match(service, users["passenger"], departure,
                              NANDIGAMA, VIJAYAWADA, _bags(0, 1))

    with pytest.raises(DomainError) as conflict:
        act(service, "request", users["passenger"], match_id=changed_match["id"])

    assert conflict.value.status == 409
    assert conflict.value.code == "booking_already_exists"
    assert "review or cancel" in str(conflict.value).lower()
    with store.read() as tx:
        saved = [row for row in tx.list("bookings") if row["trip_id"] == trip["id"]]
    assert len(saved) == 1
    assert saved[0]["id"] == original["id"]
    assert saved[0]["status"] == existing_status
    assert saved[0]["request_id"] == original["request_id"]
    assert saved[0]["price_quote"] == original["price_quote"]
    assert saved[0]["pickup"] == SURYAPET
    assert saved[0]["dropoff"] == NANDIGAMA
    assert saved[0]["baggage"] == _bags(1, 0)


def test_original_retry_after_cancel_stays_terminal_and_new_search_can_book(tmp_path):
    service, _, users, _ = make_service(tmp_path)
    departure = future_departure()
    _publish(service, users["driver"], departure=departure,
             capacity=_bags(2, 1), price=12_500)
    first_search, first_match = _match(service, users["passenger"], departure,
                                       SURYAPET, NANDIGAMA, _bags(1, 0))
    original = act(service, "request", users["passenger"],
                    match_id=first_match["id"])["booking"]
    cancelled = act(service, "cancel_booking", users["passenger"],
                    booking_id=original["id"], reason="Changed plans")["booking"]
    assert cancelled["status"] == "cancelled"

    replay = act(service, "request", users["passenger"],
                 match_id=first_match["id"])["booking"]
    assert replay["id"] == original["id"]
    assert replay["request_id"] == first_search["request"]["id"]
    assert replay["status"] == "cancelled"
    assert replay["price_quote"] == original["price_quote"]

    _, fresh_match = _match(service, users["passenger"], departure,
                            NANDIGAMA, VIJAYAWADA, _bags(0, 1))
    fresh = act(service, "request", users["passenger"],
                match_id=fresh_match["id"])["booking"]
    assert fresh["id"] != original["id"]
    assert fresh["request_id"] != original["request_id"]
    assert fresh["status"] == "pending"
    assert fresh["baggage"] == _bags(0, 1)


def test_concurrent_same_match_request_retry_creates_one_booking(tmp_path):
    service, store, users, _ = make_service(tmp_path)
    departure = future_departure()
    _, trip = _publish(service, users["driver"], departure=departure,
                       capacity=_bags(2, 1), price=12_500)
    _, match = _match(service, users["passenger"], departure,
                      SURYAPET, NANDIGAMA, _bags(1, 0))

    def request():
        return act(service, "request", users["passenger"], match_id=match["id"])["booking"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in
                   [pool.submit(request), pool.submit(request)]]

    assert len({row["id"] for row in results}) == 1
    with store.read() as tx:
        rows = [row for row in tx.list("bookings") if row["trip_id"] == trip["id"]]
    assert len(rows) == 1


def test_api_request_conflict_includes_booking_already_exists_code(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "booking-request-test",
                      "DATABASE_PATH": str(tmp_path / "http.sqlite3"),
                      "PHONE_AUTH_ENABLED": False, "VOICE_ENABLED": False})
    service = app.extensions["beta_service"]
    service.router = FixtureRoadProvider()
    _base_service, _base_store, users, _ = make_service(tmp_path / "fixtures")
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        for user in users.values():
            tx.put("users", user["id"], user)

    departure = future_departure()
    _publish(service, users["driver"], departure=departure,
             capacity=_bags(2, 1), price=12_500)
    _, first_match = _match(service, users["passenger"], departure,
                            SURYAPET, NANDIGAMA, _bags(1, 0))
    act(service, "request", users["passenger"], match_id=first_match["id"])
    _, changed_match = _match(service, users["passenger"], departure,
                              NANDIGAMA, VIJAYAWADA, _bags(0, 1))

    session_id = secrets.token_urlsafe(32)
    with store.transaction() as tx:
        issue_web_session_in(tx, users["passenger"], session_id)
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(account="passenger", auth_epoch=0, auth_session_id=session_id,
                       csrf_token="csrf-booking-request")
    response = client.post("/api/request", json={"match_id": changed_match["id"]}, headers={
        "Origin": "http://localhost", "X-CSRF-Token": "csrf-booking-request",
        "X-Expected-User-ID": "passenger",
    })

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "You already have a request for this trip. Review or cancel it before requesting a different segment.",
        "code": "booking_already_exists",
    }
