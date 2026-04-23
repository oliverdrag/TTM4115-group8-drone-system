import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from .config import BATTERY_SAFETY_MARGIN, BATTERY_TICK_MS, DRONES, NAV_TICK_MS
from .database import Database
from .grid import Grid
from .mqtt_bridge import MQTTBridge
from .pathfinding import astar
from .weather_client import fetch_weather

log = logging.getLogger("fleet_manager")


class FleetManager:
    _AVAILABLE_BATTERY = {"high", "low", "high_charging", "low_charging"}
    _BATTERY_PRIORITY = {"high_charging": 0, "high": 1, "low_charging": 2, "low": 3}
    _BATTERY_RUNWAY_MS = {
        "high": 2 * BATTERY_TICK_MS, "high_charging": 2 * BATTERY_TICK_MS,
        "low": BATTERY_TICK_MS, "low_charging": BATTERY_TICK_MS,
    }
    _IN_FLIGHT_STATUSES = {
        "flight started", "returning", "delivered, returning",
        "cancel, returning", "timed out, returning", "arrived, unloading medicine",
    }

    def __init__(self, db: Database, grid: Grid, bridge: MQTTBridge):
        self.db = db
        self.grid = grid
        self.bridge = bridge
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, dict], None]] = []
        self.drones: dict[str, dict] = {}
        self.orders: dict[int, dict] = {}
        self.viewer: dict = {}
        self._bootstrap_drones()

    def _bootstrap_drones(self) -> None:
        persisted = {d["id"]: d for d in self.db.list_drones()}
        for cfg in DRONES:
            hx, hy = cfg["home"]
            row = persisted.get(cfg["id"])
            drone = {
                "id": cfg["id"], "name": cfg["name"],
                "home_x": hx, "home_y": hy,
                "x": row["x"] if row else hx,
                "y": row["y"] if row else hy,
                "status": row["status"] if row else "docked",
                "battery_state": row["battery_state"] if row else "high",
                "medicine": row["medicine"] if row else "",
                "mission_id": None, "order_id": None,
            }
            self.drones[cfg["id"]] = drone
            self.db.upsert_drone(drone)

    def add_listener(self, fn: Callable[[str, dict], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[str, dict], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _broadcast(self, event: str, payload: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event, payload)
            except Exception:
                log.exception("broadcast listener failed")

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "drones": [dict(d) for d in self.drones.values()],
                "orders": [dict(o) for o in self.orders.values()],
                "viewer": dict(self.viewer),
            }

    def _set_order_status(self, order: dict, status: str, event: str) -> None:
        self.db.update_order(order["id"], status=status)
        order["status"] = status
        self._broadcast(event, dict(order))

    def on_viewer_event(self, payload: dict) -> None:
        drone_id = payload.get("drone_id")
        if not drone_id:
            return
        with self._lock:
            self.viewer = {"drone_id": drone_id, "zoom_level": payload.get("zoom_level")}
        self._broadcast("viewer_changed", dict(self.viewer))

    def submit_order(self, user_name: str, medicine: str, dest: tuple[int, int]) -> dict:
        if not self.grid.is_free(*dest):
            raise ValueError("Destination is inside a restricted zone")
        if not self._is_flyable(dest):
            raise ValueError("Weather unflyable at destination (wind or rain above limits)")
        order_id = self.db.create_order(user_name, medicine, dest)
        order = {
            "id": order_id, "user_name": user_name, "medicine": medicine,
            "dest_x": dest[0], "dest_y": dest[1],
            "status": "pending", "drone_id": None, "route": None,
        }
        with self._lock:
            self.orders[order_id] = order
        self._broadcast("order_created", order)

        assigned = self._pick_drone_for(dest)
        if assigned is None:
            self._set_order_status(order, "failed", "order_failed")
            raise RuntimeError("No drone has enough battery to reach the destination and return")
        drone, path = assigned
        drone.update({
            "status": "assigned", "medicine": medicine, "order_id": order_id,
            "mission_id": self.db.create_mission(order_id, drone["id"], path),
        })
        self.db.upsert_drone(drone)
        self.db.update_order(order_id, drone_id=drone["id"], status="assigned")
        order.update({"drone_id": drone["id"], "status": "assigned", "route": path})
        self._broadcast("order_assigned", order)
        self._broadcast("drone_updated", dict(drone))
        self.bridge.send_command(drone["id"], "new_order", order_id=order_id, medicine=medicine)
        return order

    def confirm_medicine_loaded(self, drone_id: str) -> None:
        drone = self._get_drone(drone_id)
        order_id = drone.get("order_id")
        if order_id is None:
            raise RuntimeError(f"{drone_id} has no active order")
        order = self.orders.get(order_id)
        if order is None:
            raise RuntimeError(f"order {order_id} not found in memory")
        route = order.get("route") or []
        self.bridge.send_command(drone_id, "stop_charge")
        self.bridge.send_command(drone_id, "medicine_loaded",
                                 destination=[order["dest_x"], order["dest_y"]],
                                 route=[list(p) for p in route])
        self._set_order_status(order, "in_transit", "order_in_transit")

    def confirm_delivery_received(self, order_id: int) -> None:
        order = self.orders.get(order_id)
        if order is None or order.get("drone_id") is None:
            raise RuntimeError(f"unknown order {order_id}")
        self.bridge.send_command(order["drone_id"], "delivery_completed", order_id=order_id)
        self._set_order_status(order, "delivered", "order_delivered")

    def cancel_order(self, order_id: int) -> None:
        order = self.orders.get(order_id)
        if order is None:
            return
        if order.get("drone_id"):
            self.bridge.send_command(order["drone_id"], "cancel", order_id=order_id)
        self._set_order_status(order, "cancelled", "order_cancelled")

    def return_drone(self, drone_id: str) -> None:
        drone = self._get_drone(drone_id)
        self.bridge.send_command(drone_id, "cancel")
        drone["status"] = "returning"
        self.db.upsert_drone(drone)
        self._broadcast("drone_updated", dict(drone))

    def _is_flyable(self, cell: tuple[int, int]) -> bool:
        try:
            w = fetch_weather(*cell)
        except Exception as e:
            log.warning("weather check failed for %s (%s) — treating as flyable", cell, e)
            return True
        return bool(w.get("flyable", True))

    def _pick_drone_for(self, dest: tuple[int, int]) -> Optional[tuple[dict, list[tuple[int, int]]]]:
        with self._lock:
            candidates = [d for d in self.drones.values()
                          if d["status"] == "docked" and d["battery_state"] in self._AVAILABLE_BATTERY]
        if not candidates:
            return None
        scored: list[tuple[int, dict, list[tuple[int, int]]]] = []
        for drone in candidates:
            if not self._is_flyable((drone["x"], drone["y"])):
                log.info("skipping %s: unflyable weather at home", drone["id"])
                continue
            path = astar(self.grid, (drone["x"], drone["y"]), dest)
            if path is None:
                continue
            flight_ms = 2 * max(0, len(path) - 1) * NAV_TICK_MS
            runway_ms = self._BATTERY_RUNWAY_MS.get(drone["battery_state"], 0)
            if flight_ms > runway_ms * BATTERY_SAFETY_MARGIN:
                continue
            scored.append((len(path), drone, path))
        if not scored:
            return None
        scored.sort(key=lambda row: (row[0], self._BATTERY_PRIORITY.get(row[1]["battery_state"], 99)))
        _, drone, path = scored[0]
        return drone, path

    def _get_drone(self, drone_id: str) -> dict:
        drone = self.drones.get(drone_id)
        if drone is None:
            raise RuntimeError(f"unknown drone {drone_id}")
        return drone

    def on_mqtt_event(self, drone_id: str, channel: str, payload: dict) -> None:
        drone = self.drones.get(drone_id)
        if drone is None:
            return
        if channel == "display":
            self._broadcast("drone_display", {"drone_id": drone_id, **payload})
            return
        fn = getattr(self, f"_handle_{channel}", None)
        if fn:
            fn(drone, payload)

    def _handle_status(self, drone: dict, payload: dict) -> None:
        status = payload.get("status", "")
        drone["status"] = status
        self.db.upsert_drone(drone)
        self._broadcast("drone_status", {
            "drone_id": drone["id"], "status": status, "message": payload.get("message", ""),
        })
        self._broadcast("drone_updated", dict(drone))
        if status == "docked":
            self.bridge.send_command(drone["id"], "charge")

    def _handle_telemetry(self, drone: dict, payload: dict) -> None:
        x, y = payload.get("x"), payload.get("y")
        if isinstance(x, int) and isinstance(y, int):
            drone["x"], drone["y"] = x, y
            self.db.upsert_drone(drone)
            self._broadcast("drone_telemetry", {
                "drone_id": drone["id"], "x": x, "y": y, "heading": payload.get("heading", 0),
            })

    def _handle_battery(self, drone: dict, payload: dict) -> None:
        state = payload.get("state", "")
        if not state:
            return
        drone["battery_state"] = state
        self.db.upsert_drone(drone)
        self._broadcast("drone_battery", {"drone_id": drone["id"], "state": state})
        self._broadcast("drone_updated", dict(drone))
        if state == "empty" and drone["status"] in self._IN_FLIGHT_STATUSES:
            log.warning("[%s] went empty mid-flight — emergency landed", drone["id"])
            drone["status"] = "emergency_landed_empty"
            self.db.upsert_drone(drone)
            order = self.orders.get(drone.get("order_id"))
            if order and order.get("status") not in ("cancelled", "completed"):
                self._set_order_status(order, "failed", "order_failed")
            self._broadcast("drone_updated", dict(drone))

    def _handle_event(self, drone: dict, payload: dict) -> None:
        kind = payload.get("kind", "")
        order = self.orders.get(drone.get("order_id"))
        if kind == "arrived_at_client":
            if order:
                self._set_order_status(order, "arrived", "order_arrived")
        elif kind == "returned_home":
            if drone.get("mission_id"):
                self.db.update_mission(drone["mission_id"], status="completed",
                                       completed_at=datetime.utcnow().isoformat())
            if order and order.get("status") != "cancelled":
                self._set_order_status(order, "completed", "order_completed")
            drone.update({"order_id": None, "mission_id": None, "medicine": "", "status": "docked"})
            self.db.upsert_drone(drone)
            self._broadcast("drone_updated", dict(drone))
