"""Mock Airspace Zone Service — GraphQL over HTTP.

Endpoint: POST /graphql
Body:     {"query": "...", "variables": {...}}

Supported queries:
  query RestrictedZones($width: Int!, $height: Int!) {
    restrictedZones(width: $width, height: $height) {
      id
      name
      cells { x y }
    }
  }

The mock keeps its generated zones cached so the shape is stable across
queries for a given server run. A new server process = new randomized map.
"""

import logging
import re

from flask import Flask, jsonify, request

from application_server.config import AIRSPACE_MOCK_HOST, AIRSPACE_MOCK_PORT, DRONES
from application_server.grid import generate_zones


app = Flask(__name__)
log = logging.getLogger("airspace_mock")


_CACHE: dict[tuple[int, int], list[dict]] = {}


def _get_zones(width: int, height: int) -> list[dict]:
    key = (width, height)
    if key not in _CACHE:
        reserved = [tuple(d["home"]) for d in DRONES]
        _CACHE[key] = generate_zones(width, height, reserved=reserved, seed=42)
    return _CACHE[key]


@app.post("/graphql")
def graphql():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    variables = body.get("variables", {}) or {}

    # Minimal parser: we only handle the `restrictedZones` field. Real GraphQL
    # servers would use graphene/ariadne; we don't need the full protocol
    # because the application server is the only client.
    if "restrictedZones" not in query:
        return jsonify({"errors": [{"message": "only restrictedZones is implemented"}]}), 400

    width = int(variables.get("width") or _int_literal(query, "width") or 200)
    height = int(variables.get("height") or _int_literal(query, "height") or 200)

    zones = _get_zones(width, height)

    # Shape the response to match a real GraphQL result (data / errors).
    data_zones = []
    for z in zones:
        data_zones.append(
            {
                "id": z["id"],
                "name": z["name"],
                "cells": [{"x": x, "y": y} for (x, y) in z["cells"]],
            }
        )
    return jsonify({"data": {"restrictedZones": data_zones}})


def _int_literal(query: str, field: str):
    """Fallback for queries that inline the int instead of using variables."""
    m = re.search(rf"{field}\s*:\s*(\d+)", query)
    return int(m.group(1)) if m else None


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "airspace_zone_mock"})


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("Airspace mock listening on %s:%s", AIRSPACE_MOCK_HOST, AIRSPACE_MOCK_PORT)
    app.run(host=AIRSPACE_MOCK_HOST, port=AIRSPACE_MOCK_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
