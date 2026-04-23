"""Flight control state machine (drone side).

Verbatim implementation of the Flight Control diagram in the spec, rewired
so that the `arrived` and `returned` signals come from the navigation
module instead of a stubbed flight-duration timer.

Triggers from the application server: `new_order`, `medicine_loaded`,
`cancel`, `delivery_completed`.
Triggers internal:                     `arrived`, `returned`, `t1` (delivery
timeout).
"""

import logging
from typing import Callable, Optional

from stmpy import Machine

from .navigation_module import NavigationModule


log = logging.getLogger("flight_control")


class FlightControl:
    def __init__(
        self,
        drone_id: str,
        delivery_timeout_ms: int,
        nav: NavigationModule,
        publish_status: Callable[[str], None],
        publish_display: Callable[[str], None],
        publish_event: Callable[[str, dict], None],
    ):
        self.drone_id = drone_id
        self.delivery_timeout_ms = delivery_timeout_ms
        self.nav = nav
        self.publish_status = publish_status
        self.publish_display = publish_display
        self.publish_event = publish_event

        self.stm: Optional[Machine] = None
        self.current_route: list[tuple[int, int]] = []
        self.current_destination: Optional[tuple[int, int]] = None

    # ---- hardware stubs -----------------------------------------------
    def open_storage(self):
        log.info("[%s] storage hatch: OPEN", self.drone_id)

    def close_storage(self):
        log.info("[%s] storage hatch: CLOSED", self.drone_id)

    def land(self):
        log.info("[%s] landed", self.drone_id)

    # ---- helpers ------------------------------------------------------
    def on_init(self):
        log.info("[%s] flight control initialized, docked", self.drone_id)
        self.publish_status("docked")
        self.publish_display("docked")

    def send_status(self, status: str):
        self.publish_status(status)

    def display(self, message: str):
        self.publish_display(message)

    # ---- transition effects (named to match the diagram) -------------
    def effect_new_order(self):
        self.publish_display("load medicine")
        self.publish_status("loading medicine")

    def effect_cancel_loading(self):
        self.publish_status("docking")
        self.publish_display("docking")

    def effect_medicine_loaded(self, destination, route):
        self.current_destination = (int(destination[0]), int(destination[1]))
        self.current_route = [(int(x), int(y)) for x, y in route]
        self.close_storage()
        self.nav.fly_to_client(self.current_route)
        self.publish_status("flight started")
        self.publish_display("flight started")

    def effect_cancel_travel(self):
        self.nav.abort()
        self.nav.fly_home()
        self.publish_status("cancel, returning")
        self.publish_display("returning")

    def effect_arrived(self):
        self.publish_status("arrived, unloading medicine")
        self.publish_display("pick up medicine")
        self.open_storage()
        self.publish_event("arrived_at_client", {})

    def effect_delivery_completed(self):
        self.close_storage()
        self.publish_display("returning")
        self.nav.fly_home()
        self.publish_status("delivered, returning")

    def effect_delivery_timeout(self):
        self.close_storage()
        self.publish_display("returning")
        self.nav.fly_home()
        self.publish_status("timed out, returning")

    def effect_returned(self):
        self.land()
        self.publish_status("returned")
        self.open_storage()
        self.publish_display("returned, check for remaining medicine")
        self.publish_event("returned_home", {})

    def effect_cancel_deliver(self):
        # cancel button pressed while waiting at the client (same outcome as timeout)
        self.effect_delivery_timeout()


def build_machine(
    drone_id: str,
    delivery_timeout_ms: int,
    nav: NavigationModule,
    publish_status: Callable[[str], None],
    publish_display: Callable[[str], None],
    publish_event: Callable[[str, dict], None],
) -> tuple[FlightControl, Machine]:
    handlers = FlightControl(
        drone_id=drone_id,
        delivery_timeout_ms=delivery_timeout_ms,
        nav=nav,
        publish_status=publish_status,
        publish_display=publish_display,
        publish_event=publish_event,
    )

    transitions = [
        {"source": "initial", "target": "docked", "effect": "on_init"},

        # docked → load_medicine
        {"trigger": "new_order", "source": "docked", "target": "load_medicine", "effect": "effect_new_order"},

        # load_medicine ↔ docked (cancel)
        {"trigger": "cancel", "source": "load_medicine", "target": "docked", "effect": "effect_cancel_loading"},

        # load_medicine → travel_to_client
        {
            "trigger": "medicine_loaded",
            "source": "load_medicine",
            "target": "travel_to_client",
            "effect": "effect_medicine_loaded(*)",
        },

        # travel_to_client → returning (cancel)
        {"trigger": "cancel", "source": "travel_to_client", "target": "returning", "effect": "effect_cancel_travel"},

        # travel_to_client → deliver (arrived)
        {
            "trigger": "arrived",
            "source": "travel_to_client",
            "target": "deliver",
            "effect": "effect_arrived; start_timer('delivery_timeout', {})".format(delivery_timeout_ms),
        },

        # deliver → returning (delivery_completed)
        {
            "trigger": "delivery_completed",
            "source": "deliver",
            "target": "returning",
            "effect": "stop_timer('delivery_timeout'); effect_delivery_completed",
        },

        # deliver → returning (timeout)
        {"trigger": "delivery_timeout", "source": "deliver", "target": "returning", "effect": "effect_delivery_timeout"},

        # deliver → returning (cancel)
        {"trigger": "cancel", "source": "deliver", "target": "returning", "effect": "effect_cancel_deliver"},

        # returning → docked (returned)
        {"trigger": "returned", "source": "returning", "target": "docked", "effect": "effect_returned"},
    ]

    machine = Machine(name="flight_control", transitions=transitions, obj=handlers)
    handlers.stm = machine
    return handlers, machine
