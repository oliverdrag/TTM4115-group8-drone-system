import requests

from .config import YR_SERVICE_URL


def fetch_weather(x: int, y: int, timeout: float = 3.0) -> dict:
    r = requests.get(f"{YR_SERVICE_URL}/weather", params={"x": x, "y": y}, timeout=timeout)
    r.raise_for_status()
    return r.json()
