"""Pipes MQTT traffic between the drones and the fleet manager."""

import json
import logging
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from .config import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_ROOT, drone_topic, viewer_topic


log = logging.getLogger("mqtt_bridge")


class MQTTBridge:
    """Connects to the broker once and fans messages into a callback.

    Spawns its own network thread via `loop_start()`. All drone-originated
    messages land in `on_event(drone_id, channel, payload)` so the fleet
    manager doesn't need to know anything about MQTT. Sense-HAT viewer
    state (when the Pi's joystick switches focus drone) is routed to the
    optional `on_viewer` callback.
    """

    def __init__(
        self,
        on_event: Callable[[str, str, dict], None],
        on_viewer: Optional[Callable[[dict], None]] = None,
    ):
        self.on_event = on_event
        self.on_viewer = on_viewer
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._ready = threading.Event()

    # ---- lifecycle ------------------------------------------------------
    def start(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT) -> None:
        log.info("Connecting to MQTT %s:%s", broker, port)
        self.client.connect_async(broker, port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    # ---- publish --------------------------------------------------------
    def send_command(self, drone_id: str, command: str, **kwargs) -> None:
        payload = {"command": command, **kwargs}
        topic = drone_topic(drone_id, "command")
        self.client.publish(topic, json.dumps(payload), qos=1)
        log.debug("→ %s: %s", topic, payload)

    # ---- callbacks ------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT connected (%s)", reason_code)
        # Subscribe to every drone's uplink channels plus the singleton
        # Sense-HAT viewer topic.
        topics = [
            (f"{MQTT_TOPIC_ROOT}/drone/+/status", 0),
            (f"{MQTT_TOPIC_ROOT}/drone/+/telemetry", 0),
            (f"{MQTT_TOPIC_ROOT}/drone/+/display", 0),
            (f"{MQTT_TOPIC_ROOT}/drone/+/battery", 0),
            (f"{MQTT_TOPIC_ROOT}/drone/+/event", 0),
            (viewer_topic(), 0),
        ]
        client.subscribe(topics)
        self._ready.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Dropped invalid payload on %s", msg.topic)
            return
        # Viewer topic is global, not per-drone.
        if msg.topic == viewer_topic():
            if self.on_viewer is not None:
                try:
                    self.on_viewer(payload)
                except Exception:
                    log.exception("viewer handler failed")
            return
        # Topic shape: ttm4115/group8/drone/<id>/<channel>
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        drone_id = parts[3]
        channel = parts[4]
        try:
            self.on_event(drone_id, channel, payload)
        except Exception:
            log.exception("Event handler failed for %s/%s", drone_id, channel)
