import logging
import os
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("display")

try:
    from sense_hat import SenseHat  # type: ignore[import-not-found]
except Exception:
    SenseHat = None  # type: ignore[assignment]

_DISABLED = os.environ.get("DISABLE_DISPLAY", "0") == "1"
RESTRICTED_THRESHOLD = 0.25

OFF = (0, 0, 0)
RED = (180, 0, 0)
PATH_GREEN = (0, 150, 40)

DRONE_RGB: dict[int, tuple[int, int, int]] = {
    1: (40, 90, 255), 2: (220, 40, 40), 3: (255, 110, 0),
    4: (220, 170, 0), 5: (180, 50, 220),
}
FALLBACK_DRONE_RGB = (200, 200, 200)
ZOOM_CELLS_PER_LED = [10, 5, 2, 1]
_DOCKED_STATUSES = {"docked", "returned", "docking", "emergency_landed_empty", "offline"}


def _drone_index(drone_id: str) -> int:
    try:
        return int(drone_id.split("-")[-1])
    except (ValueError, IndexError):
        return 0


def drone_color(drone_id: str) -> tuple[int, int, int]:
    return DRONE_RGB.get(_drone_index(drone_id), FALLBACK_DRONE_RGB)


class GridDisplay:
    def __init__(self, hat_size: int = 8,
                 on_focus_change: Optional[Callable[[str], None]] = None):
        self.hat_size = hat_size
        self.on_focus_change = on_focus_change
        self.grid_width = 0
        self.grid_height = 0
        self.restricted: set[tuple[int, int]] = set()
        self.path: set[tuple[int, int]] = set()
        self.positions: dict[str, tuple[int, int]] = {}
        self.known_drones: list[str] = []
        self.focus_drone: Optional[str] = None
        self.zoom_level = 0
        self._lock = threading.Lock()
        self.disabled = _DISABLED
        self.hat = None
        self._stick_thread: Optional[threading.Thread] = None
        self._stick_stop = threading.Event()
        if not self.disabled and SenseHat is not None:
            try:
                self.hat = SenseHat()
                self.hat.low_light = False
                self.hat.clear()
            except Exception as e:
                log.warning("SenseHat init failed (%s); using ASCII fallback", e)
                self.hat = None

    def _track_drone(self, drone_id: str) -> None:
        if drone_id and drone_id not in self.known_drones:
            self.known_drones.append(drone_id)
            self.known_drones.sort()

    def set_grid(self, width: int, height: int, zones: list[dict]) -> None:
        with self._lock:
            self.grid_width = width
            self.grid_height = height
            self.restricted = {
                (int(c[0]), int(c[1])) for z in zones for c in z.get("cells", [])
            }
        self.render()

    def set_path(self, route, **_) -> None:
        with self._lock:
            self.path = {(int(p[0]), int(p[1])) for p in (route or [])}
        self.render()

    def clear_path(self) -> None:
        with self._lock:
            self.path = set()
        self.render()

    def set_position(self, x: int, y: int, drone_id: Optional[str] = None) -> None:
        key = drone_id or "_self"
        with self._lock:
            self.positions[key] = (int(x), int(y))
            self._track_drone(drone_id or "")
        self.render()

    def set_drone_status(self, drone_id: str, status: str) -> None:
        with self._lock:
            self._track_drone(drone_id)
            if drone_id == self.focus_drone and status in _DOCKED_STATUSES and self.path:
                self.path = set()
                log.info("focus drone %s is %s — path cleared", drone_id, status)
        self.render()

    def _fire_focus_change(self, drone_id: str) -> None:
        if self.on_focus_change:
            try:
                self.on_focus_change(drone_id)
            except Exception:
                log.exception("on_focus_change callback raised")

    def set_focus_drone(self, drone_id: str) -> None:
        changed = False
        with self._lock:
            self._track_drone(drone_id)
            if self.focus_drone != drone_id:
                self.focus_drone = drone_id
                self.path = set()
                changed = True
        if changed:
            self._fire_focus_change(drone_id)
        self.render()

    def cycle_focus(self, delta: int) -> Optional[str]:
        with self._lock:
            if not self.known_drones:
                return None
            idx = self.known_drones.index(self.focus_drone) if self.focus_drone in self.known_drones else 0
            new_focus = self.known_drones[(idx + delta) % len(self.known_drones)]
            if new_focus == self.focus_drone:
                return new_focus
            self.focus_drone = new_focus
            self.path = set()
        self._fire_focus_change(new_focus)
        self.render()
        return new_focus

    def set_zoom(self, level: int) -> None:
        with self._lock:
            self.zoom_level = max(0, min(len(ZOOM_CELLS_PER_LED) - 1, level))
        self.render()

    def change_zoom(self, delta: int) -> int:
        with self._lock:
            self.zoom_level = max(0, min(len(ZOOM_CELLS_PER_LED) - 1, self.zoom_level + delta))
            new_level = self.zoom_level
        self.render()
        return new_level

    def render(self) -> None:
        if self.disabled:
            return
        with self._lock:
            if self.grid_width == 0 or self.grid_height == 0:
                return
            leds = self._compute_leds_locked()
        if self.hat is not None:
            try:
                self.hat.set_pixels([c for row in leds for c in row])
            except Exception as e:
                log.warning("hat.set_pixels failed: %s", e)
        else:
            self._ascii(leds)

    def _viewport_locked(self) -> tuple[int, int, int]:
        cpl = ZOOM_CELLS_PER_LED[self.zoom_level]
        viewport_cells = self.hat_size * cpl
        focus_pos = None
        if self.focus_drone and self.focus_drone in self.positions:
            focus_pos = self.positions[self.focus_drone]
        elif "_self" in self.positions:
            focus_pos = self.positions["_self"]
        if focus_pos is None or viewport_cells >= max(self.grid_width, self.grid_height):
            return (0, 0, cpl)
        cx, cy = focus_pos
        ox = max(0, min(self.grid_width - viewport_cells, cx - viewport_cells // 2))
        oy = max(0, min(self.grid_height - viewport_cells, cy - viewport_cells // 2))
        return (ox - ox % cpl, oy - oy % cpl, cpl)

    def _compute_leds_locked(self) -> list[list[tuple[int, int, int]]]:
        size = self.hat_size
        ox, oy, cpl = self._viewport_locked()
        leds = [[OFF] * size for _ in range(size)]
        for led_y in range(size):
            for led_x in range(size):
                x0 = ox + led_x * cpl
                y0 = oy + led_y * cpl
                x1 = min(self.grid_width, x0 + cpl)
                y1 = min(self.grid_height, y0 + cpl)
                if x0 >= self.grid_width or y0 >= self.grid_height:
                    continue
                total = max(1, (x1 - x0) * (y1 - y0))
                restricted_count = 0
                path_hit = False
                for yy in range(y0, y1):
                    for xx in range(x0, x1):
                        if (xx, yy) in self.restricted:
                            restricted_count += 1
                        if (xx, yy) in self.path:
                            path_hit = True
                if restricted_count / total > RESTRICTED_THRESHOLD:
                    leds[led_y][led_x] = RED
                elif path_hit:
                    leds[led_y][led_x] = PATH_GREEN
        focus_key = None
        if self.focus_drone and self.focus_drone in self.positions:
            focus_key = self.focus_drone
        elif "_self" in self.positions and not self.focus_drone:
            focus_key = "_self"
        if focus_key is not None:
            px, py = self.positions[focus_key]
            if ox <= px < ox + size * cpl and oy <= py < oy + size * cpl:
                led_x = (px - ox) // cpl
                led_y = (py - oy) // cpl
                if 0 <= led_x < size and 0 <= led_y < size:
                    leds[led_y][led_x] = drone_color(self.focus_drone or "drone-01")
        return leds

    def _ascii(self, leds: list[list[tuple[int, int, int]]]) -> None:
        def char_for(rgb):
            if rgb == OFF: return "·"
            if rgb == RED: return "R"
            if rgb == PATH_GREEN: return "G"
            for idx, color in DRONE_RGB.items():
                if rgb == color:
                    return str(idx)
            return "?"
        lines = ["   " + " ".join(str(i) for i in range(self.hat_size))]
        for y, row in enumerate(leds):
            lines.append(f"{y:2} " + " ".join(char_for(c) for c in row))
        log.info("display (zoom=%d cells/led, focus=%s):\n%s",
                 ZOOM_CELLS_PER_LED[self.zoom_level], self.focus_drone or "-", "\n".join(lines))

    def start_joystick(self, on_cycle: Optional[Callable[[int], None]] = None,
                       on_zoom: Optional[Callable[[int], None]] = None) -> None:
        if self.disabled or self.hat is None:
            return

        def run() -> None:
            try:
                stick = self.hat.stick  # type: ignore[union-attr]
            except Exception as e:
                log.warning("joystick unavailable: %s", e)
                return
            cycle = on_cycle or self.cycle_focus
            zoom = on_zoom or self.change_zoom
            while not self._stick_stop.is_set():
                try:
                    events = stick.get_events()
                    if not events:
                        time.sleep(0.05)
                        continue
                    for ev in events:
                        if getattr(ev, "action", None) != "pressed":
                            continue
                        d = getattr(ev, "direction", None)
                        if d == "left": cycle(-1)
                        elif d == "right": cycle(1)
                        elif d == "up": zoom(1)
                        elif d == "down": zoom(-1)
                        elif d == "middle": self.set_zoom(0)
                except Exception as e:
                    log.warning("joystick read failed: %s", e)
                    time.sleep(0.2)

        self._stick_thread = threading.Thread(target=run, daemon=True)
        self._stick_thread.start()

    def close(self) -> None:
        self._stick_stop.set()
        if self.hat is not None:
            try:
                self.hat.clear()
            except Exception:
                pass
