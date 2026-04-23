"""Een-kommando ende-til-ende oppstarter.

    python run_all.py

Booter  hele systmet og river det ned reint  på Ctrl+C:

  På denne laptopen:
    1. Mosquitto MQTT megler  (LAN-bundet, :1884)
    2. Luftrom sone  mock      (GraphQL, :5001)
    3. YR vær  mock         (REST,    :5002)
    4. Applikasjons server      (REST + /ws/live, :5000)
    5. drone-02 .. drone-05    (virtuele — kunn tilstandsmaskiner)
    6. Bruker frontend  (Tk)
    7. Sykehus frontend (Tk)

  På Raspberry Pien (group8@group8-drone.local):
    8. rsync reposet,  så kjør drone-01 med ekte Sense HAT

Alt er kobla opp sånn at en enkelt bestiling fra bruker frontendn sender
den nermeste dronen (ofte Pi-dronen),  flyr den A*-utregna ruta på tvers av
den 80×80 / 8 km verden, og Pien si LED matrise renderer rutn live.

Miljø overstyringer:
    PI_USER (standard group8)
    PI_HOST (standard group8-drone.local)
    PI_DRONE_ID (standard drone-01)
    MQTT_PORT (standard 1884)
    LAUNCH_GUIS=0 for å hoppe over user_app/hospital_app
    SKIP_PI=1 for  å hoppe over  Pi drona helt (laptop-kunn modus)
"""

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
# Each battery stage lasts this long — tuned so a HIGH-battery drone has
# enough runway (2 × this) to complete a full 80×80 round-trip under the
# fleet manager's BATTERY_SAFETY_MARGIN check. Override via env var for
# stress tests.
BATTERY_TICK_MS = os.environ.get("BATTERY_TICK_MS", "90000")

LOCAL_DRONES = ["drone-02", "drone-03", "drone-04", "drone-05"]
LAUNCH_GUIS = os.environ.get("LAUNCH_GUIS", "1") != "0"
SKIP_PI = os.environ.get("SKIP_PI", "0") == "1"


# ------------------------------------------------------------------ hjelpere
def lan_ip() -> str:
    """Beste-forsøk gjet på  denne laptopens LAN IP."""
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
    """Fjern gammel tilstnad så hver kjøring starter  reint."""
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


def deploy_and_start_pi(host_ip: str) -> subprocess.Popen | None:
    print(f"  → rsync → {PI_USER}@{PI_HOST}:{PI_REMOTE}")
    subprocess.run(
        ["ssh", f"{PI_USER}@{PI_HOST}", f"mkdir -p {PI_REMOTE}"],
        check=True,
    )
    subprocess.run(
        [
            "rsync", "-az", "--delete",
            "--exclude=.venv", "--exclude=.git", "--exclude=__pycache__",
            "--exclude=*.db", "--exclude=*.db-journal", "--exclude=*.log",
            "--exclude=images/", "--exclude=diagrams/",
            "--exclude=hospital_app.py", "--exclude=user_app.py",
            "./", f"{PI_USER}@{PI_HOST}:{PI_REMOTE}/",
        ],
        cwd=ROOT, check=True,
    )
    print("  → sørger for venv + avhengigheter på Pien")
    subprocess.run(
        [
            "ssh", f"{PI_USER}@{PI_HOST}",
            f"cd {PI_REMOTE} && "
            "([ -d .venv ] || python3 -m venv --system-site-packages .venv) && "
            ".venv/bin/pip install --quiet --disable-pip-version-check "
            "stmpy paho-mqtt requests",
        ],
        check=True,
    )
    print(f"  → {PI_DRONE_ID} on Pi (sense HAT)")
    log_name = f"{PI_DRONE_ID}.log"
    # Start drona dettacha via nohup så SSH sesjonen kan avslutte
    # med en gang. Vi strømer den fjerne loggen tilbake med  en andre, lang-levd
    # SSH som orkestrratoren overvåker; nedbrytning dreper  den  fjerne prosesen
    # med en separat `pkill` kall  i kill_pi_drone().
    # Wrap the whole remote command in a subshell `(...)` so the background
    # nohup survives the outer ssh channel closing. Without the subshell SSH
    # returns 255 (remote shell killed before the child forks).
    # Kill any previous drone from a separate SSH — running pkill inside the
    # main launch command would match the SSH wrapper's own argv and kill it.
    kill_pi_drone()
    start_cmd = (
        f"(cd {PI_REMOTE} && "
        f" rm -f {log_name} ; "
        f" nohup env MQTT_BROKER={host_ip} MQTT_PORT={MQTT_PORT} "
        f"   APP_SERVER_URL=http://{host_ip}:5000 "
        f"   NAV_TICK_MS={NAV_TICK_MS} BATTERY_TICK_MS={BATTERY_TICK_MS} "
        f"   .venv/bin/python -u -m drone.drone_main {PI_DRONE_ID} "
        f"   > {log_name} 2>&1 < /dev/null &)"
    )
    subprocess.run(
        ["ssh", f"{PI_USER}@{PI_HOST}", start_cmd],
        check=True,
    )
    # Give nohup a moment to create the log before we start tailing it.
    time.sleep(0.8)
    # Stream the Pi drone's log back to our stdout so the operator sees it
    # alongside the other services.
    return subprocess.Popen(
        ["ssh", "-o", "ServerAliveInterval=15",
         f"{PI_USER}@{PI_HOST}",
         f"tail -n +1 -F {PI_REMOTE}/{log_name}"],
        cwd=ROOT, stdin=subprocess.DEVNULL,
    )


