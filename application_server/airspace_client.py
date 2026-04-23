"""GraphQL client for the Airspace Zone Service mock."""

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
    """Ask the airspace service for the current restricted-zone polygons.

    The mock returns zones as lists of cells rather than vector polygons — we
    operate on a tile grid so this is the useful shape.
    """
    response = requests.post(
        AIRSPACE_SERVICE_URL,
        json={
            "query": RESTRICTED_ZONES_QUERY,
            "variables": {"width": width, "height": height},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if "errors" in body:
        raise RuntimeError(f"Airspace service error: {body['errors']}")
    zones = body.get("data", {}).get("restrictedZones", []) or []
    # Normalize: cells are {x, y} dicts from GraphQL; we want tuples inside.
    normalized = []
    for zone in zones:
        cells = [(c["x"], c["y"]) for c in zone.get("cells", [])]
        normalized.append(
            {
                "id": zone.get("id", ""),
                "name": zone.get("name", ""),
                "cells": cells,
            }
        )
    return normalized
