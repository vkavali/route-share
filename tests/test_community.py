from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app


PASSWORD = "correct-horse-battery"
ORIGIN_HEADERS = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True, "SECRET_KEY": "community-test-key", "BETA_PASSWORD": PASSWORD,
        "DATABASE_PATH": str(tmp_path / "community.sqlite3"),
    })
    store = application.extensions["beta_store"]
    now = datetime.now(timezone.utc)
    departure = now + timedelta(minutes=30)
    dropoff = now + timedelta(minutes=55)
    trip = {
        "id": "trip-community", "driver_id": "driver", "driver_name": "Development driver",
        "status": "started", "departure": departure.isoformat(), "seats": 3,
        "max_detour_minutes": 10, "detour_minutes": 0,
        "origin": {"label": "Origin", "lat": 17.0, "lon": 78.0},
        "destination": {"label": "Destination", "lat": 17.2, "lon": 78.2},
        "route": {"provider": "fixture", "duration_s": 1200,
                  "coordinates": [[78.0, 17.0], [78.1, 17.1], [78.2, 17.2]]},
        "current_route": {"provider": "fixture", "duration_s": 1200,
                          "coordinates": [[78.0, 17.0], [78.1, 17.1], [78.2, 17.2]]},
    }
    pickup = {"label": "Pickup", "lat": 17.1, "lon": 78.1}
    end = {"label": "Dropoff", "lat": 17.15, "lon": 78.15}
    booking = {
        "id": "booking-community", "trip_id": trip["id"], "request_id": "request-community",
        "driver_id": "driver", "passenger_id": "passenger", "driver_name": "Development driver",
        "passenger_name": "Development passenger", "status": "accepted", "seats": 1,
        "start_m": 1000, "end_m": 15000, "pickup": pickup, "dropoff": end,
        "match": {"pickup": pickup, "dropoff": end, "routed_pickup": pickup, "routed_dropoff": end,
                  "dropoff_at": dropoff.isoformat()},
        "accepted_at": now.isoformat(), "created_at": now.isoformat(),
    }
    with store.transaction() as tx:
        tx.put("trips", trip["id"], trip)
        tx.put("bookings", booking["id"], booking)
    return application


def login(client, account):
    token = client.get("/api/bootstrap").json["csrf_token"]
    result = client.post("/api/login", json={"account": account, "password": PASSWORD},
                         headers={**ORIGIN_HEADERS, "X-CSRF-Token": token})
    assert result.status_code == 200


def post(client, action, **payload):
    token = client.get("/api/bootstrap").json["csrf_token"]
    return client.post(f"/api/{action}", json=payload,
                       headers={**ORIGIN_HEADERS, "X-CSRF-Token": token})


def test_profile_update_normalizes_phone_and_preserves_identity_verification(app, tmp_path):
    client = app.test_client()
    login(client, "driver")
    initial = client.get("/api/profile").json["profile"]
    assert initial["phone"] == "" and initial["share_phone"] is False

    response = post(client, "update_profile", name="  Meera Rao  ", phone="98765 43210",
                    share_phone=True, verification={"phone": "verified", "identity": "verified"})
    assert response.status_code == 200
    assert response.json["profile"] == {
        "id": "driver", "name": "Meera Rao", "phone": "+919876543210", "share_phone": True,
        "verification": {"phone": "not_checked", "identity": "not_checked", "dl": "not_checked",
                          "rc": "not_checked", "selfie": "not_checked"},
    }
    assert response.json["user"]["name"] == "Meera Rao"
    assert post(client, "update_profile", name="Meera Rao", phone="12345", share_phone=True).status_code == 400
    assert post(client, "update_profile", name="Meera Rao", share_phone="true").status_code == 400

    restarted = create_app({"TESTING": True, "SECRET_KEY": "community-test-key", "BETA_PASSWORD": PASSWORD,
                            "DATABASE_PATH": app.extensions["beta_store"].path})
    after_restart = restarted.test_client()
    login(after_restart, "driver")
    persisted = after_restart.get("/api/profile").json["profile"]
    assert persisted["name"] == "Meera Rao" and persisted["phone"] == "+919876543210"


def test_public_summary_is_allowlisted_and_ops_redacts_phones(app):
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver.update(phone="+919876543210", share_phone=True)
        tx.put("users", "driver", driver)
        tx.put("ratings", "rating-real", {"id": "rating-real", "subject_id": "driver", "author_id": "passenger",
                                           "stars": 4, "comment": "safe persisted review"})
        tx.put("trips", "trip-done", {"id": "trip-done", "driver_id": "driver", "status": "completed",
                                       "departure": "2026-01-01T00:00:00+00:00", "seats": 1,
                                       "route": {"coordinates": [[78, 17], [78.1, 17.1]]},
                                       "origin": {"label": "a", "lat": 17, "lon": 78},
                                       "destination": {"label": "b", "lat": 17.1, "lon": 78.1}})
    passenger = app.test_client()
    login(passenger, "passenger")
    state = passenger.get("/api/state").json
    booking = next(row for row in state["bookings"] if row["id"] == "booking-community")
    summary = booking["counterpart_summary"]
    assert set(summary) == {"id", "name", "development", "verification", "rating_average", "rating_count", "completed_trip_count"}
    assert summary["rating_average"] is None and summary["rating_count"] == 1 and summary["completed_trip_count"] == 1
    assert "phone" not in summary and "+919876543210" not in str(state)

    admin = app.test_client()
    login(admin, "admin")
    ops_users = admin.get("/api/operations").json["users"]
    assert all("phone" not in row and "share_phone" not in row for row in ops_users)


