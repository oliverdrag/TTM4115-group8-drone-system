"""Live fleet state and dispatch logic.

The fleet manager owns:
- in-memory drone roster (position, battery_state, status, current mission)
- order lifecycle (submit → assigned → dispatched → ... → completed)
- A* path computation
- translating drone MQTT events into REST/WS-friendly state updates

It uses the MQTTBridge to talk to drones and the Database for persistence.
"""

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from .config import DRONES
from .database import Database
from .grid import Grid
from .mqtt_bridge import MQTTBridge
from .pathfinding import astar


log = logging.getLogger("fleet_manager")


class FleetManager:
    def __init__(self, db: Database, grid: Grid, bridge: MQTTBridge):
        self.db = db
        self.grid = grid
        self.bridge = bridge
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, dict], None]] = []

        # Live drone state keyed by id. Seeded from config + persisted state.
        self.drones: dict[str, dict] = {}
        # order_id -> current state snapshot (subset of DB row + live path)
        self.orders: dict[int, dict] = {}

        self._bootstrap_drones()

    # ---- bootstrap ------------------------------------------------------
    def _bootstrap_drones(self) -> None:
        persisted = {d["id"]: d for d in self.db.list_drones()}
        for cfg in DRONES:
            hx, hy = cfg["home"]
            row = persisted.get(cfg["id"])
            drone = {
                "id": cfg["id"],
                "name": cfg["name"],
                "home_x": hx,
                "home_y": hy,
                "x": row["x"] if row else hx,
                "y": row["y"] if row else hy,
                "status": row["status"] if row else "docked",
                "battery_state": row["battery_state"] if row else "high",
                "medicine": row["medicine"] if row else "",
                "mission_id": None,
                "order_id": None,
            }
            self.drones[cfg["id"]] = drone
            self.db.upsert_drone(drone)

    # ---- subscriptions --------------------------------------------------
    def add_listener(self, fn: Callable[[str, dict], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[str, dict], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _broadcast(self, event: str, payload: dict) -> None:
        # Snapshot listeners under lock so a slow subscriber can't block us.
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event, payload)
            except Exception:
                log.exception("broadcast listener failed")

    # ---- snapshot helpers ----------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "drones": [dict(d) for d in self.drones.values()],
                "orders": [dict(o) for o in self.orders.values()],
            }

    # ---- order lifecycle -----------------------------------------------
    def submit_order(self, user_name: str, medicine: str, dest: tuple[int, int]) -> dict:
        """Entry point from the REST API."""
        if not self.grid.is_free(*dest):
            raise ValueError("Destination is inside a restricted zone")

        order_id = self.db.create_order(user_name, medicine, dest)
        order = {
            "id": order_id,
            "user_name": user_name,
            "medicine": medicine,
            "dest_x": dest[0],
            "dest_y": dest[1],
            "status": "pending",
            "drone_id": None,
            "route": None,
        }
        with self._lock:
            self.orders[order_id] = order

        self._broadcast("order_created", order)

        drone = self._find_available_drone()
        if drone is None:
            self.db.update_order(order_id, status="failed")
            order["status"] = "failed"
            self._broadcast("order_failed", {"order_id": order_id, "reason": "no drones"})
            raise RuntimeError("No drones available")

        path = astar(self.grid, (drone["x"], drone["y"]), dest)
        if path is None:
            self.db.update_order(order_id, status="failed")
            order["status"] = "failed"
            self._broadcast("order_failed", {"order_id": order_id, "reason": "no route"})
            raise RuntimeError("No route to destination")

        # Reserve the drone and create the mission record.
        drone["status"] = "assigned"
        drone["medicine"] = medicine
        drone["order_id"] = order_id
        mission_id = self.db.create_mission(order_id, drone["id"], path)
        drone["mission_id"] = mission_id
        self.db.upsert_drone(drone)
        self.db.update_order(order_id, drone_id=drone["id"], status="assigned")

        order["drone_id"] = drone["id"]
        order["status"] = "assigned"
        order["route"] = path
        self._broadcast("order_assigned", order)
        self._broadcast("drone_updated", dict(drone))

        # Tell the drone to get ready to load.
        self.bridge.send_command(drone["id"], "new_order", order_id=order_id, medicine=medicine)
        return order

    def confirm_medicine_loaded(self, drone_id: str) -> None:
        """Hospital staff pressed 'medicine loaded' for this drone."""
        drone = self._get_drone(drone_id)
        order_id = drone.get("order_id")
        if order_id is None:
            raise RuntimeError(f"{drone_id} has no active order")
        order = self.orders.get(order_id)
        if order is None:
            raise RuntimeError(f"order {order_id} not found in memory")
        route = order.get("route") or []
        dest = (order["dest_x"], order["dest_y"])
        self.bridge.send_command(
            drone_id,
            "medicine_loaded",
            destination=list(dest),
            route=[list(p) for p in route],
        )
        self.db.update_order(order_id, status="in_transit")
        order["status"] = "in_transit"
        self._broadcast("order_in_transit", dict(order))

    def confirm_delivery_received(self, order_id: int) -> None:
        """User pressed 'medicine received' in the user app."""
        order = self.orders.get(order_id)
        if order is None or order.get("drone_id") is None:
            raise RuntimeError(f"unknown order {order_id}")
        drone_id = order["drone_id"]
        self.bridge.send_command(drone_id, "delivery_completed", order_id=order_id)
        self.db.update_order(order_id, status="delivered")
        order["status"] = "delivered"
        self._broadcast("order_delivered", dict(order))

    def cancel_order(self, order_id: int) -> None:
        order = self.orders.get(order_id)
        if order is None:
            return
        drone_id = order.get("drone_id")
        if drone_id:
            self.bridge.send_command(drone_id, "cancel", order_id=order_id)
        self.db.update_order(order_id, status="cancelled")
        order["status"] = "cancelled"
        self._broadcast("order_cancelled", dict(order))

    def return_drone(self, drone_id: str) -> None:
        """Hospital-originated 'return' button on a docked/loaded drone."""
        drone = self._get_drone(drone_id)
        self.bridge.send_command(drone_id, "cancel")
        drone["status"] = "returning"
        self.db.upsert_drone(drone)
        self._broadcast("drone_updated", dict(drone))

    # ---- selection ------------------------------------------------------
    def _find_available_drone(self) -> Optional[dict]:
        with self._lock:
            candidates = [
                d for d in self.drones.values()
                if d["status"] == "docked" and d["battery_state"] in ("high", "low")
            ]
        if not candidates:
            return None
        # High battery first, then nearest to hangar corner (stable choice).
        candidates.sort(key=lambda d: (d["battery_state"] != "high", d["x"] + d["y"]))
        return candidates[0]

    def _get_drone(self, drone_id: str) -> dict:
        drone = self.drones.get(drone_id)
        if drone is None:
            raise RuntimeError(f"unknown drone {drone_id}")
        return drone

    # ---- MQTT event handling -------------------------------------------
    def on_mqtt_event(self, drone_id: str, channel: str, payload: dict) -> None:
        drone = self.drones.get(drone_id)
        if drone is None:
            log.warning("event for unknown drone %s", drone_id)
            return
        if channel == "status":
            self._handle_status(drone, payload)
        elif channel == "telemetry":
            self._handle_telemetry(drone, payload)
        elif channel == "battery":
            self._handle_battery(drone, payload)
        elif channel == "event":
            self._handle_event(drone, payload)
        elif channel == "display":
            self._broadcast("drone_display", {"drone_id": drone_id, **payload})

    def _handle_status(self, drone: dict, payload: dict) -> None:
        status = payload.get("status", "")
        drone["status"] = status
        self.db.upsert_drone(drone)
        self._broadcast(
            "drone_status",
            {"drone_id": drone["id"], "status": status, "message": payload.get("message", "")},
        )
        self._broadcast("drone_updated", dict(drone))

    def _handle_telemetry(self, drone: dict, payload: dict) -> None:
        x = payload.get("x")
        y = payload.get("y")
        if isinstance(x, int) and isinstance(y, int):
            drone["x"] = x
            drone["y"] = y
            self.db.upsert_drone(drone)
            self._broadcast(
                "drone_telemetry",
                {"drone_id": drone["id"], "x": x, "y": y, "heading": payload.get("heading", 0)},
            )

    def _handle_battery(self, drone: dict, payload: dict) -> None:
        state = payload.get("state", "")
        if state:
            drone["battery_state"] = state
            self.db.upsert_drone(drone)
            self._broadcast(
                "drone_battery",
                {"drone_id": drone["id"], "state": state},
            )
            self._broadcast("drone_updated", dict(drone))

    def _handle_event(self, drone: dict, payload: dict) -> None:
        kind = payload.get("kind", "")
        if kind == "arrived_at_client":
            order_id = drone.get("order_id")
            if order_id:
                self.db.update_order(order_id, status="arrived")
                order = self.orders.get(order_id)
                if order:
                    order["status"] = "arrived"
                    self._broadcast("order_arrived", dict(order))
        elif kind == "returned_home":
            # Drone is docked again; mission + order close out.
            mission_id = drone.get("mission_id")
            order_id = drone.get("order_id")
            if mission_id:
                self.db.update_mission(
                    mission_id,
                    status="completed",
                    completed_at=datetime.utcnow().isoformat(),
                )
            if order_id:
                order = self.orders.get(order_id)
                if order and order.get("status") != "cancelled":
                    self.db.update_order(order_id, status="completed")
                    if order:
                        order["status"] = "completed"
                        self._broadcast("order_completed", dict(order))
            drone["order_id"] = None
            drone["mission_id"] = None
            drone["medicine"] = ""
            drone["status"] = "docked"
            self.db.upsert_drone(drone)
            self._broadcast("drone_updated", dict(drone))
