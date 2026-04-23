import os

APP_SERVER_HOST = os.environ.get("APP_SERVER_HOST", "0.0.0.0")
APP_SERVER_PORT = int(os.environ.get("APP_SERVER_PORT", "5000"))
AIRSPACE_MOCK_HOST = os.environ.get("AIRSPACE_MOCK_HOST", "0.0.0.0")
AIRSPACE_MOCK_PORT = int(os.environ.get("AIRSPACE_MOCK_PORT", "5001"))
YR_MOCK_HOST = os.environ.get("YR_MOCK_HOST", "0.0.0.0")
YR_MOCK_PORT = int(os.environ.get("YR_MOCK_PORT", "5002"))

AIRSPACE_SERVICE_URL = os.environ.get("AIRSPACE_SERVICE_URL", f"http://localhost:{AIRSPACE_MOCK_PORT}/graphql")
YR_SERVICE_URL = os.environ.get("YR_SERVICE_URL", f"http://localhost:{YR_MOCK_PORT}")
APP_SERVER_URL = os.environ.get("APP_SERVER_URL", f"http://localhost:{APP_SERVER_PORT}")

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_ROOT = os.environ.get("MQTT_TOPIC_ROOT", "ttm4115/group8")


def drone_topic(drone_id: str, channel: str) -> str:
    return f"{MQTT_TOPIC_ROOT}/drone/{drone_id}/{channel}"


def viewer_topic() -> str:
    return f"{MQTT_TOPIC_ROOT}/viewer/status"


METERS_PER_CELL = 100
GRID_WIDTH = 80
GRID_HEIGHT = 80

DB_PATH = os.environ.get("DB_PATH", "drone_system.db")

DRONES = [
    {"id": "drone-01", "name": "Drone 01", "home": (5, 5)},
    {"id": "drone-02", "name": "Drone 02", "home": (5, 10)},
    {"id": "drone-03", "name": "Drone 03", "home": (10, 5)},
    {"id": "drone-04", "name": "Drone 04", "home": (10, 10)},
    {"id": "drone-05", "name": "Drone 05", "home": (15, 5)},
]

NAV_TICK_MS = int(os.environ.get("NAV_TICK_MS", "500"))
BATTERY_TICK_MS = int(os.environ.get("BATTERY_TICK_MS", "30000"))
DELIVERY_TIMEOUT_MS = int(os.environ.get("DELIVERY_TIMEOUT_MS", "180000"))
BATTERY_SAFETY_MARGIN = float(os.environ.get("BATTERY_SAFETY_MARGIN", "0.9"))
