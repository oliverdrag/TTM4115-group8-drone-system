#!/usr/bin/env bash
set -euo pipefail

PI_USER="${PI_USER:-group8}"
PI_HOST="${PI_HOST:-group8-drone.local}"
REMOTE_DIR="${REMOTE_DIR:-~/drone-system}"
MQTT_BROKER="${MQTT_BROKER:-$(ip -4 addr show | awk '/inet / && $2 !~ /^127\./ {sub(/\/.*/,"",$2); print $2; exit}')}"
MQTT_PORT="${MQTT_PORT:-1884}"
APP_SERVER_URL="${APP_SERVER_URL:-http://${MQTT_BROKER}:5000}"
NAV_TICK_MS="${NAV_TICK_MS:-500}"
BATTERY_TICK_MS="${BATTERY_TICK_MS:-45000}"

echo "→ syncing project to ${PI_USER}@${PI_HOST}:${REMOTE_DIR}"
ssh "${PI_USER}@${PI_HOST}" "mkdir -p ${REMOTE_DIR}"
rsync -az --delete \
  --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
  --exclude='*.db' --exclude='*.db-journal' \
  --exclude='images/' --exclude='diagrams/' \
  --exclude='hospital_computer/' --exclude='recipient_mobile/' --exclude='ui_theme.py' \
  ./ "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

echo "→ ensuring venv + deps on Pi"
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  cd ${REMOTE_DIR}
  [ -d .venv ] || python3 -m venv --system-site-packages .venv
  .venv/bin/pip install --quiet --disable-pip-version-check stmpy paho-mqtt requests
"

if [ $# -ge 1 ]; then
  drone_id="$1"
  echo "→ launching ${drone_id} on the Pi (MQTT=${MQTT_BROKER}:${MQTT_PORT}, APP=${APP_SERVER_URL})"
  ssh "${PI_USER}@${PI_HOST}" "
    cd ${REMOTE_DIR}
    pkill -f 'drone.drone_main' || true
    sleep 0.3
    MQTT_BROKER=${MQTT_BROKER} MQTT_PORT=${MQTT_PORT} \
    APP_SERVER_URL=${APP_SERVER_URL} \
    NAV_TICK_MS=${NAV_TICK_MS} BATTERY_TICK_MS=${BATTERY_TICK_MS} \
    nohup .venv/bin/python -m drone.drone_main ${drone_id} > ${drone_id}.log 2>&1 &
    sleep 1
    tail -5 ${drone_id}.log
  "
  echo "→ tail logs: ssh ${PI_USER}@${PI_HOST} 'tail -f ${REMOTE_DIR}/${drone_id}.log'"
fi