def kill_pi_drone() -> None:
    # Match the python interpreter running the drone module, not the literal
    # string "drone.drone_main" — otherwise pkill catches the ssh wrapper
    # whose argv contains that string and terminates itself.
    cmd = "pkill -f 'python.*-m drone\\.drone_main' 2>/dev/null ; exit 0"
    try:
        subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", f"{PI_USER}@{PI_HOST}", cmd],
            timeout=6, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ------------------------------------------------------------------ main
def main() -> None:
    print("==========================================")
    print(" TTM4115 Group 8 — Drone Delivery System ")
    print("==========================================")
    host_ip = lan_ip()
    print(f"laptop LAN IP: {host_ip}")

    wipe_stale_state()

    # Miljø som hver lokal subprosess  arver.
    env = os.environ.copy()
    env["MQTT_BROKER"] = "localhost"
    env["MQTT_PORT"] = MQTT_PORT
    env["APP_SERVER_URL"] = "http://localhost:5000"
    env["NAV_TICK_MS"] = NAV_TICK_MS
    env["BATTERY_TICK_MS"] = BATTERY_TICK_MS
    env["PYTHONUNBUFFERED"] = "1"

    processes: list[tuple[str, subprocess.Popen]] = []

    def register(name: str, p: subprocess.Popen | None) -> None:
        if p is not None:
            processes.append((name, p))

    try:
        print("\n== laptop ==")
        register("mosquitto", start_mosquitto(MQTT_PORT))
        time.sleep(0.8)

        register("airspace-mock", start(
            "airspace-zone mock   :5001",
            [PY, "-m", "services.airspace_zone_mock"], env,
        ))
        register("yr-mock", start(
            "yr-weather mock     :5002",
            [PY, "-m", "services.yr_weather_mock"], env,
        ))
        time.sleep(1.2)

        register("app-server", start(
            "application server  :5000",
            [PY, "app.py"], env,
        ))
        time.sleep(2.0)

        # Virtuele droner har ikkje sense hat og trengr ikkje den ASCII
        # fallbacken som spammer loggne — skru av  displayet heilt for dem.
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
            register("user-app", start("user frontend",
                                       [PY, "user_app.py"], env))
            register("hospital-app", start("hospital frontend",
                                           [PY, "hospital_app.py"], env))

        print("\n✓ system up. Ctrl+C to stop everything cleanly.\n")

        # Overvåkning — hvis noken kritisk prosses dør, riv ned.
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
            remaining = max(0.1, deadline - time.time())
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                p.kill()
        print("  done")


if __name__ == "__main__":
    main()
