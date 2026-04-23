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
        _CACHE[key] = generate_zones(width, height,
                                     reserved=[tuple(d["home"]) for d in DRONES], seed=42)
    return _CACHE[key]


def _int_literal(query: str, field: str):
    m = re.search(rf"{field}\s*:\s*(\d+)", query)
    return int(m.group(1)) if m else None


@app.post("/graphql")
def graphql():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    variables = body.get("variables", {}) or {}
    if "restrictedZones" not in query:
        return jsonify({"errors": [{"message": "only restrictedZones is implemented"}]}), 400
    width = int(variables.get("width") or _int_literal(query, "width") or 200)
    height = int(variables.get("height") or _int_literal(query, "height") or 200)
    data_zones = [
        {"id": z["id"], "name": z["name"],
         "cells": [{"x": x, "y": y} for (x, y) in z["cells"]]}
        for z in _get_zones(width, height)
    ]
    return jsonify({"data": {"restrictedZones": data_zones}})


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "airspace_zone_mock"})


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("Airspace mock listening on %s:%s", AIRSPACE_MOCK_HOST, AIRSPACE_MOCK_PORT)
    app.run(host=AIRSPACE_MOCK_HOST, port=AIRSPACE_MOCK_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
