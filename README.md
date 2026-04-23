# TTM4115 Group 8 — Drone Delivery System

Implementation of the emergency-medication drone system described in
`System Spec, Version 3`. The deployment follows the spec diagram:

```
┌────────────────┐      HTTPS/REST      ┌────────────────────────────┐
│ User Frontend  │ ───────────────────▶ │                            │
└────────────────┘                      │    Application Server      │
                                        │   ┌────────────────────┐   │
┌────────────────┐   HTTPS/WS + REST    │   │ Order Processing   │   │      GraphQL      ┌───────────────────────┐
│ Hospital       │ ───────────────────▶ │   │ Fleet Manager      │ ◀────────────────────▶│ Airspace Zone Service │
│ Frontend       │                      │   │ Mission & Drone DB │   │      REST         └───────────────────────┘
└────────────────┘                      │   └────────────────────┘ ◀────────────────────▶│ YR Weather API        │
                                        └──────────────┬─────────────┘                   └───────────────────────┘
                                                       │ MQTT
                                         ┌─────────────▼──────────────┐
                                         │    Autonomous Drone (Pi)   │
                                         │ Flight Control STM         │
                                         │ Battery Management STM     │
                                         │ Navigation Module (mocked) │
                                         └────────────────────────────┘
```

## Layout

| Path                                   | Role                                                         |
|----------------------------------------|--------------------------------------------------------------|
| `app.py`                               | Application-server entry point                               |
| `application_server/`                  | Flask REST + WebSocket, SQLite, A* pathfinding, MQTT bridge  |
| `services/airspace_zone_mock.py`       | Mock Airspace Zone Service (GraphQL, :5001)                  |
| `services/yr_weather_mock.py`          | Mock YR weather API (REST, :5002)                            |
| `drone/`                               | Flight control STM, battery STM, navigation module, entry    |
| `user_app.py`                          | User frontend (tkinter → REST)                               |
| `hospital_app.py`                      | Hospital frontend (tkinter → REST + /ws/live)                |
| `run_all.py`                           | One-shot launcher for local end-to-end runs                  |

## Installing (laptop)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install mosquitto         # binary only — run_all.py runs its own instance
ssh-copy-id group8@group8-drone.local  # passwordless SSH for rsync/deploy
```

## One-command end-to-end

```bash
python run_all.py
```

That single command:

1. Spawns a LAN-bound mosquitto broker on `:1884`
2. Starts the airspace zone mock (`:5001`), YR weather mock (`:5002`) and
   the application server (`:5000`)
3. Launches drones 02-05 as virtual drones on the laptop
4. **rsyncs the repo to the Pi** and starts `drone-01` there with the
   real Sense HAT — the LED matrix shows the path live
5. Opens the user frontend and the hospital frontend

Ctrl+C tears down every process, including the remote drone on the Pi.

Useful overrides:

| Env var         | Purpose                                                   |
|-----------------|-----------------------------------------------------------|
| `SKIP_PI=1`     | Laptop-only — skip rsync + Pi drone                       |
| `LAUNCH_GUIS=0` | Headless mode — no tkinter frontends                      |
| `PI_HOST=...`   | Override Pi hostname (default `group8-drone.local`)       |
| `PI_USER=...`   | Override Pi user (default `group8`)                       |
| `NAV_TICK_MS=`  | Flight speed — ms per grid cell (default `500`)           |

## Running pieces by hand

```bash
python -m services.airspace_zone_mock   # :5001
python -m services.yr_weather_mock      # :5002
python app.py                           # :5000 (reads MQTT_PORT env var)
python -m drone.drone_main drone-02     # one per drone id
python user_app.py
python hospital_app.py
```

To run the drone on the Pi manually:

```bash
./deploy_pi.sh drone-01                # rsync + launch in one step
# or:
ssh group8@group8-drone.local \
  "cd drone-system && MQTT_BROKER=<laptop-ip> MQTT_PORT=1884 \
   APP_SERVER_URL=http://<laptop-ip>:5000 \
   .venv/bin/python -m drone.drone_main drone-01"
