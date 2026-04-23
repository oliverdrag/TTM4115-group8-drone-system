"""Flask REST + WebSocket interface for the application server.

REST endpoints:
  GET  /api/health                         — liveness
  GET  /api/grid                           — grid size + restricted zones
  GET  /api/drones                         — live drone fleet
  POST /api/orders                         — user submits an order
  GET  /api/orders/<id>                    — user polls order status
  POST /api/orders/<id>/complete           — user confirms delivery received
  POST /api/orders/<id>/cancel             — user cancels
  POST /api/drones/<id>/medicine_loaded    — hospital confirms loading
  POST /api/drones/<id>/return             — hospital orders a return
  GET  /api/missions/<drone_id>/path       — current route for a drone

WebSocket:
  /ws/live — fan-out of fleet/order events as JSON frames
"""

import json
import logging
import queue

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sock import Sock

from .config import (
    APP_SERVER_HOST,
    APP_SERVER_PORT,
    DB_PATH,
    GRID_HEIGHT,
    GRID_WIDTH,
)
from .database import Database
from .fleet_manager import FleetManager
from .grid import Grid, generate_zones
from .mqtt_bridge import MQTTBridge
from .pathfinding import astar


log = logging.getLogger("server")


def build_app() -> tuple[Flask, FleetManager]:
    db = Database(DB_PATH)

    # Load zones: prefer the airspace service, fall back to cached snapshot,
    # and finally synthesize fresh blobs so the server still comes up even
    # when the mocks aren't running.
    zones = _load_zones(db)
    grid = Grid.from_zones(GRID_WIDTH, GRID_HEIGHT, zones)
    db.save_grid_snapshot(GRID_WIDTH, GRID_HEIGHT, json.dumps(zones))

    bridge = MQTTBridge(on_event=lambda drone_id, channel, payload: fleet.on_mqtt_event(drone_id, channel, payload))
    fleet = FleetManager(db=db, grid=grid, bridge=bridge)

    app = Flask(__name__)
    CORS(app)
    sock = Sock(app)

    _register_rest(app, fleet, grid)
    _register_ws(sock, fleet)

    # Start MQTT after Flask objects exist so the callback can fire safely.
    bridge.start()

    return app, fleet


def _load_zones(db: Database) -> list[dict]:
    from .airspace_client import fetch_restricted_zones  # lazy import

    try:
        zones = fetch_restricted_zones(GRID_WIDTH, GRID_HEIGHT)
        log.info("Loaded %d restricted zones from airspace service", len(zones))
        return [{"id": z["id"], "name": z["name"], "cells": [list(c) for c in z["cells"]]} for z in zones]
    except Exception as exc:
        log.warning("Airspace service unavailable (%s); falling back to cache/synth", exc)

    snapshot = db.load_grid_snapshot()
    if snapshot:
        try:
            return json.loads(snapshot["zones_json"])
        except Exception:
            pass

    log.info("Generating synthetic restricted zones")
    from .config import DRONES

    reserved = [tuple(d["home"]) for d in DRONES]
    return generate_zones(GRID_WIDTH, GRID_HEIGHT, reserved=reserved, seed=42)


# ---- REST --------------------------------------------------------------
def _register_rest(app: Flask, fleet: FleetManager, grid: Grid) -> None:
    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/grid")
    def get_grid():
        return jsonify(grid.to_dict())

    @app.get("/api/drones")
    def list_drones():
        return jsonify({"drones": [dict(d) for d in fleet.drones.values()]})

    @app.post("/api/orders")
    def create_order():
        data = request.get_json(force=True, silent=True) or {}
        user_name = (data.get("user_name") or "").strip()
        medicine = (data.get("medicine") or "").strip()
        location = data.get("location") or {}
        try:
            x = int(location["x"])
            y = int(location["y"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "location.x and location.y must be integers"}), 400
        if not user_name or not medicine:
            return jsonify({"error": "user_name and medicine are required"}), 400
        try:
            order = fleet.submit_order(user_name, medicine, (x, y))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        return jsonify(order), 201

    @app.get("/api/orders/<int:order_id>")
    def get_order(order_id: int):
        order = fleet.orders.get(order_id)
        if order is None:
            row = fleet.db.get_order(order_id)
            if row is None:
                return jsonify({"error": "not found"}), 404
            return jsonify(row)
        return jsonify(order)

    @app.post("/api/orders/<int:order_id>/complete")
    def complete_order(order_id: int):
        try:
            fleet.confirm_delivery_received(order_id)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @app.post("/api/orders/<int:order_id>/cancel")
    def cancel_order(order_id: int):
        fleet.cancel_order(order_id)
        return jsonify({"ok": True})

    @app.post("/api/drones/<drone_id>/medicine_loaded")
    def medicine_loaded(drone_id: str):
        try:
            fleet.confirm_medicine_loaded(drone_id)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @app.post("/api/drones/<drone_id>/return")
    def return_drone(drone_id: str):
        try:
            fleet.return_drone(drone_id)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @app.get("/api/missions/<drone_id>/path")
    def mission_path(drone_id: str):
        drone = fleet.drones.get(drone_id)
        if drone is None:
            return jsonify({"error": "unknown drone"}), 404
        order_id = drone.get("order_id")
        order = fleet.orders.get(order_id) if order_id else None
        return jsonify(
            {
                "drone_id": drone_id,
                "position": {"x": drone["x"], "y": drone["y"]},
                "route": order.get("route") if order else None,
                "order_id": order_id,
            }
        )

    @app.post("/api/path")
    def preview_path():
        """Utility for the hospital frontend's live pathfinding preview."""
        data = request.get_json(force=True, silent=True) or {}
        try:
            start = (int(data["start"]["x"]), int(data["start"]["y"]))
            goal = (int(data["goal"]["x"]), int(data["goal"]["y"]))
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "start and goal must have int x,y"}), 400
        path = astar(grid, start, goal)
        return jsonify({"path": path})


# ---- WebSocket ---------------------------------------------------------
def _register_ws(sock: Sock, fleet: FleetManager) -> None:
    @sock.route("/ws/live")
    def live(ws):
        q: queue.Queue = queue.Queue(maxsize=1000)

        def listener(event: str, payload: dict):
            try:
                q.put_nowait({"event": event, "payload": payload})
            except queue.Full:
                pass  # drop if the client can't keep up

        # Prime the connection with a full snapshot so the client has state
        # before the first delta arrives.
        ws.send(json.dumps({"event": "snapshot", "payload": fleet.snapshot()}))

        fleet.add_listener(listener)
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    ws.send(json.dumps({"event": "ping", "payload": {}}))
                    continue
                ws.send(json.dumps(msg))
        except Exception:
            pass
        finally:
            fleet.remove_listener(listener)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    app, _fleet = build_app()
    # Threaded so WebSocket, REST and MQTT callbacks coexist without blocking.
    app.run(host=APP_SERVER_HOST, port=APP_SERVER_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
