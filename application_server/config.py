"""Shared config for the application server and its clients."""

import os


# ---- Network ports ----
APP_SERVER_HOST = os.environ.get("APP_SERVER_HOST", "0.0.0.0")
APP_SERVER_PORT = int(os.environ.get("APP_SERVER_PORT", "5000"))

AIRSPACE_MOCK_HOST = os.environ.get("AIRSPACE_MOCK_HOST", "0.0.0.0")
AIRSPACE_MOCK_PORT = int(os.environ.get("AIRSPACE_MOCK_PORT", "5001"))

YR_MOCK_HOST = os.environ.get("YR_MOCK_HOST", "0.0.0.0")
YR_MOCK_PORT = int(os.environ.get("YR_MOCK_PORT", "5002"))


# ---- URLs the application server uses to reach the mocks ----
AIRSPACE_SERVICE_URL = os.environ.get(
    "AIRSPACE_SERVICE_URL",
    f"http://localhost:{AIRSPACE_MOCK_PORT}/graphql",
)
YR_SERVICE_URL = os.environ.get(
    "YR_SERVICE_URL",
    f"http://localhost:{YR_MOCK_PORT}",
)
APP_SERVER_URL = os.environ.get(
    "APP_SERVER_URL",
    f"http://localhost:{APP_SERVER_PORT}",
)


# ---- MQTT ----
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_ROOT = os.environ.get("MQTT_TOPIC_ROOT", "ttm4115/group8")


def drone_topic(drone_id: str, channel: str) -> str:
    """Per-drone MQTT topic: ttm4115/group8/drone/<id>/<channel>."""
    return f"{MQTT_TOPIC_ROOT}/drone/{drone_id}/{channel}"


def viewer_topic() -> str:
    """Singleton topic for Sense-HAT viewport state (which drone is being followed)."""
    return f"{MQTT_TOPIC_ROOT}/viewer/status"


# ---- Grid ----
# World is an 8 km × 8 km square rendered as 80 × 80 tiles of 100 m each.
# The Sense HAT (8 × 8 LEDs) shows the grid downsampled 10×.
METERS_PER_CELL = 100
GRID_WIDTH = 80
GRID_HEIGHT = 80


# ---- Database ----
DB_PATH = os.environ.get("DB_PATH", "drone_system.db")


# ---- Drone roster ----
# The hospital hangars are clustered near one corner of the grid; this is what
# the drones treat as "home" when returning.
DRONES = [
    {"id": "drone-01", "name": "Drone 01", "home": (5, 5)},
    {"id": "drone-02", "name": "Drone 02", "home": (5, 10)},
    {"id": "drone-03", "name": "Drone 03", "home": (10, 5)},
    {"id": "drone-04", "name": "Drone 04", "home": (10, 10)},
    {"id": "drone-05", "name": "Drone 05", "home": (15, 5)},
]


# ---- Simulation tuning ----
# How long the navigation module spends on each grid cell while flying.
# 500 ms @ 100 m/cell → 200 m/s effective sim speed, one full traversal ≈ 40 s.
NAV_TICK_MS = int(os.environ.get("NAV_TICK_MS", "500"))
# Duration of each battery stage per the state-machine diagram (30 s in the spec).
BATTERY_TICK_MS = int(os.environ.get("BATTERY_TICK_MS", "30000"))
# Time the drone waits for the recipient before giving up and returning.
DELIVERY_TIMEOUT_MS = int(os.environ.get("DELIVERY_TIMEOUT_MS", "180000"))
# Safety factor — only commit a drone if the round-trip takes less than
# this fraction of its remaining battery runway.
BATTERY_SAFETY_MARGIN = float(os.environ.get("BATTERY_SAFETY_MARGIN", "0.9"))
