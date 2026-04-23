"""Sense HAT (or ASCII fallback) visualization of the drone's world.

The world grid is 80 × 80 cells (each cell = 100 m). The Sense HAT is
8 × 8 LEDs. The viewport downsamples the grid to the 8 × 8 matrix, with a
configurable zoom level and a focus drone that the viewport is centred on.

Zoom levels (cells per LED):
    level 0 — 10 cells/LED  (full 80 × 80 grid visible)
    level 1 —  5 cells/LED  (40 × 40 window)
    level 2 —  2 cells/LED  (16 × 16 window)
    level 3 —  1 cell/LED   (8 × 8 window, i.e. real-resolution follow)

Rendering rules:
  - Only the focus drone is drawn on the LED matrix — its identity colour.
  - Other drones' positions are tracked (for the joystick cycle list)
    but not rendered, so the operator sees exactly one dot at a time.
  - The focus drone's planned route is always GREEN so it never blends
    into the drone's own colour.
  - Cells belonging to a restricted zone render red when more than 25 %
    of an LED's block is restricted.
  - Free airspace renders OFF (dark) — no dim-white wash.
  - When the focus drone is docked / returned, the path is auto-cleared.

When `sense_hat` isn't importable (dev laptop), an ASCII fallback draws
the same grid to stdout.
"""

import logging
import os
import threading
import time
from typing import Callable, Optional


log = logging.getLogger("display")

try:
    from sense_hat import SenseHat  # type: ignore[import-not-found]
except Exception:  # pragma: no cover — Sense HAT not present
    SenseHat = None  # type: ignore[assignment]


# DISABLE_DISPLAY=1 makes the module a no-op. Used for virtual drones running
# on the laptop, where neither a real Sense HAT nor the ASCII fallback is
# interesting — we just want quiet state-machine behaviour.
_DISABLED = os.environ.get("DISABLE_DISPLAY", "0") == "1"


# Colour palette (RGB 0-255).
OFF   = (0, 0, 0)
RED   = (180, 0, 0)
# The path is always this green, regardless of the focus drone's colour.
PATH_GREEN = (0, 150, 40)

# Per-drone identity colours, keyed by 1-based drone index (drone-01..drone-05).
# No green in this palette — green is reserved for the planned path so the
# drone dot never blends into its own route.
DRONE_RGB: dict[int, tuple[int, int, int]] = {
    1: (40, 90, 255),   # blue
    2: (220, 40, 40),   # red
    3: (255, 110, 0),   # orange
    4: (220, 170, 0),   # amber
    5: (180, 50, 220),  # purple
}
FALLBACK_DRONE_RGB = (200, 200, 200)

# Discrete zoom table: cells per LED. First level = full-grid overview.
ZOOM_CELLS_PER_LED = [10, 5, 2, 1]

# Statuses that count as "on the ground at home" — used to auto-clear the
# path the moment the focus drone is no longer mid-mission.
_DOCKED_STATUSES = {"docked", "returned", "docking",
                    "emergency_landed_empty", "offline"}


def _drone_index(drone_id: str) -> int:
    try:
        return int(drone_id.split("-")[-1])
    except (ValueError, IndexError):
        return 0


def drone_color(drone_id: str) -> tuple[int, int, int]:
    return DRONE_RGB.get(_drone_index(drone_id), FALLBACK_DRONE_RGB)


