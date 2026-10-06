#!/usr/bin/env python3
"""Run bounded live OSRM + Service/Store development evidence.

All records are written to work/live-validation.sqlite3, never the app DB.
The initial specified points are attempted and recorded before any alternate.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain import Service, DomainError, IST  # noqa: E402
from app.store import Store  # noqa: E402
from app.routing import OSRMProvider  # noqa: E402

DB = ROOT / "work" / "live-validation.sqlite3"
OUT = ROOT / "work" / "live-evidence.json"
ACTORS = {
    "driver": {"id": "live-dev-driver", "name": "Live test driver", "role": "member", "phone": "", "vehicle": {"model": "Test vehicle", "plate": "DEV-001"}, "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")}, "development": True},
    "passenger": {"id": "live-dev-passenger", "name": "Live test passenger", "role": "member", "phone": "", "vehicle": {}, "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")}, "development": True},
    "passenger2": {"id": "live-dev-passenger2", "name": "Live test passenger 2", "role": "member", "phone": "", "vehicle": {}, "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")}, "development": True},
    "admin": {"id": "live-dev-admin", "name": "Live test admin", "role": "admin", "phone": "", "vehicle": {}, "verification": {k: "not_checked" for k in ("phone", "identity", "dl", "rc", "selfie")}, "development": True},
}

EAST = {
    "driver_origin": {"label": "Kondapur", "lat": 17.460, "lon": 78.357},
    "driver_destination": {"label": "Vijayawada", "lat": 16.506, "lon": 80.648},
    "pickup": {"label": "LB Nagar", "lat": 17.3457, "lon": 78.5522},
    "dropoff": {"label": "Suryapet", "lat": 17.139, "lon": 79.620},
}
SOUTH = {
    "driver_origin": {"label": "Hyderabad east pilot / Kondapur", "lat": 17.460, "lon": 78.357},
    "driver_destination": {"label": "Wanaparthy", "lat": 16.362, "lon": 78.062},
    "pickup": {"label": "Shadnagar", "lat": 17.071, "lon": 78.209},
    "dropoff": {"label": "Kothakota", "lat": 16.374, "lon": 77.971},
}

def save(evidence):
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def iso(dt):
    return dt.astimezone(IST).isoformat(timespec="seconds")

def compact_route(route):
    return {k: route.get(k) for k in ("provider", "distance_m", "duration_s", "traffic", "snap_limit_m", "calculated_at", "calculation_id")} | {"geometry_coordinate_count": len(route.get("coordinates", []))}

class Runner:
    def __init__(self, evidence):
        self.evidence = evidence
        self.store = Store(DB)
        self.router = OSRMProvider(self.store, timeout=20)
        self.service = Service(self.store, self.router)
        with self.store.transaction() as tx:
            for key, actor in ACTORS.items():
                tx.put("users", actor["id"], actor)
        self.evidence["database"] = str(DB)
        self.evidence["actors"] = {k: {"id": v["id"], "role": v["role"], "development": v["development"]} for k, v in ACTORS.items()}

    def call(self, action, actor, payload):
        try:
            return {"ok": True, "value": self.service.dispatch(action, ACTORS[actor], payload)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "error_type": type(exc).__name__, "status": getattr(exc, "status", None)}

    def run_corridor(self, name, points, departure):
        out = {"specified_points": points, "steps": {}}
        self.evidence["corridors"][name] = out
        save(self.evidence)
        preview = self.call("preview", "driver", {"origin": points["driver_origin"], "destination": points["driver_destination"], "departure": iso(departure), "seats": 1, "max_detour_minutes": 10})
        out["steps"]["preview"] = {"ok": preview["ok"], **({"error": preview["error"], "error_type": preview["error_type"]} if not preview["ok"] else {"route": compact_route(preview["value"]["preview"]["route"]), "preview_id": preview["value"]["preview"]["id"]})}
        save(self.evidence)
        if not preview["ok"]:
            return out
        p = preview["value"]["preview"]
        published = self.call("publish", "driver", {"preview_id": p["id"]})
        out["steps"]["publish"] = {"ok": published["ok"], **({"error": published["error"]} if not published["ok"] else {"trip_id": published["value"]["trip"]["id"], "trip_status": published["value"]["trip"]["status"]})}
        save(self.evidence)
        if not published["ok"]:
            return out
        trip = published["value"]["trip"]
        window = {"window_start": iso(departure - timedelta(minutes=1)), "window_end": iso(departure + timedelta(hours=8)), "seats": 1}
        searched = self.call("search", "passenger", {"origin": points["pickup"], "destination": points["dropoff"], **window})
        if not searched["ok"]:
            out["steps"]["search"] = {"ok": False, "error": searched["error"], "error_type": searched["error_type"]}
            save(self.evidence)
            return out
        result = searched["value"]
        matches = [m for m in result["matches"] if m["trip_id"] == trip["id"]]
        out["steps"]["search"] = {"ok": True, "request_id": result["request"]["id"], "metrics": result["metrics"], "trip_match_count": len(matches), "matches": [{"id": m["id"], "trip_id": m["trip_id"], "pickup_detour_minutes": m["pickup_detour_minutes"], "dropoff_detour_minutes": m["dropoff_detour_minutes"], "incremental_detour_minutes": m["incremental_detour_minutes"], "total_driver_detour_minutes": m["total_driver_detour_minutes"], "pickup_at": m["pickup_at"], "dropoff_at": m["dropoff_at"], "start_m": round(m["start_m"], 1), "end_m": round(m["end_m"], 1), "available_seats": m["available_seats"], "baseline_match": m["baseline_match"], "route_provider": m["route_provider"]} for m in matches]}
        save(self.evidence)
        if not matches:
            return out
        match = matches[0]
        requested = self.call("request", "passenger", {"match_id": match["id"]})
        out["steps"]["request"] = {"ok": requested["ok"], **({"error": requested["error"]} if not requested["ok"] else {"booking_id": requested["value"]["booking"]["id"], "status": requested["value"]["booking"]["status"]})}
        save(self.evidence)
        if not requested["ok"]:
            return out
        booking_id = requested["value"]["booking"]["id"]
        accepted = self.call("accept", "driver", {"booking_id": booking_id})
        out["steps"]["accept"] = {"ok": accepted["ok"], **({"error": accepted["error"]} if not accepted["ok"] else {"status": accepted["value"]["booking"]["status"], "total_driver_detour_minutes": accepted["value"]["booking"]["match"]["total_driver_detour_minutes"]})}
        save(self.evidence)
        if not accepted["ok"]:
            return out
        started = self.call("start_trip", "driver", {"trip_id": trip["id"]})
        out["steps"]["start_trip"] = {"ok": started["ok"], **({"error": started["error"]} if not started["ok"] else {"status": started["value"]["trip"]["status"]})}
        save(self.evidence)
        if not started["ok"]:
            return out
        segment = self.call("complete_segment", "passenger", {"booking_id": booking_id})
        out["steps"]["complete_segment"] = {"ok": segment["ok"], **({"error": segment["error"]} if not segment["ok"] else {"status": segment["value"]["booking"]["status"]})}
        save(self.evidence)
        if not segment["ok"]:
            return out
        complete = self.call("complete_trip", "driver", {"trip_id": trip["id"]})
        out["steps"]["complete_trip"] = {"ok": complete["ok"], **({"error": complete["error"]} if not complete["ok"] else {"status": complete["value"]["trip"]["status"]})}
        save(self.evidence)
        if not complete["ok"]:
            return out
        ratings = []
        for who, stars in (("passenger", 5), ("driver", 5)):
            rated = self.call("rate", who, {"booking_id": booking_id, "stars": stars, "comment": "Development end-to-end evidence"})
            ratings.append({"actor": who, "ok": rated["ok"], **({"error": rated["error"]} if not rated["ok"] else {"rating_id": rated["value"]["rating"]["id"]})})
        out["steps"]["ratings"] = ratings
        out["lifecycle_ids"] = {"preview_id": p["id"], "trip_id": trip["id"], "request_id": result["request"]["id"], "match_id": match["id"], "booking_id": booking_id}
        save(self.evidence)
        return out

    def run_adjacent_seat_reuse(self, departure):
        out = {"status": "attempted", "scope": "Adjacent seat inventory evidence only; no real passenger pickup convenience or demand claim.", "alternate_method": "After the named Nandigama endpoint was incompatible, use one coordinate sampled from the actual OSRM route geometry to test touching segments; do not treat it as a real pickup landmark.", "steps": {}}
        self.evidence["seat_reuse"] = out
        save(self.evidence)
        origin = {"label": "Suryapet", "lat": 17.139, "lon": 79.620}
        destination = {"label": "Kodad", "lat": 16.998, "lon": 79.966}
        preview = self.call("preview", "driver", {"origin": origin, "destination": destination, "departure": iso(departure), "seats": 1, "max_detour_minutes": 10})
        if not preview["ok"]:
            out["steps"]["preview"] = {"ok": False, "error": preview["error"]}; save(self.evidence); return out
        p = preview["value"]["preview"]
        out["steps"]["preview"] = {"ok": True, "preview_id": p["id"], "route": compact_route(p["route"])}
        geometry = p["route"]["coordinates"]
        # Choose explicit, reproducible road points from the actual OSRM geometry.
        # This is only a test of adjacent segment inventory, not fabricated routing.
        middle_coord = geometry[round((len(geometry) - 1) * 0.58)]
        middle = {"label": "OSRM route point 58% (between Suryapet and Kodad)", "lon": middle_coord[0], "lat": middle_coord[1]}
        out["road_points"] = {"origin": origin, "middle": middle, "destination": destination}
        pub = self.call("publish", "driver", {"preview_id": p["id"]})
        if not pub["ok"]:
            out["steps"]["publish"] = {"ok": False, "error": pub["error"]}; save(self.evidence); return out
        trip = pub["value"]["trip"]
        out["steps"]["publish"] = {"ok": True, "trip_id": trip["id"], "seats": trip["seats"]}
        interval = {"window_start": iso(departure - timedelta(minutes=1)), "window_end": iso(departure + timedelta(hours=4)), "seats": 1}
        # Preserve the originally suggested Suryapet→Nandigama leg as its own
        # measured attempt. If it is ineligible, retain the exact engine reason.
        nandigama = {"label": "Nandigama", "lat": 16.771, "lon": 80.285}
        specified = self.call("search", "passenger", {"origin": origin, "destination": nandigama, **interval})
        if specified["ok"]:
            specified_result = specified["value"]
            specified_matches = [m for m in specified_result["matches"] if m["trip_id"] == trip["id"]]
            evaluation = next((row for row in specified_result["request"].get("evaluations", []) if row["trip_id"] == trip["id"]), None)
            out["steps"]["specified_nandigama_search"] = {"ok": True, "request_id": specified_result["request"]["id"], "metrics": specified_result["metrics"], "trip_match_count": len(specified_matches), "trip_evaluation": evaluation}
        else:
            out["steps"]["specified_nandigama_search"] = {"ok": False, "error": specified["error"], "error_type": specified["error_type"]}
        save(self.evidence)
        segments = [("passenger", origin, middle), ("passenger2", middle, destination)]
        bookings = []
        for who, pickup, dropoff in segments:
            searched = self.call("search", who, {"origin": pickup, "destination": dropoff, **interval})
            if not searched["ok"]:
                out["steps"][f"search_{who}"] = {"ok": False, "error": searched["error"]}; save(self.evidence); return out
            matches = [m for m in searched["value"]["matches"] if m["trip_id"] == trip["id"]]
            out["steps"][f"search_{who}"] = {"ok": True, "request_id": searched["value"]["request"]["id"], "metrics": searched["value"]["metrics"], "trip_match_count": len(matches)}
            if not matches:
                save(self.evidence); return out
            requested = self.call("request", who, {"match_id": matches[0]["id"]})
            if not requested["ok"]:
                out["steps"][f"request_{who}"] = {"ok": False, "error": requested["error"]}; save(self.evidence); return out
            booking_id = requested["value"]["booking"]["id"]
            accepted = self.call("accept", "driver", {"booking_id": booking_id})
            out["steps"][f"accept_{who}"] = {"ok": accepted["ok"], **({"error": accepted["error"]} if not accepted["ok"] else {"booking_id": booking_id, "status": accepted["value"]["booking"]["status"], "start_m": round(accepted["value"]["booking"]["start_m"], 1), "end_m": round(accepted["value"]["booking"]["end_m"], 1)})}
            save(self.evidence)
            if not accepted["ok"]:
                return out
            bookings.append(booking_id)
        state = self.call("state", "driver", {})
        trip_view = next((t for t in state.get("value", {}).get("trips", []) if t["id"] == trip["id"]), None) if state["ok"] else None
        out["accepted_adjacent_bookings"] = bookings
        out["inventory"] = trip_view.get("inventory") if trip_view else None
        out["success"] = len(bookings) == 2 and all(out["steps"].get(f"accept_{who}", {}).get("ok") for who, _, _ in segments)
        save(self.evidence)
        return out

def main():
    # The requested evidence DB is deliberately removed only by manual operator action;
    # reruns reuse it and are clearly identified as cumulative evidence.
    evidence = {"schema": "live-osrm-service-e2e-v1", "started_at": datetime.now(timezone.utc).isoformat(), "scope": "Local development actors; live OSRM road routing; no real users or rides; not market validation.", "database_reused": DB.exists(), "corridors": {}, "seat_reuse": {"status": "not_run"}}
    runner = Runner(evidence)
    save(evidence)
    base = datetime.now(IST).replace(microsecond=0) + timedelta(days=3)
    east = runner.run_corridor("east", EAST, base)
    east_success = all(east.get("steps", {}).get(k, {}).get("ok") for k in ("preview", "publish", "search", "request", "accept", "start_trip", "complete_segment", "complete_trip")) and all(x.get("ok") for x in east.get("steps", {}).get("ratings", []))
    evidence["east_full_lifecycle_success"] = east_success
    save(evidence)
    if east_success:
        south = runner.run_corridor("south", SOUTH, base + timedelta(days=2))
        evidence["corridors"]["south"] = south
    else:
        evidence["corridors"]["south"] = {"status": "not_run", "reason": "East full lifecycle did not complete; requested ordering preserved."}
    south = evidence["corridors"]["south"]
    south_success = bool(south.get("lifecycle_ids")) and all(south.get("steps", {}).get(k, {}).get("ok") for k in ("preview", "publish", "search", "request", "accept", "start_trip", "complete_segment", "complete_trip")) and all(x.get("ok") for x in south.get("steps", {}).get("ratings", []))
    if east_success and south_success:
        runner.run_adjacent_seat_reuse(base + timedelta(days=4))
    try:
        ops = runner.call("operations", "admin", {})
        if ops["ok"]:
            metrics = ops["value"]["metrics"]
            evidence["operations"] = {"ok": True, "metrics": metrics, "collection_counts": {k: len(ops["value"].get(k, [])) for k in ("users", "trips", "requests", "matches", "bookings", "ratings", "events", "route_calculations")}}
        else:
            evidence["operations"] = {"ok": False, "error": ops["error"]}
    except Exception as exc:
        evidence["operations"] = {"ok": False, "error": str(exc)}
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    save(evidence)
    print(json.dumps({"evidence": str(OUT), "database": str(DB), "east_full_lifecycle_success": east_success, "south": evidence["corridors"]["south"].get("status", "attempted"), "operations": evidence.get("operations", {}).get("ok")}, indent=2))

if __name__ == "__main__":
    main()
