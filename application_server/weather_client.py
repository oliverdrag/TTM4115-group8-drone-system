"""REST client for the YR weather mock."""

import requests

from .config import YR_SERVICE_URL


def fetch_weather(x: int, y: int, timeout: float = 3.0) -> dict:
    """Ask the mocked YR service for weather at a grid cell.

    Response shape: {"wind": float, "rain_mm": float, "flyable": bool}.
    """
    response = requests.get(
        f"{YR_SERVICE_URL}/weather",
        params={"x": x, "y": y},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