```

## REST API (application server)

| Method | Path                                   | Purpose                                |
|--------|----------------------------------------|----------------------------------------|
| GET    | `/api/health`                          | liveness                               |
| GET    | `/api/grid`                            | grid size + restricted zones           |
| GET    | `/api/drones`                          | live fleet snapshot                    |
| POST   | `/api/orders`                          | user submits an order                  |
| GET    | `/api/orders/<id>`                     | user polls order status                |
| POST   | `/api/orders/<id>/complete`            | user confirms delivery received        |
| POST   | `/api/orders/<id>/cancel`              | user cancels                           |
| POST   | `/api/drones/<id>/medicine_loaded`     | hospital confirms loading              |
| POST   | `/api/drones/<id>/return`              | hospital recalls a drone               |
| POST   | `/api/path`                            | A* preview (for hospital viz)          |
| GET    | `/api/missions/<drone_id>/path`        | drone's current route + position       |
| WS     | `/ws/live`                             | fan-out of fleet/order events          |

## World model

- **Grid**: 200×200 tiles, each cell either free or restricted. The
  airspace zone mock generates zones using random-walker blob growth from
  several seed points — feels like a few national parks rather than drawn
  circles.
- **Coordinates**: the user frontend picks a random free cell on order
  submission. Hangars are clustered at the top-left corner (see
  `application_server/config.DRONES`).
- **A***: 4-connected, Manhattan heuristic. Runs on the app server at
  order time; the outbound route is pushed to the drone over MQTT.
- **Return flight**: the drone retraces its trail — always clear,
  without re-running A*.

## State machines

- **Flight control** (drone side): verbatim from the spec diagram —
  states `docked`, `load_medicine`, `travel_to_client`, `deliver`,
  `returning`. The `arrived` / `returned` signals come from the
  Navigation Module instead of a stubbed flight-duration timer.
- **Battery management** (drone side): verbatim from the spec diagram
  with timers `t1`..`t4`. Publishes state changes over MQTT so the fleet
  manager knows when a drone becomes unavailable.
- **User frontend**: `idle → enter_info → drone_delivering`, with a
  `cancelled_by_system` transition driven by the REST order-status poller.

## MQTT topics

| Direction        | Topic                                          | Payload                  |
|------------------|------------------------------------------------|--------------------------|
| server → drone   | `ttm4115/group8/drone/<id>/command`            | `{command, ...}`         |
| drone → server   | `ttm4115/group8/drone/<id>/status`             | `{status}`               |
| drone → server   | `ttm4115/group8/drone/<id>/telemetry`          | `{x, y, heading}`        |
| drone → server   | `ttm4115/group8/drone/<id>/battery`            | `{state}`                |
| drone → server   | `ttm4115/group8/drone/<id>/event`              | `{kind, ...}`            |
| drone → server   | `ttm4115/group8/drone/<id>/display`            | `{display}`              |

## Environment variables

| Variable              | Default            | Notes                                   |
|-----------------------|--------------------|-----------------------------------------|
| `APP_SERVER_HOST`     | `0.0.0.0`          |                                         |
| `APP_SERVER_PORT`     | `5000`             |                                         |
| `APP_SERVER_URL`      | `http://localhost:5000` | used by the frontends              |
| `MQTT_BROKER`         | `localhost`        | set on the Pi                           |
| `MQTT_PORT`           | `1883`             |                                         |
| `AIRSPACE_SERVICE_URL`| `http://localhost:5001/graphql` |                             |
| `YR_SERVICE_URL`      | `http://localhost:5002` |                                    |
| `DB_PATH`             | `drone_system.db`  |                                         |
| `NAV_TICK_MS`         | `150`              | flight speed (ms per grid cell)         |
| `BATTERY_TICK_MS`     | `30000`            | battery state duration                  |
| `DELIVERY_TIMEOUT_MS` | `180000`           | drone hovers this long for the recipient|
