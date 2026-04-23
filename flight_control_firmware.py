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
        print("Flight control firmware initialized. Drone is docked.")
        self.client_loc = None
        self.send_status("docked")
        self.display("docked")

    def send_status(self, status):
        payload = json.dumps({"status": status})
        print("STATUS -> {}".format(status))
        self.mqtt_client.publish(MQTT_TOPIC_STATUS, payload)

    def display(self, message):
        payload = json.dumps({"display": message})
        print("DISPLAY: {}".format(message))
        self.mqtt_client.publish(MQTT_TOPIC_DISPLAY, payload)

    def open_storage(self):
        print("[hardware] storage hatch opened")

    def close_storage(self):
        print("[hardware] storage hatch closed")

    def land(self):
        print("[hardware] drone landed")

    def init_flight(self, location):
        if location == "home":
            self.stm.start_timer("flight_done_home", FLIGHT_DURATION_MS)
        else:
            self.stm.start_timer("flight_done_client", FLIGHT_DURATION_MS)

    # ---- TRANSITION EFFECTS (TERMINAL UI) ----

    def start_loading(self):
        self.display("load medicine")
        self.send_status("loading medicine")

    def cancel_to_docked(self):
        self.send_status("docking")
        self.display("docking")

    def start_travel(self, client_loc="client"):
        self.client_loc = client_loc
        self.close_storage()
        self.initiate_flight(client_loc)
        self.send_status("flight started")
        self.display("flight started")

    def cancel_to_returning(self):
        self.initiate_flight("home")
        self.send_status("cancel, returning")
        self.display("returning")

    def arrive_at_client(self):
        self.send_status("arrived, unloading medicine")
        self.display("pick up medicine")
        self.open_storage()

    def deliver_complete(self):
        self.close_storage()
        self.display("returning")
        self.initiate_flight("home")
        self.send_status("delivered, returning")

    def deliver_timeout(self):
        self.close_storage()
        self.display("returning")
        self.initiate_flight("home")
        self.send_status("timed out, returning")

    def arrive_at_home(self):
        self.land()
        self.send_status("returned")
        self.open_storage()
        self.display("returned, check for remaining medicine")


# ---- STATES / TRANSITIONS ----

# Initial transition
t0 = {
    "source": "initial",
    "target": "docked",
    "effect": "on_init()",
}

# State for stasjonært/Docked: ny ordre ->last medisiner
t1 = {
    "trigger": "new_order",
    "source": "docked",
    "target": "loading",
    "effect": "start_loading",
}

# Last medisin->avbryt->STasjonert
t2 = {
    "trigger": "cancel",
    "source": "load_medicine",
    "target": "docked",
    "effect": "cancel_to_docked",
}

# Last medisin->medisin lastet->Fly to person i nød
t3 = {
    "trigger": "medicine_loaded",
    "source": "load_medicine",
    "target": "travel_to_client",
    "effect": "start_travel(*)",
}

# Person i nød->avbryt->Returning
t4 = {
    "trigger": "cancel",
    "source": "travel_to_client",
    "target": "returning",
    "effect": "cancel_to_returning",
}

# Person i nød->fremme->levering
t5 = {
    "trigger": "flight_done_client",
    "source": "travel_to_client",
    "target": "deliver",
    "effect": "arrive_at_client; start_timer('delivery_timeout', {})".format(TIMEOUT_DURATION_MS),
}

# Levering->delivery_completed->DRa tilbake
t6 = {
    "trigger": "delivery_completed",
    "source": "deliver",
    "target": "returning",
    "effect": "stop_timer('delivery_timeout'); deliver_complete",
}

# Levering- t1 (timeout)-> Dra tilbake
t7 = {
    "trigger": "delivery_timeout",
    "source": "deliver",
    "target": "returning",
    "effect": "deliver_timeout",
}

# Drar tilbake->kommet tilbake-> Stasjonært
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

    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        print("on_connect(): {}".format(reason_code))


    def on_message(self, client, userdata, msg):
        print("on_message(): topic: {} payload: {}".format(msg.topic, msg.payload.decode("utf-8")))


        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            print("Invalid JSON payload, ignoring message.")
            return
        
        if msg.topic != MQTT_TOPIC_COMMAND:
            return
        

        command = payload.get("command", "")


        if command == "new_order":
            self.stm_driver.send("new_order", "flight_control")
        elif command == "medicine_loaded":
            client_loc = payload.get("client_loc", "client")
            self.stm_driver.send("medicine_loaded", "flight_control", args=[client_loc])
        elif command == "cancel":
            self.stm_driver.send("cancel", "flight_control")
        elif command == "delivery_completed":
            self.stm_driver.send("delivery_completed", "flight_control")
        else:
            print("Unknown command: {}".format(command))

    def start(self, broker, port):
        print("Connecting to {}:{}".format(broker, port))
        self.client.connect(broker, port)
        self.client.subscribe(MQTT_TOPIC_COMMAND)
        try:
            thread = Thread(target=self.client.loop_forever)
            thread.start()
        except KeyboardInterrupt:
            print("Interrupted")
            self.client.disconnect()


# ---- MQTT DRIVER SETUP ----

if __name__ == "__main__":
    mqtt_driver = Driver()
    mqtt_driver.add_machine(flight_control_machine)

    mqtt_client = DroneMQTTClient()
    flight_control_machine.mqtt_client = mqtt_client
    mqtt_client.stm = mqtt_driver

    mqtt_driver.start(keep_active=True)
    mqtt_client.start(broker, port)
