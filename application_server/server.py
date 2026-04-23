import json
import logging
import queue

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sock import Sock

from .config import APP_SERVER_HOST, APP_SERVER_PORT, DB_PATH, GRID_HEIGHT, GRID_WIDTH
from .database import Database
from .fleet_manager import FleetManager
from .grid import Grid, generate_zones
from .mqtt_bridge import MQTTBridge
from .pathfinding import astar

log = logging.getLogger("server")


def build_app() -> tuple[Flask, FleetManager]:
    db = Database(DB_PATH)
    zones = _load_zones(db)
    grid = Grid.from_zones(GRID_WIDTH, GRID_HEIGHT, zones)
    db.save_grid_snapshot(GRID_WIDTH, GRID_HEIGHT, json.dumps(zones))

    bridge = MQTTBridge(
        on_event=lambda d, c, p: fleet.on_mqtt_event(d, c, p),
        on_viewer=lambda p: fleet.on_viewer_event(p),
    )
    fleet = FleetManager(db=db, grid=grid, bridge=bridge)

    app = Flask(__name__)
    CORS(app)
    sock = Sock(app)
    _register_rest(app, fleet, grid)
    _register_ws(sock, fleet)
    bridge.start()
    return app, fleet


def _load_zones(db: Database) -> list[dict]:
    from .airspace_client import fetch_restricted_zones
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
    from .config import DRONES
    return generate_zones(GRID_WIDTH, GRID_HEIGHT, reserved=[tuple(d["home"]) for d in DRONES], seed=42)


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

    @app.get("/api/viewer")
    def get_viewer():
        return jsonify(dict(fleet.viewer))

    @app.post("/api/orders")
    def create_order():
        data = request.get_json(force=True, silent=True) or {}
        user_name = (data.get("user_name") or "").strip()
        medicine = (data.get("medicine") or "").strip()
        location = data.get("location") or {}
        try:
            x, y = int(location["x"]), int(location["y"])
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

    def _ok(fn, *args):
        try:
            fn(*args)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @app.post("/api/orders/<int:order_id>/complete")
    def complete_order(order_id: int):
        return _ok(fleet.confirm_delivery_received, order_id)

    @app.post("/api/orders/<int:order_id>/cancel")
    def cancel_order(order_id: int):
        fleet.cancel_order(order_id)
        return jsonify({"ok": True})

    @app.post("/api/drones/<drone_id>/medicine_loaded")
    def medicine_loaded(drone_id: str):
        return _ok(fleet.confirm_medicine_loaded, drone_id)

    @app.post("/api/drones/<drone_id>/return")
    def return_drone(drone_id: str):
        return _ok(fleet.return_drone, drone_id)

    @app.get("/api/missions/<drone_id>/path")
    def mission_path(drone_id: str):
        drone = fleet.drones.get(drone_id)
        if drone is None:
            return jsonify({"error": "unknown drone"}), 404
        order_id = drone.get("order_id")
        order = fleet.orders.get(order_id) if order_id else None
        return jsonify({
            "drone_id": drone_id,
            "position": {"x": drone["x"], "y": drone["y"]},
            "route": order.get("route") if order else None,
            "order_id": order_id,
        })

    @app.post("/api/path")
    def preview_path():
        data = request.get_json(force=True, silent=True) or {}
        try:
            start = (int(data["start"]["x"]), int(data["start"]["y"]))
            goal = (int(data["goal"]["x"]), int(data["goal"]["y"]))
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "start and goal must have int x,y"}), 400
        return jsonify({"path": astar(grid, start, goal)})


def _register_ws(sock: Sock, fleet: FleetManager) -> None:
    @sock.route("/ws/live")
    def live(ws):
        q: queue.Queue = queue.Queue(maxsize=1000)

        def listener(event: str, payload: dict):
            try:
                q.put_nowait({"event": event, "payload": payload})
            except queue.Full:
                pass

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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    app, _ = build_app()
    app.run(host=APP_SERVER_HOST, port=APP_SERVER_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
