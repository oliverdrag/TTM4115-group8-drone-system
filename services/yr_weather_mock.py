"""Mock YR Weather API — REST.

Endpoint:  GET /weather?x=X&y=Y
Response:  {"location": {"x": X, "y": Y}, "wind": float, "rain_mm": float, "flyable": bool}

The real YR service uses lat/lon + a bigger JSON shape, but since our whole
world is a 200x200 grid without geo coordinates this keeps the contract
cheap while still being a separate REST service the app server calls.
"""

import logging
import math
import random

from flask import Flask, jsonify, request

from application_server.config import YR_MOCK_HOST, YR_MOCK_PORT


app = Flask(__name__)
log = logging.getLogger("yr_mock")


@app.get("/weather")
def weather():
    try:
        x = int(request.args.get("x", 0))
        y = int(request.args.get("y", 0))
    except ValueError:
        return jsonify({"error": "x,y must be integers"}), 400

    # Deterministic-per-cell pseudo-weather, so repeated queries are stable
    # within a server run but vary across cells.
    seed = (x * 7919 + y * 104729) ^ 0xC0FFEE
    rng = random.Random(seed)
    wind = round(rng.uniform(0, 14), 1)
    rain = round(max(0.0, rng.uniform(-5, 6)), 1)
    flyable = wind < 12 and rain < 5.0

    return jsonify(
        {
            "location": {"x": x, "y": y},
            "wind": wind,
            "rain_mm": rain,
            "flyable": flyable,
        }
    )


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "yr_weather_mock"})


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("YR weather mock listening on %s:%s", YR_MOCK_HOST, YR_MOCK_PORT)
    app.run(host=YR_MOCK_HOST, port=YR_MOCK_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
