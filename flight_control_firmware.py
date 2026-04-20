# Flight control firmware
#
# STATES WE GOT: "docked", "load_medicine", "travel_to_client", "returning", "deliver"
#
# We have some signals called "arrived" and "returned". These would normally come
# from the drone's gps sensors. To keep this self contained we simulate them with
# a flight timer that fires after a short delay whenever "initate_flight" is called.

import json
from threading import Thread

import paho.mqtt.client as mqtt
from stmpy import Driver, Machine


broker, port = "localhost", 1883

# MQTT TOPICS
MQTT_TOPIC_COMMAND = "ttm4115/group8/drone/command"
MQTT_TOPIC_STATUS = "ttm4115/group8/drone/status"
MQTT_TOPIC_DISPLAY = "ttm4115/group8/drone/display"

FLIGHT_DURATION_MS = 10 * 1000
TIMEOUT_DURATION_MS = 3 * 60 * 1000


class FlightControl:

    def on_init(self):
        pass

    def send_status(self, status):
        pass

    def display(self, message):
        pass

    def open_storage(self):
        pass

    def close_storage(self):
        pass

    def land(self):
        pass

    def init_flight(self):
        pass

    # ---- TRANSITION EFFECTS (TERMINAL UI) ----

    def start_loading(self):
        pass

    def cancel_to_docked(self):
        pass

    def start_travel(self, client_loc="client"):
        pass

    def cancel_to_returning(self):
        pass

    def arrive_at_client(self):
        pass

    def deliver_complete(self):
        pass

    def deliver_timeout(self):
        pass

    def arrive_at_home(self):
        pass


# ---- STATES / TRANSITIONS ----

# Initial transition
t0 = {
    "source": "initial",
    "target": "docked",
    "effect": "on_init()",
}

# State for docked: new order -> load medicines
t1 = {
    "trigger": "new_order",
    "source": "docked",
    "target": "loading",
    "effect": "start_loading",
}

# Load medicine -- cancel --> Docked
t2 = {
    "trigger": "cancel",
    "source": "load_medicine",
    "target": "docked",
    "effect": "cancel_to_docked",
}

# Load medicine -- medicine_loaded --> Travel to client
t3 = {
    "trigger": "medicine_loaded",
    "source": "load_medicine",
    "target": "travel_to_client",
    "effect": "start_travel(*)",
}

# Travel to client -- cancel --> Returning
t4 = {
    "trigger": "cancel",
    "source": "travel_to_client",
    "target": "returning",
    "effect": "cancel_to_returning",
}

# Travel to client -- arrived --> Deliver
t5 = {
    "trigger": "flight_done_client",
    "source": "travel_to_client",
    "target": "deliver",
    "effect": "arrive_at_client; start_timer('delivery_timeout', {})".format(TIMEOUT_DURATION_MS),
}

# Deliver -- delivery_completed --> Returning
t6 = {
    "trigger": "delivery_completed",
    "source": "deliver",
    "target": "returning",
    "effect": "stop_timer('delivery_timeout'); deliver_complete",
}

# Deliver -- t1 (timeout) --> Returning
t7 = {
    "trigger": "delivery_timeout",
    "source": "deliver",
    "target": "returning",
    "effect": "deliver_timeout",
}

# Returning -- returned --> Docked
t8 = {
    "trigger": "flight_done_home",
    "source": "returning",
    "target": "docked",
    "effect": "arrive_at_home",
}


# ---- CREATE STATE MACHINE ----

flight_control = FlightControl()

flight_control_machine = Machine(
    name="flight_control_machine",
    transitions=[t0, t1, t2, t3, t4, t5, t6, t7, t8],
    obj=flight_control,
)

flight_control.stm = flight_control_machine


# ---- CLIENT SETUP ----

class DroneMQTTClient(mqtt.Client):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_connect(self, client, userdata, flags, rc):
        pass

    def on_message(self, client, userdata, msg):
        pass


# ---- MQTT DRIVER SETUP ----

if __name__ == "__main__":
    mqtt_driver = Driver()
    mqtt_driver.add_machine(flight_control_machine)

    mqtt_client = DroneMQTTClient()
    flight_control_machine.mqtt_client = mqtt_client
    mqtt_client.stm = mqtt_driver

    mqtt_driver.start(keep_active=True)
    mqtt_client.start(broker, port)
