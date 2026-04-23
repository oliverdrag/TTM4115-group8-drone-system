import json
import logging
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from .config import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_ROOT, drone_topic, viewer_topic

log = logging.getLogger("mqtt_bridge")


class MQTTBridge:
    def __init__(self, on_event: Callable[[str, str, dict], None],
                 on_viewer: Optional[Callable[[dict], None]] = None):
        self.on_event = on_event
        self.on_viewer = on_viewer
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._ready = threading.Event()

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

    def send_command(self, drone_id: str, command: str, **kwargs) -> None:
        payload = {"command": command, **kwargs}
        self.client.publish(drone_topic(drone_id, "command"), json.dumps(payload), qos=1)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT connected (%s)", reason_code)
        topics = [(f"{MQTT_TOPIC_ROOT}/drone/+/{ch}", 0)
                  for ch in ("status", "telemetry", "display", "battery", "event")]
        topics.append((viewer_topic(), 0))
        client.subscribe(topics)
        self._ready.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if msg.topic == viewer_topic():
            if self.on_viewer is not None:
                try:
                    self.on_viewer(payload)
                except Exception:
                    log.exception("viewer handler failed")
            return
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        try:
            self.on_event(parts[3], parts[4], payload)
        except Exception:
            log.exception("Event handler failed for %s/%s", parts[3], parts[4])
