import json
import logging
import os
import sys
import threading
from typing import Optional

import paho.mqtt.client as mqtt
import requests
from stmpy import Driver

from application_server.config import (
    APP_SERVER_URL, BATTERY_TICK_MS, DELIVERY_TIMEOUT_MS, DRONES,
    MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_ROOT, NAV_TICK_MS,
    drone_topic, viewer_topic,
)

from .battery_management import build_machine as build_battery
from .display_hat import GridDisplay, ZOOM_CELLS_PER_LED
from .flight_control import build_machine as build_flight
from .navigation_module import NavigationModule

log = logging.getLogger("drone_main")

_IN_FLIGHT_FLIGHT_STATES = {"travel_to_client", "deliver", "returning"}


def find_drone_config(drone_id: str) -> dict:
    for d in DRONES:
        if d["id"] == drone_id:
            return d
    raise SystemExit(f"Unknown drone_id {drone_id}; known: {[d['id'] for d in DRONES]}")


class Drone:
    def __init__(self, drone_id: str, home: tuple[int, int]):
        self.drone_id = drone_id
        self.home = home
        self.driver = Driver()
        self.display = GridDisplay(on_focus_change=self._on_focus_change)
        self.display.set_focus_drone(self.drone_id)

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=drone_id)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.will_set(drone_topic(drone_id, "status"),
                             json.dumps({"status": "offline"}), qos=1, retain=False)

        self.nav = NavigationModule(
            drone_id=drone_id, tick_ms=NAV_TICK_MS,
            publish_telemetry=self._publish_telemetry,
            on_arrived_client=lambda: self.driver.send("arrived", "flight_control"),
            on_arrived_home=self._on_returned_home,
        )
        self.nav.set_home(home)

        self.flight, flight_machine = build_flight(
            drone_id=drone_id, delivery_timeout_ms=DELIVERY_TIMEOUT_MS, nav=self.nav,
            publish_status=self._publish_status,
            publish_display=self._publish_display,
            publish_event=self._publish_event,
        )
        self.battery, battery_machine = build_battery(
            drone_id=drone_id, tick_ms=BATTERY_TICK_MS, publish=self._publish_battery,
        )
        self.driver.add_machine(flight_machine)
        self.driver.add_machine(battery_machine)

    def _publish(self, channel: str, payload: dict) -> None:
        self.client.publish(drone_topic(self.drone_id, channel), json.dumps(payload), qos=0)

    def _publish_status(self, status: str) -> None:
        self._publish("status", {"status": status})
        self.display.set_drone_status(self.drone_id, status)

    def _publish_display(self, message: str) -> None:
        self._publish("display", {"display": message})

    def _publish_telemetry(self, x: int, y: int, heading: int) -> None:
        self._publish("telemetry", {"x": x, "y": y, "heading": heading})
        self.display.set_position(x, y, drone_id=self.drone_id)

    def _on_returned_home(self) -> None:
        self.display.clear_path()
        self.driver.send("returned", "flight_control")

    def _publish_battery(self, state: str) -> None:
        self._publish("battery", {"state": state})
        if state == "empty":
            self._handle_battery_empty()

    def _publish_event(self, kind: str, extra: Optional[dict] = None) -> None:
        self._publish("event", {"kind": kind, **(extra or {})})

    def _handle_battery_empty(self) -> None:
        flight_state = self.flight.stm.state if self.flight and self.flight.stm else None
        if flight_state not in _IN_FLIGHT_FLIGHT_STATES:
            return
        log.warning("[%s] battery EMPTY while in flight state %s — emergency landing",
                    self.drone_id, flight_state)
        try:
            self.nav.abort()
        except Exception:
            log.exception("nav.abort() failed")
        self._publish_status("emergency_landed_empty")
        self._publish_display("emergency: battery empty")
        self.display.clear_path()

    def _on_focus_change(self, drone_id: str) -> None:
        self._publish_viewer_state(drone_id)
        threading.Thread(target=self._fetch_and_set_focus_path,
                         args=(drone_id,), daemon=True).start()

    def _publish_viewer_state(self, drone_id: str) -> None:
        payload = {
            "drone_id": drone_id,
            "zoom_level": self.display.zoom_level,
            "zoom_cells_per_led": ZOOM_CELLS_PER_LED[self.display.zoom_level],
        }
        try:
            self.client.publish(viewer_topic(), json.dumps(payload), qos=0)
        except Exception:
            log.exception("failed to publish viewer state")

    def _fetch_and_set_focus_path(self, drone_id: str) -> None:
        try:
            r = requests.get(f"{APP_SERVER_URL}/api/missions/{drone_id}/path", timeout=3)
            if not r.ok:
                return
            route = (r.json() or {}).get("route") or []
        except Exception as e:
            log.warning("[%s] could not fetch path for %s: %s", self.drone_id, drone_id, e)
            return
        if route:
            self.display.set_path(route, drone_id=drone_id)
        else:
            self.display.clear_path()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("[%s] MQTT connected (%s)", self.drone_id, reason_code)
        client.subscribe(drone_topic(self.drone_id, "command"), qos=1)
        client.subscribe(f"{MQTT_TOPIC_ROOT}/drone/+/telemetry", qos=0)
        client.subscribe(f"{MQTT_TOPIC_ROOT}/drone/+/status", qos=0)
        current = self.flight.stm.state if self.flight and self.flight.stm else "docked"
        self._publish_status(current)
        self.display.set_position(self.home[0], self.home[1], drone_id=self.drone_id)
        self._publish_viewer_state(self.drone_id)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        src_drone, channel = parts[3], parts[4]
        if src_drone != self.drone_id:
            if channel == "telemetry":
                x, y = payload.get("x"), payload.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    self.display.set_position(x, y, drone_id=src_drone)
            elif channel == "status":
                status = payload.get("status", "")
                if status:
                    self.display.set_drone_status(src_drone, status)
            return
        command = payload.get("command", "")
        log.info("[%s] ← %s: %s", self.drone_id, command, payload)
        if command == "new_order":
            self.driver.send("new_order", "flight_control")
        elif command == "medicine_loaded":
            route = payload.get("route", [])
            self.display.set_path(route, drone_id=self.drone_id)
            self.driver.send("medicine_loaded", "flight_control",
                             args=[payload.get("destination", []), route])
        elif command == "cancel":
            self.driver.send("cancel", "flight_control")
        elif command == "delivery_completed":
            self.driver.send("delivery_completed", "flight_control")
        elif command == "charge":
            self.driver.send("charge", "battery")
        elif command == "stop_charge":
            self.driver.send("stop_charge", "battery")
        else:
            log.warning("[%s] unknown command %r", self.drone_id, command)

    def _fetch_grid_and_paint(self) -> None:
        try:
            r = requests.get(f"{APP_SERVER_URL}/api/grid", timeout=5)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("[%s] could not fetch grid: %s", self.drone_id, e)
            return
        self.display.set_grid(int(data.get("width", 0)), int(data.get("height", 0)),
                              data.get("zones", []))
        self.display.set_position(self.home[0], self.home[1], drone_id=self.drone_id)

    def run(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT) -> None:
        log.info("[%s] connecting to MQTT %s:%s", self.drone_id, broker, port)
        self.client.connect(broker, port, keepalive=60)
        self.driver.start(keep_active=True)
        threading.Thread(target=self._fetch_grid_and_paint, daemon=True).start()
        self.display.start_joystick()
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            log.info("[%s] interrupted; shutting down", self.drone_id)
        finally:
            self.nav.abort()
            self.driver.stop()
            self.client.disconnect()
            self.display.close()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    drone_id = argv[1] if len(argv) > 1 else os.environ.get("DRONE_ID", "drone-01")
    cfg = find_drone_config(drone_id)
    Drone(drone_id=cfg["id"], home=tuple(cfg["home"])).run()


if __name__ == "__main__":
    main(sys.argv)
