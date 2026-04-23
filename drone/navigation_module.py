"""Mocka GPS / retning for den simulerte drona.

Den ekte navigasjons modulen ville  konsumere IMU + GPS. Vi har ingen av
dem på Raspberry Pien, så denne modulen bare  går en ferdigberegna rute  en grid celle
per tick og emitter telemetri på  hvert steg.

Når drona reiser utover husker den stien; "dra heim" gjenbruker den
reverserte stien, som er  garantert klar siden vi akkurat flydd den.
"""

import logging
import threading
from typing import Callable, Optional


log = logging.getLogger("navigation")


class NavigationModule:
    def __init__(
        self,
        drone_id: str,
        tick_ms: int,
        publish_telemetry: Callable[[int, int, int], None],
        on_arrived_client: Callable[[], None],
        on_arrived_home: Callable[[], None],
    ):
        self.drone_id = drone_id
        self.tick_ms = tick_ms
        self.publish_telemetry = publish_telemetry
        self.on_arrived_client = on_arrived_client
        self.on_arrived_home = on_arrived_home

        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._route: list[tuple[int, int]] = []
        self._trail: list[tuple[int, int]] = []  # besøkt (for returtur)
        self._phase: Optional[str] = None  # "client" | "home"
        self._position: tuple[int, int] = (0, 0)

    # ---- posisjon -------------------------------------------------------
    def set_home(self, home: tuple[int, int]) -> None:
        with self._lock:
            self._position = home
            self._trail = [home]
        self.publish_telemetry(home[0], home[1], 0)

    def position(self) -> tuple[int, int]:
        with self._lock:
            return self._position

    # ---- flight control -------------------------------------------------
    def fly_to_client(self, route: list[tuple[int, int]]) -> None:
        """Start utgående flighten. `route` inkluderer start og målet."""
        self._cancel_timer()
        with self._lock:
            # Dropp den ledande cellen hvis det er der vi allerede er.
            if route and route[0] == self._position:
                route = route[1:]
            self._route = list(route)
            self._trail = [self._position]
            self._phase = "client"
        log.info("[%s] outbound flight started, %d cells", self.drone_id, len(self._route))
        self._schedule_next()

    def fly_home(self) -> None:
        """Snu  rundt og gå  samme sti  tilbake."""
        self._cancel_timer()
        with self._lock:
            # Revers av besøkt sti, hopper over nåværne celle.
            trail = list(reversed(self._trail))
            if trail and trail[0] == self._position:
                trail = trail[1:]
            self._route = trail
            # Resett stien så en  påfølgende utgående flight starter ferskt.
            self._trail = [self._position]
            self._phase = "home"
        log.info("[%s] return flight started, %d cells", self.drone_id, len(self._route))
        self._schedule_next()

    def abort(self) -> None:
        self._cancel_timer()
        with self._lock:
            self._route = []
            self._phase = None

    # ---- internt -------------------------------------------------------
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
            route_remaining = len(self._route)

        self.publish_telemetry(next_pos[0], next_pos[1], heading)
        if route_remaining > 0:
            self._schedule_next()
        else:
            self._finish_flight()

    def _deliver_arrival_locked(self) -> None:
        # Kalt med låsen holdt; slipp før tilbakekall invokeres.
        phase = self._phase
        self._phase = None
        if phase is None:
            return
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


def _heading(prev: tuple[int, int], nxt: tuple[int, int]) -> int:
    """Kompass retning i grader (0=N, 90=Ø, 180=S, 270=V)."""
    dx = nxt[0] - prev[0]
    dy = nxt[1] - prev[1]
    if dx > 0:
        return 90
    if dx < 0:
        return 270
    if dy < 0:
        return 0
    if dy > 0:
        return 180
    return 0
