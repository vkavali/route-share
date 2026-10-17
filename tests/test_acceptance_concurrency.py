"""Concurrency regressions for route-aware booking acceptance.

The road provider is deliberately controlled with barriers and events so these
tests exercise stale snapshots and lock ownership without live network access.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local

import pytest

from app.domain import DomainError
from app.routing import RoutingError
from test_lifecycle import (
    FixtureRoadProvider,
    KONDAPUR,
    NANDIGAMA,
    SURYAPET,
    VIJAYAWADA,
    act,
    booking_for,
    future_departure,
    make_service,
    publish,
)


class ControlledRoadProvider(FixtureRoadProvider):
    """Block or synchronize the first acceptance route per worker thread."""

    def __init__(self):
        super().__init__()
        self.armed = False
        self.entered = Event()
        self.release = Event()
        self.barrier = None
        self.fail_when_armed = False
        self._thread_state = local()

    def route(self, points):
        if self.armed and not getattr(self._thread_state, "entered_gate", False):
            self._thread_state.entered_gate = True
            self.entered.set()
            if self.barrier is not None:
                self.barrier.wait(timeout=10)
            elif not self.release.wait(timeout=10):
                raise AssertionError("test did not release the controlled route")
            if self.fail_when_armed:
                raise RoutingError("FIXTURE ROUTING FAILURE - acceptance must not commit")
        return super().route(points)


def _pending_pair(service, users, *, seats=1, second_passenger=None):
    departure = future_departure()
    _, trip = publish(service, users["driver"], KONDAPUR, VIJAYAWADA,
                      departure, seats=seats)
    _, first = booking_for(service, users["passenger"], SURYAPET,
                           NANDIGAMA, departure)
    if second_passenger is None:
        second_passenger = "passenger2"
    _, second = booking_for(service, users[second_passenger], SURYAPET,
                            NANDIGAMA, departure)
    return trip, first, second


def _run_accept(service, driver, booking_id):
    try:
        return act(service, "accept", driver, booking_id=booking_id)["booking"]
    except DomainError as exc:
        return exc.status


def _read_acceptance_state(store, booking_ids, trip_id):
    with store.read() as tx:
        bookings = {booking_id: tx.get("bookings", booking_id)
                    for booking_id in booking_ids}
        trip = tx.get("trips", trip_id)
        events = [row for row in tx.list("events")
                  if row.get("kind") == "seat_accepted"
                  and row.get("object_id") in booking_ids]
        route_logs = [row for row in tx.list("route_calculations")
                      if row.get("reason") == "acceptance_recheck"
                      and row.get("object_id") in booking_ids]
    return bookings, trip, events, route_logs


def test_slow_acceptance_routing_does_not_hold_store_writer_lock(tmp_path):
    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    trip, booking, _ = _pending_pair(service, users)
    router.armed = True

    with ThreadPoolExecutor(max_workers=2) as pool:
        accept_future = pool.submit(_run_accept, service, users["driver"], booking["id"])
        assert router.entered.wait(timeout=5), "acceptance never reached the route provider"
        writer_finished = Event()

        def unrelated_write():
            with store.transaction() as tx:
                tx.put("concurrency_probe", "writer", {"id": "writer", "ok": True})
            writer_finished.set()

        writer_future = pool.submit(unrelated_write)
        try:
            # The route remains blocked. The independent SQLite writer must still
            # finish; event synchronization avoids relying on a sleep or live OSRM.
            writer_completed_while_route_blocked = writer_finished.wait(timeout=5)
        finally:
            router.release.set()
        writer_future.result(timeout=5)
        assert accept_future.result(timeout=10)["status"] == "accepted"

    assert writer_completed_while_route_blocked
    with store.read() as tx:
        assert tx.get("concurrency_probe", "writer")["ok"] is True


@pytest.mark.parametrize("change", ["actor_revoked", "pair_blocked", "trip_cancelled"])
def test_acceptance_rechecks_live_eligibility_after_routing(tmp_path, change):
    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    trip, booking, _ = _pending_pair(service, users)
    router.armed = True

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_accept, service, users["driver"], booking["id"])
        assert router.entered.wait(timeout=5), "acceptance never reached the route provider"
        if change == "actor_revoked":
            with store.transaction() as tx:
                driver = tx.get("users", users["driver"]["id"])
                driver["account_status"] = "suspended"
                tx.put("users", driver["id"], driver)
        elif change == "pair_blocked":
            act(service, "block_person", users["passenger"], booking_id=booking["id"])
        else:
            act(service, "cancel_trip", users["driver"], trip_id=trip["id"],
                reason="Fixture cancellation during route calculation")
        router.release.set()
        result = future.result(timeout=10)

    assert isinstance(result, int) and result in (401, 409)
    bookings, current_trip, events, route_logs = _read_acceptance_state(
        store, [booking["id"]], trip["id"])
    assert bookings[booking["id"]]["status"] != "accepted"
    assert not events
    assert not route_logs
    if change == "pair_blocked":
        assert bookings[booking["id"]]["status"] == "cancelled"
    if change == "trip_cancelled":
        assert current_trip["status"] == "cancelled"


@pytest.mark.parametrize("seats,expected", [(1, [409, "accepted"]), (2, ["accepted", "accepted"])])
def test_concurrent_overlapping_accepts_revalidate_capacity(tmp_path, seats, expected):
    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    trip, first, second = _pending_pair(service, users, seats=seats)
    router.armed = True
    router.barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_accept, service, users["driver"], booking["id"])
                   for booking in (first, second)]
        results = [future.result(timeout=15) for future in futures]

    statuses = [result if isinstance(result, int) else result["status"] for result in results]
    assert sorted(statuses, key=str) == sorted(expected, key=str)
    bookings, _, events, _ = _read_acceptance_state(
        store, [first["id"], second["id"]], trip["id"])
    accepted = [row for row in bookings.values() if row["status"] == "accepted"]
    assert len(accepted) == seats
    assert len(events) == seats


def test_same_booking_accept_race_is_idempotent_and_emits_one_event(tmp_path):
    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    trip, booking, _ = _pending_pair(service, users)
    router.armed = True
    router.barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_accept, service, users["driver"], booking["id"])
                   for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert all(not isinstance(result, int) for result in results)
    assert {result["id"] for result in results} == {booking["id"]}
    assert all(result["status"] == "accepted" for result in results)
    bookings, _, events, route_logs = _read_acceptance_state(
        store, [booking["id"]], trip["id"])
    assert bookings[booking["id"]]["status"] == "accepted"
    assert len(events) == 1
    assert len(route_logs) == 1


def test_acceptance_routing_failure_leaves_no_acceptance_writes(tmp_path):
    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    trip, booking, _ = _pending_pair(service, users)
    before_bookings, before_trip, before_events, before_logs = _read_acceptance_state(
        store, [booking["id"]], trip["id"])
    router.fail_when_armed = True
    router.armed = True

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_accept, service, users["driver"], booking["id"])
        assert router.entered.wait(timeout=5), "acceptance never reached the route provider"
        router.release.set()
        result = future.result(timeout=10)

    assert result == 503
    after_bookings, after_trip, after_events, after_logs = _read_acceptance_state(
        store, [booking["id"]], trip["id"])
    assert after_bookings[booking["id"]]["status"] == before_bookings[booking["id"]]["status"] == "pending"
    assert after_trip == before_trip
    assert after_events == before_events == []
    assert after_logs == before_logs == []


@pytest.mark.parametrize("change", ["baggage_capacity", "seat_price_paise"])
def test_changed_offer_during_acceptance_cannot_commit_old_baggage_or_fare(tmp_path, change):
    from test_ride_options import _bags, _publish, _search, _request

    router = ControlledRoadProvider()
    service, store, users, _ = make_service(tmp_path, router)
    _, trip = _publish(service, users["driver"], capacity=_bags(1), price=10_000)
    match = _search(service, users["passenger"], trip["departure"], bags=_bags(1))["matches"][0]
    booking = _request(service, users["passenger"], match)
    router.armed = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_accept, service, users["driver"], booking["id"])
        try:
            assert router.entered.wait(timeout=5)
            with store.transaction() as tx:
                current = tx.get("trips", trip["id"])
                # Even an older writer that misses the version increment must
                # not make the calculated offer authoritative after a change.
                current[change] = _bags(0) if change == "baggage_capacity" else 20_000
                tx.put("trips", current["id"], current)
        finally:
            router.release.set()
        assert future.result(timeout=10) == 409
    bookings, _, events, route_logs = _read_acceptance_state(store, [booking["id"]], trip["id"])
    assert bookings[booking["id"]]["status"] == "pending"
    assert bookings[booking["id"]]["price_quote"] == booking["price_quote"]
    assert not events and not route_logs
