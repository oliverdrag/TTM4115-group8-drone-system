"""Batteri håndterings tilstandsmaskin (drone side).

Speiler  `stm Battery Management` diagramet: seks tilstander og fire navngitte
timere. Transisjoner er ordrette effektr fra diagramet, pluss en enkelt
ekstra `_publish_state()` entry aksjon per tilstand så flåte manageren ser
transisjonene over MQTT.

Triggere fra flåte manageren: `charge`, `stop_charge`.
Triggere internt:              `t1`, `t2`, `t3`, `t4` (timere).
"""

import logging
from typing import Callable

from stmpy import Machine


log = logging.getLogger("battery")


class BatteryManagement:
    """Tilstandsmaskin  tilbakekall. Holder bare  forbigåande referansar; STM
    instansen er festa som `self.stm` av driver oppsettet."""

    def __init__(self, drone_id: str, tick_ms: int, publish: Callable[[str], None]):
        self.drone_id = drone_id
        self.tick_ms = tick_ms
        self.publish = publish
        self.stm: Machine | None = None

    # ---- tilstand entry aksjoner: hver tilstand publiserer navet sitt -------------
    def enter_high(self):
        log.info("[%s] battery: HIGH", self.drone_id)
        self.publish("high")

    def enter_low(self):
        log.info("[%s] battery: LOW", self.drone_id)
        self.publish("low")

    def enter_empty(self):
        log.info("[%s] battery: EMPTY (drone unavailable)", self.drone_id)
        self.publish("empty")

    def enter_empty_charging(self):
        log.info("[%s] battery: EMPTY-CHARGING", self.drone_id)
        self.publish("empty_charging")

    def enter_low_charging(self):
        log.info("[%s] battery: LOW-CHARGING (drone available)", self.drone_id)
        self.publish("low_charging")

    def enter_high_charging(self):
        log.info("[%s] battery: HIGH-CHARGING", self.drone_id)
        self.publish("high_charging")


def build_machine(drone_id: str, tick_ms: int, publish: Callable[[str], None]) -> tuple[BatteryManagement, Machine]:
    handlers = BatteryManagement(drone_id, tick_ms, publish)

    # One state per block in the diagram.
    states = [
        {"name": "high",            "entry": "enter_high"},
        {"name": "low",             "entry": "enter_low"},
        {"name": "empty",           "entry": "enter_empty"},
        {"name": "empty_charging",  "entry": "enter_empty_charging"},
        {"name": "low_charging",    "entry": "enter_low_charging"},
        {"name": "high_charging",   "entry": "enter_high_charging"},
    ]

    t = str(tick_ms)

    transitions = [
        # Initial state is High; arm t1 so it will eventually discharge.
        {"source": "initial",         "target": "high",           "effect": f"start_timer('t1', {t})"},

        # Discharge path: High → Low → Empty.
        {"trigger": "t1", "source": "high", "target": "low",      "effect": f"start_timer('t2', {t})"},
        {"trigger": "t2", "source": "low",  "target": "empty",    "effect": ""},

        # Charging side.
        {"trigger": "charge",      "source": "empty", "target": "empty_charging", "effect": f"start_timer('t3', {t})"},
        {"trigger": "t3",          "source": "empty_charging", "target": "low_charging", "effect": f"start_timer('t4', {t})"},
        {"trigger": "t4",          "source": "low_charging",   "target": "high_charging"},
        {"trigger": "charge",      "source": "low",   "target": "low_charging",  "effect": f"start_timer('t4', {t})"},
        {"trigger": "charge",      "source": "high",  "target": "high_charging"},

        # Leave the dock mid-charge.
        {"trigger": "stop_charge", "source": "high_charging", "target": "high", "effect": f"start_timer('t1', {t})"},
        {"trigger": "stop_charge", "source": "low_charging",  "target": "low",  "effect": f"start_timer('t2', {t})"},
    ]

    machine = Machine(name="battery", transitions=transitions, states=states, obj=handlers)
    handlers.stm = machine
    return handlers, machine
