"""Isolated Flask + SQLite fixture for the browser ride journey.

The named accounts, road estimates, and password are synthetic development
fixtures. This process never uses OTP, payments, external routing, or production.
"""
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server
from app import create_app

logging.getLogger("werkzeug").setLevel(logging.ERROR)


class FixtureRouter:
    name = "FIXTURE ONLY - synthetic route estimate; no road or traffic claim"

    def route(self, points):
        coordinates = [[point["lon"], point["lat"]] for point in points]
        distance = sum(
            ((points[i + 1]["lat"] - points[i]["lat"]) ** 2
             + (points[i + 1]["lon"] - points[i]["lon"]) ** 2) ** 0.5 * 111_000
            for i in range(len(points) - 1)
        )
        leg_distances = [
            ((points[i + 1]["lat"] - points[i]["lat"]) ** 2
             + (points[i + 1]["lon"] - points[i]["lon"]) ** 2) ** 0.5 * 111_000
            for i in range(len(points) - 1)
        ]
        return {
            "coordinates": coordinates,
            "distance_m": distance,
            "duration_s": distance / 15,
            "leg_durations_s": [distance / max(1, len(points) - 1) / 15] * (len(points) - 1),
            "leg_distances_m": leg_distances,
            "waypoints": [{"distance": 0, "location": coordinate} for coordinate in coordinates],
            "provider": self.name,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "calculation_id": "fixture-" + uuid.uuid4().hex,
            "traffic": False,
        }


temporary = tempfile.TemporaryDirectory(prefix="seatpal-ride-live-")
app = create_app({
    "TESTING": True,
    "HOSTED_MODE": False,
    "DEMO_PASSWORD_ENABLED": True,
    "BETA_PASSWORD": "local-ui-fixture-only",
    "SECRET_KEY": "isolated-ride-browser-test-secret",
    "SECRET_PATH": os.path.join(temporary.name, "secret"),
    "DATABASE_PATH": os.path.join(temporary.name, "journey.sqlite3"),
})
app.extensions["beta_service"].router = FixtureRouter()
with app.extensions["beta_store"].transaction() as tx:
    driver = tx.get("users", "driver")
    driver["vehicle"] = {"model": "Synthetic fixture car", "plate": "TEST-ONLY"}
    tx.put("users", "driver", driver)

server = make_server("127.0.0.1", 0, app, threaded=True)
print(json.dumps({"port": server.server_port, "password": "local-ui-fixture-only"}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    temporary.cleanup()