def test_contact_requires_active_participant_consent_and_no_block(app):
    store = app.extensions["beta_store"]
    passenger, outsider, admin = (app.test_client() for _ in range(3))
    login(passenger, "passenger")
    login(outsider, "passenger2")
    login(admin, "admin")
    assert passenger.get("/api/contact?booking_id=booking-community").status_code == 403
    with store.transaction() as tx:
        driver = tx.get("users", "driver")
        driver.update(phone="+919876543210", share_phone=True)
        tx.put("users", "driver", driver)
    allowed = passenger.get("/api/contact?booking_id=booking-community")
    assert allowed.status_code == 200 and allowed.json["contact"] == {"name": "Development driver", "phone": "+919876543210"}
    assert post(passenger, "contact", booking_id="booking-community").json == allowed.json
    assert outsider.get("/api/contact?booking_id=booking-community").status_code == 403
    assert admin.get("/api/contact?booking_id=booking-community").status_code == 403

    with store.transaction() as tx:
        tx.put("blocks", "driver:passenger", {"id": "driver:passenger", "blocker_id": "driver", "blocked_id": "passenger"})
    assert passenger.get("/api/contact?booking_id=booking-community").status_code == 403


def test_chat_is_idempotent_private_unread_and_readable_but_not_sendable_after_completion(app):
    store = app.extensions["beta_store"]
    passenger, driver, outsider = (app.test_client() for _ in range(3))
    login(passenger, "passenger")
    login(driver, "driver")
    login(outsider, "passenger2")
    sent = post(passenger, "send_message", booking_id="booking-community", text="  I am at the pickup point.  ",
                client_message_id="local-msg-1")
    assert sent.status_code == 200
    message = sent.json["message"]
    assert message["text"] == "I am at the pickup point."
    assert post(passenger, "send_message", booking_id="booking-community", text="I am at the pickup point.",
                client_message_id="local-msg-1").json["message"] == message
    assert post(passenger, "send_message", booking_id="booking-community", text="Different payload",
                client_message_id="local-msg-1").status_code == 409

    conversation = driver.get("/api/chat?booking_id=booking-community")
    assert conversation.status_code == 200
    assert conversation.json["send_allowed"] is True and conversation.json["can_send"] is True
    assert len(conversation.json["messages"]) == 1
    assert "recipient_id" not in conversation.json["messages"][0]
    assert outsider.get("/api/chat?booking_id=booking-community").status_code == 403
    chats = driver.get("/api/chats").json["chats"]
    assert chats[0]["latest_message"]["text"] == "I am at the pickup point."
    assert chats[0]["unread_count"] == 1
    state = driver.get("/api/state").json
    assert state["chat_unread_count"] == 1 and state["notification_unread_count"] == 1
    notes = driver.get("/api/notifications").json["notifications"]
    chat_note = next(row for row in notes if row["type"] == "chat_message")
    assert "text" not in chat_note and chat_note["message_id"] == message["id"]
    with store.read() as tx:
        assert all(message["text"] not in str(event) for event in tx.list("events"))

    marked = post(driver, "mark_chat_read", booking_id="booking-community", upto_message_id=message["id"])
    assert marked.status_code == 200
    read_at = driver.get("/api/chat?booking_id=booking-community").json["messages"][0]["read_at"]
    assert read_at == marked.json["read_at"]
    post(driver, "mark_chat_read", booking_id="booking-community", upto_message_id=message["id"])
    assert driver.get("/api/chat?booking_id=booking-community").json["messages"][0]["read_at"] == read_at
    note_id = chat_note["id"]
    note_read = post(driver, "mark_notification_read", notification_id=note_id)
    assert note_read.status_code == 200 and note_read.json["notification"]["read_at"]
    assert post(passenger, "mark_notification_read", notification_id=note_id).status_code == 404
    assert driver.get("/api/state").json["chat_unread_count"] == 0

    with store.transaction() as tx:
        trip = tx.get("trips", "trip-community")
        trip["status"] = "completed"
        tx.put("trips", trip["id"], trip)
        booking = tx.get("bookings", "booking-community")
        booking["status"] = "segment_completed"
        tx.put("bookings", booking["id"], booking)
    completed_chat = driver.get("/api/chat?booking_id=booking-community").json
    assert completed_chat["send_allowed"] is False and completed_chat["can_send"] is False
    assert completed_chat["messages"][0]["text"] == "I am at the pickup point."
    assert post(driver, "send_message", booking_id="booking-community", text="too late", client_message_id="late").status_code == 409
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        tx.put("blocks", "driver:passenger", {"id": "driver:passenger", "blocker_id": "driver", "blocked_id": "passenger"})
    assert driver.get("/api/chat?booking_id=booking-community").status_code == 403


