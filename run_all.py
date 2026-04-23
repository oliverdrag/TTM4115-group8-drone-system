import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

PI_USER = os.environ.get("PI_USER", "group8")
PI_HOST = os.environ.get("PI_HOST", "group8-drone.local")
PI_REMOTE = os.environ.get("PI_REMOTE", "drone-system")
PI_DRONE_ID = os.environ.get("PI_DRONE_ID", "drone-01")

MQTT_PORT = os.environ.get("MQTT_PORT", "1884")
NAV_TICK_MS = os.environ.get("NAV_TICK_MS", "500")
BATTERY_TICK_MS = os.environ.get("BATTERY_TICK_MS", "90000")

LOCAL_DRONES = ["drone-02", "drone-03", "drone-04", "drone-05"]
LAUNCH_GUIS = os.environ.get("LAUNCH_GUIS", "1") != "0"
SKIP_PI = os.environ.get("SKIP_PI", "0") == "1"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def pi_reachable() -> bool:
    if SKIP_PI:
        return False
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
             f"{PI_USER}@{PI_HOST}", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6,
        )
        return r.returncode == 0
    except Exception:
        return False


def wipe_stale_state() -> None:
    for name in ("drone_system.db", "drone_system.db-journal", "drone_log.csv"):
        p = ROOT / name
        if p.exists():
            p.unlink()


def start(name: str, cmd: list[str], env: dict | None = None) -> subprocess.Popen:
    print(f"  → {name}")
    return subprocess.Popen(cmd, cwd=ROOT, env=env or os.environ.copy())


def start_mosquitto(port: str) -> subprocess.Popen:
    conf = ROOT / ".mosquitto-lan.conf"
    conf.write_text(f"listener {port} 0.0.0.0\nallow_anonymous true\n")
    binary = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    return start("mosquitto", [binary, "-c", str(conf)])


def kill_pi_drone() -> None:
    cmd = "pkill -f 'python.*-m drone\\.drone_main' 2>/dev/null ; exit 0"
    try:
        subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", f"{PI_USER}@{PI_HOST}", cmd],
            timeout=6, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def deploy_and_start_pi(host_ip: str) -> subprocess.Popen | None:
    print(f"  → rsync → {PI_USER}@{PI_HOST}:{PI_REMOTE}")
    subprocess.run(["ssh", f"{PI_USER}@{PI_HOST}", f"mkdir -p {PI_REMOTE}"], check=True)
    subprocess.run(
        ["rsync", "-az", "--delete",
         "--exclude=.venv", "--exclude=.git", "--exclude=__pycache__",
         "--exclude=*.db", "--exclude=*.db-journal", "--exclude=*.log",
         "--exclude=images/", "--exclude=diagrams/",
         "--exclude=hospital_app.py", "--exclude=user_app.py",
         "./", f"{PI_USER}@{PI_HOST}:{PI_REMOTE}/"],
        cwd=ROOT, check=True,
    )
    print("  → venv + deps on Pi")
    subprocess.run(
        ["ssh", f"{PI_USER}@{PI_HOST}",
         f"cd {PI_REMOTE} && "
         "([ -d .venv ] || python3 -m venv --system-site-packages .venv) && "
         ".venv/bin/pip install --quiet --disable-pip-version-check "
         "stmpy paho-mqtt requests"],
        check=True,
    )
    print(f"  → {PI_DRONE_ID} on Pi (sense HAT)")
    log_name = f"{PI_DRONE_ID}.log"
    kill_pi_drone()
    start_cmd = (
        f"(cd {PI_REMOTE} && rm -f {log_name} ; "
        f" nohup env MQTT_BROKER={host_ip} MQTT_PORT={MQTT_PORT} "
        f"   APP_SERVER_URL=http://{host_ip}:5000 "
        f"   NAV_TICK_MS={NAV_TICK_MS} BATTERY_TICK_MS={BATTERY_TICK_MS} "
        f"   .venv/bin/python -u -m drone.drone_main {PI_DRONE_ID} "
        f"   > {log_name} 2>&1 < /dev/null &)"
    )
    subprocess.run(["ssh", f"{PI_USER}@{PI_HOST}", start_cmd], check=True)
    time.sleep(0.8)
    return subprocess.Popen(
        ["ssh", "-o", "ServerAliveInterval=15", f"{PI_USER}@{PI_HOST}",
         f"tail -n +1 -F {PI_REMOTE}/{log_name}"],
        cwd=ROOT, stdin=subprocess.DEVNULL,
    )


def main() -> None:
    print("==========================================")
    print(" TTM4115 Group 8 — Drone Delivery System ")
    print("==========================================")
    host_ip = lan_ip()
    print(f"laptop LAN IP: {host_ip}")

    wipe_stale_state()

    env = os.environ.copy()
    env.update({
        "MQTT_BROKER": "localhost",
        "MQTT_PORT": MQTT_PORT,
        "APP_SERVER_URL": "http://localhost:5000",
        "NAV_TICK_MS": NAV_TICK_MS,
        "BATTERY_TICK_MS": BATTERY_TICK_MS,
        "PYTHONUNBUFFERED": "1",
    })

    processes: list[tuple[str, subprocess.Popen]] = []

    def register(name: str, p: subprocess.Popen | None) -> None:
        if p is not None:
            processes.append((name, p))

    try:
        print("\n== laptop ==")
        register("mosquitto", start_mosquitto(MQTT_PORT))
        time.sleep(0.8)

        register("airspace-mock", start("airspace-zone mock   :5001",
                                        [PY, "-m", "services.airspace_zone_mock"], env))
        register("yr-mock", start("yr-weather mock     :5002",
                                  [PY, "-m", "services.yr_weather_mock"], env))
        time.sleep(1.2)

        register("app-server", start("application server  :5000", [PY, "app.py"], env))
        time.sleep(2.0)

        virt_env = {**env, "DISABLE_DISPLAY": "1"}
        for d in LOCAL_DRONES:
            register(d, start(f"virtual {d}", [PY, "-u", "-m", "drone.drone_main", d], virt_env))

        if pi_reachable():
            print("\n== raspberry pi ==")
            register("pi-drone", deploy_and_start_pi(host_ip))
        else:
            print("\n== raspberry pi ==")
            print(f"  × {PI_HOST} not reachable (or SKIP_PI=1) — running laptop-only")

        if LAUNCH_GUIS:
            print("\n== frontends ==")
            register("user-app", start("user frontend", [PY, "user_app.py"], env))
            register("hospital-app", start("hospital frontend", [PY, "hospital_app.py"], env))

        print("\n✓ system up. Ctrl+C to stop everything cleanly.\n")

        while True:
            time.sleep(1)
            for name, p in processes:
                if p.poll() is not None:
                    print(f"\n× {name} exited (rc={p.returncode}) — shutting down")
                    return

    except KeyboardInterrupt:
        print("\n\nCtrl+C — stopping")
    finally:
        kill_pi_drone()
        for name, p in processes:
            try:
                p.send_signal(signal.SIGINT)
            except Exception:
                pass
        deadline = time.time() + 5
        for name, p in processes:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
        print("  done")


if __name__ == "__main__":
    main()
