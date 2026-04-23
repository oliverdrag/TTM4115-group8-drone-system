import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("navigation")


def _heading(prev: tuple[int, int], nxt: tuple[int, int]) -> int:
    dx, dy = nxt[0] - prev[0], nxt[1] - prev[1]
    if dx > 0: return 90
    if dx < 0: return 270
    if dy < 0: return 0
    if dy > 0: return 180
    return 0


class NavigationModule:
    def __init__(self, drone_id: str, tick_ms: int,
                 publish_telemetry: Callable[[int, int, int], None],
                 on_arrived_client: Callable[[], None],
                 on_arrived_home: Callable[[], None]):
        self.drone_id = drone_id
        self.tick_ms = tick_ms
        self.publish_telemetry = publish_telemetry
        self.on_arrived_client = on_arrived_client
        self.on_arrived_home = on_arrived_home
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._route: list[tuple[int, int]] = []
        self._trail: list[tuple[int, int]] = []
        self._phase: Optional[str] = None
        self._position: tuple[int, int] = (0, 0)

    def set_home(self, home: tuple[int, int]) -> None:
        with self._lock:
            self._position = home
            self._trail = [home]
        self.publish_telemetry(home[0], home[1], 0)

    def fly_to_client(self, route: list[tuple[int, int]]) -> None:
        self._cancel_timer()
        with self._lock:
            if route and route[0] == self._position:
                route = route[1:]
            self._route = list(route)
            self._trail = [self._position]
            self._phase = "client"
        log.info("[%s] outbound flight started, %d cells", self.drone_id, len(self._route))
        self._schedule_next()

    def fly_home(self) -> None:
        self._cancel_timer()
        with self._lock:
            trail = list(reversed(self._trail))
            if trail and trail[0] == self._position:
                trail = trail[1:]
            self._route = trail
            self._trail = [self._position]
            self._phase = "home"
        log.info("[%s] return flight started, %d cells", self.drone_id, len(self._route))
        self._schedule_next()

    def abort(self) -> None:
        self._cancel_timer()
        with self._lock:
            self._route = []
            self._phase = None

    def _schedule_next(self) -> None:
        with self._lock:
            if not self._route:
                self._deliver_arrival_locked()
                return
        self._timer = threading.Timer(self.tick_ms / 1000.0, self._step)
        self._timer.daemon = True
        self._timer.start()

    def _step(self) -> None:
        with self._lock:
            if not self._route:
                self._deliver_arrival_locked()
                return
            next_pos = self._route.pop(0)
            prev = self._position
            self._position = next_pos
            self._trail.append(next_pos)
            heading = _heading(prev, next_pos)
            remaining = len(self._route)
        self.publish_telemetry(next_pos[0], next_pos[1], heading)
        if remaining > 0:
            self._schedule_next()
        else:
            self._finish_flight()

    def _deliver_arrival_locked(self) -> None:
        phase = self._phase
        self._phase = None
        if phase == "client":
            threading.Thread(target=self.on_arrived_client, daemon=True).start()
        elif phase == "home":
            threading.Thread(target=self.on_arrived_home, daemon=True).start()

    def _finish_flight(self) -> None:
        with self._lock:
            phase = self._phase
            self._phase = None
        if phase == "client":
            self.on_arrived_client()
        elif phase == "home":
            self.on_arrived_home()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None