def test_contact_and_send_are_denied_after_scheduled_dropoff(app):
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        trip = tx.get("trips", "trip-community")
        trip["status"] = "published"
        tx.put("trips", trip["id"], trip)
        booking = tx.get("bookings", "booking-community")
        booking["match"]["dropoff_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        tx.put("bookings", booking["id"], booking)
        driver = tx.get("users", "driver")
        driver.update(phone="+919876543210", share_phone=True)
        tx.put("users", "driver", driver)
    client = app.test_client()
    login(client, "passenger")
    chat = client.get("/api/chat?booking_id=booking-community")
    assert chat.status_code == 200 and chat.json["send_allowed"] is False
    assert client.get("/api/contact?booking_id=booking-community").status_code == 409
    assert post(client, "send_message", booking_id="booking-community", text="expired", client_message_id="expired").status_code == 409


@pytest.mark.parametrize("reason", ["arrival", "blocked"])
def test_contact_and_chat_close_when_live_sharing_ends(reason, app):
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        booking = tx.get("bookings", "booking-community")
        booking["live_location_ended_reason"] = reason
        booking["live_location_ended_at"] = datetime.now(timezone.utc).isoformat()
        tx.put("bookings", booking["id"], booking)
        driver = tx.get("users", "driver")
        driver.update(phone="+919876543210", share_phone=True)
        tx.put("users", "driver", driver)

    passenger = app.test_client()
    login(passenger, "passenger")
    assert passenger.get("/api/contact?booking_id=booking-community").status_code == 409
    chat = passenger.get("/api/chat?booking_id=booking-community")
    assert chat.status_code == 200 and chat.json["send_allowed"] is False
    sent = post(passenger, "send_message", booking_id="booking-community", text="arrived", client_message_id="after-end")
    assert sent.status_code == 409


def test_state_includes_committed_route_for_segment_completed_booking(app):
    store = app.extensions["beta_store"]
    with store.transaction() as tx:
        booking = tx.get("bookings", "booking-community")
        booking["status"] = "segment_completed"
        booking["match"]["routed_pickup"] = {"lat": 17.0, "lon": 78.0}
        booking["match"]["routed_dropoff"] = {"lat": 17.2, "lon": 78.2}
        tx.put("bookings", booking["id"], booking)
        trip = tx.get("trips", "trip-community")
        trip["status"] = "completed"
        tx.put("trips", trip["id"], trip)

    passenger = app.test_client()
    login(passenger, "passenger")
    state = passenger.get("/api/state")
    assert state.status_code == 200
    booking = next(row for row in state.json["bookings"] if row["id"] == "booking-community")
    assert booking["route"]["coordinates"] == [[78.0, 17.0], [78.1, 17.1], [78.2, 17.2]]


def test_expected_user_header_blocks_stale_tab_profile_and_chat_mutations(app):
    client = app.test_client()
    login(client, "driver")
    login(client, "passenger")
    token = client.get("/api/bootstrap").json["csrf_token"]
    stale_headers = {**ORIGIN_HEADERS, "X-CSRF-Token": token, "X-Expected-User-ID": "driver"}
    profile = client.post("/api/update_profile", json={"name": "Wrong account", "share_phone": False},
                          headers=stale_headers)
    assert profile.status_code == 409 and profile.json["code"] == "account_changed"
    message = client.post("/api/send_message", json={"booking_id": "booking-community", "text": "stale", "client_message_id": "stale"},
                          headers=stale_headers)
    assert message.status_code == 409 and message.json["code"] == "account_changed"
    with app.extensions["beta_store"].read() as tx:
        assert tx.list("messages") == []
        assert tx.get("users", "passenger")["name"] == "Development passenger"


def test_chat_rate_limited_per_account_and_lifecycle_notifications_are_transactional(app):
    client = app.test_client()
    login(client, "passenger")
    for index in range(20):
        result = post(client, "send_message", booking_id="booking-community", text=f"message {index}",
                      client_message_id=f"msg-{index}")
        assert result.status_code == 200
    limited = post(client, "send_message", booking_id="booking-community", text="too many", client_message_id="msg-over-limit")
    assert limited.status_code == 429 and limited.json["code"] == "rate_limited"

    service = app.extensions["beta_service"]
    store = app.extensions["beta_store"]
    actor = {"id": "passenger", "name": "Development passenger"}
    with store.read() as tx:
        notification_count_before = len(tx.list("notifications"))
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            service._event(tx, actor, "seat_requested", "booking-community")
            raise RuntimeError("rollback test")
    with store.read() as tx:
        assert len(tx.list("notifications")) == notification_count_before
    with store.transaction() as tx:
        service._event(tx, actor, "seat_requested", "booking-community")
    notifications = app.test_client()
    login(notifications, "driver")
    result = notifications.get("/api/notifications").json["notifications"]
    assert sum(row["type"] == "ride_request" for row in result) == 1
