import requests

from .config import AIRSPACE_SERVICE_URL

RESTRICTED_ZONES_QUERY = """
query RestrictedZones($width: Int!, $height: Int!) {
  restrictedZones(width: $width, height: $height) {
    id
    name
    cells { x y }
  }
}
""".strip()


def fetch_restricted_zones(width: int, height: int, timeout: float = 3.0) -> list[dict]:
    r = requests.post(
        AIRSPACE_SERVICE_URL,
        json={"query": RESTRICTED_ZONES_QUERY, "variables": {"width": width, "height": height}},
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(f"Airspace service error: {body['errors']}")
    zones = body.get("data", {}).get("restrictedZones", []) or []
    return [
        {
            "id": z.get("id", ""),
            "name": z.get("name", ""),
            "cells": [(c["x"], c["y"]) for c in z.get("cells", [])],
        }
        for z in zones
    ]
