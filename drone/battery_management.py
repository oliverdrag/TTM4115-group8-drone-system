import logging
from typing import Callable

from stmpy import Machine

log = logging.getLogger("battery")


class BatteryManagement:
    def __init__(self, drone_id: str, tick_ms: int, publish: Callable[[str], None]):
        self.drone_id = drone_id
        self.tick_ms = tick_ms
        self.publish = publish
        self.stm: Machine | None = None

    def _enter(self, state: str) -> None:
        log.info("[%s] battery: %s", self.drone_id, state.upper())
        self.publish(state)

    def enter_high(self): self._enter("high")
    def enter_low(self): self._enter("low")
    def enter_empty(self): self._enter("empty")
    def enter_empty_charging(self): self._enter("empty_charging")
    def enter_low_charging(self): self._enter("low_charging")
    def enter_high_charging(self): self._enter("high_charging")


def build_machine(drone_id: str, tick_ms: int, publish: Callable[[str], None]) -> tuple[BatteryManagement, Machine]:
    handlers = BatteryManagement(drone_id, tick_ms, publish)
    t = str(tick_ms)
    states = [{"name": n, "entry": f"enter_{n}"} for n in
              ("high", "low", "empty", "empty_charging", "low_charging", "high_charging")]
    transitions = [
        {"source": "initial", "target": "high", "effect": f"start_timer('t1', {t})"},
        {"trigger": "t1", "source": "high", "target": "low", "effect": f"start_timer('t2', {t})"},
        {"trigger": "t2", "source": "low", "target": "empty"},
        {"trigger": "charge", "source": "empty", "target": "empty_charging", "effect": f"start_timer('t3', {t})"},
        {"trigger": "t3", "source": "empty_charging", "target": "low_charging", "effect": f"start_timer('t4', {t})"},
        {"trigger": "t4", "source": "low_charging", "target": "high_charging"},
        {"trigger": "charge", "source": "low", "target": "low_charging", "effect": f"start_timer('t4', {t})"},
        {"trigger": "charge", "source": "high", "target": "high_charging"},
        {"trigger": "stop_charge", "source": "high_charging", "target": "high", "effect": f"start_timer('t1', {t})"},
        {"trigger": "stop_charge", "source": "low_charging", "target": "low", "effect": f"start_timer('t2', {t})"},
    ]
    machine = Machine(name="battery", transitions=transitions, states=states, obj=handlers)
    handlers.stm = machine
    return handlers, machine