class GridDisplay:
    def __init__(
        self,
        hat_size: int = 8,
        restricted_threshold: float = 0.25,
        on_focus_change: Optional[Callable[[str], None]] = None,
    ):
        self.hat_size = hat_size
        self.restricted_threshold = restricted_threshold
        self.on_focus_change = on_focus_change

        self.grid_width = 0
        self.grid_height = 0
        self.restricted: set[tuple[int, int]] = set()

        self.path: set[tuple[int, int]] = set()
        self.path_drone_id: Optional[str] = None

        # Multi-drone position / status map. Other drones are tracked so the
        # joystick can cycle through them — but they're never drawn.
        self.positions: dict[str, tuple[int, int]] = {}
        self.statuses: dict[str, str] = {}
        self.known_drones: list[str] = []
        self.focus_drone: Optional[str] = None

        self.zoom_level = 0

        self._lock = threading.Lock()

        self.disabled = _DISABLED
        self.hat = None
        self._stick_thread: Optional[threading.Thread] = None
        self._stick_stop = threading.Event()

        if self.disabled:
            self.hat = None
        elif SenseHat is not None:
            try:
                self.hat = SenseHat()
                self.hat.low_light = False
                self.hat.clear()
            except Exception as e:
                log.warning("SenseHat init failed (%s); using ASCII fallback", e)
                self.hat = None

    # ---- data setters ---------------------------------------------------
    def set_grid(self, width: int, height: int, zones: list[dict]) -> None:
        with self._lock:
            self.grid_width = width
            self.grid_height = height
            self.restricted = set()
            for zone in zones:
                for cell in zone.get("cells", []):
                    self.restricted.add((int(cell[0]), int(cell[1])))
        self.render()

    def set_path(self, route, drone_id: Optional[str] = None) -> None:
        with self._lock:
            self.path = {(int(p[0]), int(p[1])) for p in (route or [])}
            self.path_drone_id = drone_id
        self.render()

    def clear_path(self) -> None:
        with self._lock:
            self.path = set()
            self.path_drone_id = None
        self.render()

    def set_position(self, x: int, y: int, drone_id: Optional[str] = None) -> None:
        """Update a drone's position. `drone_id=None` means the local drone."""
        key = drone_id or "_self"
        with self._lock:
            self.positions[key] = (int(x), int(y))
            if drone_id and drone_id not in self.known_drones:
                self.known_drones.append(drone_id)
                self.known_drones.sort()
        self.render()

    def set_drone_status(self, drone_id: str, status: str) -> None:
        """Track status so we can auto-clear the path when focus drone docks."""
        clear_triggered = False
        with self._lock:
            self.statuses[drone_id] = status
            if drone_id and drone_id not in self.known_drones:
                self.known_drones.append(drone_id)
                self.known_drones.sort()
            if (drone_id == self.focus_drone
                    and status in _DOCKED_STATUSES
                    and self.path):
                self.path = set()
                self.path_drone_id = None
                clear_triggered = True
        if clear_triggered:
            log.info("focus drone %s is %s — path cleared", drone_id, status)
        self.render()

    def set_focus_drone(self, drone_id: str) -> None:
        changed = False
        with self._lock:
            if drone_id not in self.known_drones:
                self.known_drones.append(drone_id)
                self.known_drones.sort()
            if self.focus_drone != drone_id:
                self.focus_drone = drone_id
                # Switching focus invalidates the previous drone's route.
                self.path = set()
                self.path_drone_id = None
                changed = True
        if changed and self.on_focus_change:
            try:
                self.on_focus_change(drone_id)
            except Exception:
                log.exception("on_focus_change callback raised")
        self.render()

    def cycle_focus(self, delta: int) -> Optional[str]:
        with self._lock:
            if not self.known_drones:
                return None
            if self.focus_drone in self.known_drones:
                idx = self.known_drones.index(self.focus_drone)
            else:
                idx = 0
            new_idx = (idx + delta) % len(self.known_drones)
            new_focus = self.known_drones[new_idx]
            if new_focus == self.focus_drone:
                return new_focus
            self.focus_drone = new_focus
            self.path = set()
            self.path_drone_id = None
        if self.on_focus_change:
            try:
                self.on_focus_change(new_focus)
            except Exception:
                log.exception("on_focus_change callback raised")
        self.render()
        return new_focus

    def set_zoom(self, level: int) -> None:
        level = max(0, min(len(ZOOM_CELLS_PER_LED) - 1, level))
        with self._lock:
            self.zoom_level = level
        self.render()

    def change_zoom(self, delta: int) -> int:
        with self._lock:
            new_level = max(0, min(len(ZOOM_CELLS_PER_LED) - 1,
                                   self.zoom_level + delta))
            self.zoom_level = new_level
        self.render()
        return new_level

    # ---- rendering ------------------------------------------------------
    def render(self) -> None:
        if self.disabled:
            return
        with self._lock:
            if self.grid_width == 0 or self.grid_height == 0:
                return
            leds = self._compute_leds_locked()
        if self.hat is not None:
            try:
                flat: list[tuple[int, int, int]] = [c for row in leds for c in row]
                self.hat.set_pixels(flat)
            except Exception as e:
                log.warning("hat.set_pixels failed: %s", e)
        else:
            self._ascii(leds)

    def _viewport_locked(self) -> tuple[int, int, int]:
        cpl = ZOOM_CELLS_PER_LED[self.zoom_level]
        viewport_cells = self.hat_size * cpl

        focus_pos: Optional[tuple[int, int]] = None
        if self.focus_drone and self.focus_drone in self.positions:
            focus_pos = self.positions[self.focus_drone]
        elif "_self" in self.positions:
            focus_pos = self.positions["_self"]

        if focus_pos is None or viewport_cells >= max(self.grid_width, self.grid_height):
            return (0, 0, cpl)

        cx, cy = focus_pos
        ox = cx - viewport_cells // 2
        oy = cy - viewport_cells // 2
        ox = max(0, min(self.grid_width - viewport_cells, ox))
        oy = max(0, min(self.grid_height - viewport_cells, oy))
        ox -= ox % cpl
        oy -= oy % cpl
        return (ox, oy, cpl)

    def _compute_leds_locked(self) -> list[list[tuple[int, int, int]]]:
        size = self.hat_size
        ox, oy, cpl = self._viewport_locked()
        leds: list[list[tuple[int, int, int]]] = [[OFF] * size for _ in range(size)]

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

                if restricted_count / total > self.restricted_threshold:
                    leds[led_y][led_x] = RED
                elif path_hit:
                    leds[led_y][led_x] = PATH_GREEN

        # Only the focus drone gets rendered on the matrix.
        focus_key: Optional[str] = None
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
                    color = drone_color(self.focus_drone or "drone-01")
                    leds[led_y][led_x] = color

        return leds

    def _ascii(self, leds: list[list[tuple[int, int, int]]]) -> None:
        def char_for(rgb: tuple[int, int, int]) -> str:
            if rgb == OFF:
                return "·"
            if rgb == RED:
                return "R"
            if rgb == PATH_GREEN:
                return "G"
            for idx, color in DRONE_RGB.items():
                if rgb == color:
                    return str(idx)
            return "?"

        lines = ["   " + " ".join(f"{i}" for i in range(self.hat_size))]
        for y, row in enumerate(leds):
            chars = " ".join(char_for(c) for c in row)
            lines.append(f"{y:2} {chars}")
        zoom_label = ZOOM_CELLS_PER_LED[self.zoom_level]
        focus_label = self.focus_drone or "-"
        log.info("display (zoom=%d cells/led, focus=%s):\n%s",
                 zoom_label, focus_label, "\n".join(lines))

    # ---- joystick -------------------------------------------------------
    def start_joystick(
        self,
        on_cycle: Optional[Callable[[int], None]] = None,
        on_zoom: Optional[Callable[[int], None]] = None,
    ) -> None:
        """Start a background thread reading the Sense HAT joystick.

        left/right → cycle focus drone (delegated to `on_cycle(delta)`).
        up/down    → zoom in/out (delegated to `on_zoom(delta)`).
        middle     → reset to full-grid overview.
        """
        if self.disabled or self.hat is None:
            return

        def run() -> None:
            try:
                stick = self.hat.stick  # type: ignore[union-attr]
            except Exception as e:
                log.warning("joystick unavailable: %s", e)
                return

            def handle_event(ev) -> None:
                if getattr(ev, "action", None) != "pressed":
                    return
                direction = getattr(ev, "direction", None)
                if direction == "left":
                    (on_cycle or (lambda d: self.cycle_focus(d)))(-1)
                elif direction == "right":
                    (on_cycle or (lambda d: self.cycle_focus(d)))(1)
                elif direction == "up":
                    (on_zoom or (lambda d: self.change_zoom(d)))(1)
                elif direction == "down":
                    (on_zoom or (lambda d: self.change_zoom(d)))(-1)
                elif direction == "middle":
                    self.set_zoom(0)

            while not self._stick_stop.is_set():
                try:
                    events = stick.get_events()
                    if events:
                        for ev in events:
                            handle_event(ev)
                    else:
                        time.sleep(0.05)
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
