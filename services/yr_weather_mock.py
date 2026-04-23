import logging
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
    rng = random.Random((x * 7919 + y * 104729) ^ 0xC0FFEE)
    wind = round(rng.uniform(0, 14), 1)
    rain = round(max(0.0, rng.uniform(-5, 6)), 1)
    return jsonify({
        "location": {"x": x, "y": y},
        "wind": wind, "rain_mm": rain,
        "flyable": wind < 12 and rain < 5.0,
    })


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "yr_weather_mock"})


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("YR weather mock listening on %s:%s", YR_MOCK_HOST, YR_MOCK_PORT)
    app.run(host=YR_MOCK_HOST, port=YR_MOCK_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run()
