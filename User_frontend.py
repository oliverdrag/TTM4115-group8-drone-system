import json
import os
import tkinter as tk
from stmpy import Machine, Driver
import paho.mqtt.client as mqtt

broker, port = "mqtt20.iik.ntnu.no", 1883

# ---- MQTT TOPICS ----
MQTT_TOPIC_CONTROL = "ttm4115/group8/user/control"
MQTT_TOPIC_DISPLAY = "ttm4115/group8/user/display"


# ---- USER MQTT CLIENT ----
class UserMQTTClient:

    def __init__(self, frontend):
        self.frontend = frontend
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print("Connected to MQTT broker with reason code {}".format(reason_code))
        client.subscribe(MQTT_TOPIC_DISPLAY)

    def on_message(self, client, userdata, msg):
        print("on_message(): topic: {} payload: {}".format(msg.topic, msg.payload.decode("utf-8")))

        if msg.topic != MQTT_TOPIC_DISPLAY:
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"display": msg.payload.decode("utf-8")}

        command = payload.get("command", "").strip().lower()
        if command == "cancelled_by_system":
            self.frontend.on_cancelled_by_system()
            return

        status = payload.get("display", payload.get("status", ""))
        if not status:
            return

        self.frontend.on_downstream_status(status)

    def publish_control(self, command, **payload):
        message = {"command": command}
        message.update(payload)
        self.client.publish(MQTT_TOPIC_CONTROL, json.dumps(message))

    def start(self, broker, port):
        print("Connecting to {}:{}".format(broker, port))
        self.client.connect(broker, port)
        self.client.loop_start()
        

# ---- USER FRONTEND ----
class UserFrontend:

    def load_images(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        image_dir = os.path.join(base_dir, "images")
        self.idle_image = tk.PhotoImage(file=os.path.join(image_dir, "idle_image.png"))
        self.delivering_image = tk.PhotoImage(file=os.path.join(image_dir, "delivering_image.png"))

    def set_status(self, status):
        self.status_text.set(status)

    def show_frame_with_clear(self, frame_name, clear=False):
        if clear:
            self.clear_form()
        self.show_frame(frame_name)
    
    # ---- UI EVENT HANDLERS ----
    def on_button_cancel(self):
        self.stm.send('cancel')
    
    def on_button_order_drone(self):
        self.stm.send('order_drone')
        
    def on_button_send_info(self):
        self.stm.send('send_info_clicked')
        
    def on_button_refresh(self):
        self.stm.send('refresh')
    
    def on_button_medicine_received(self):
        self.stm.send('medicine_received')

    def on_cancelled_by_system(self):
        if self.current_state == 'drone_delivering':
            self.stm.send('cancelled_by_system')

    def on_downstream_status(self, status):
        self.store_display_status(status)
        if self.current_state == 'drone_delivering':
            self.stm.send('refresh')
        
    def on_button_exit(self):
        self.is_shutting_down = True
        if self.mqtt_client is not None:
            self.mqtt_client.client.loop_stop()
            self.mqtt_client.client.disconnect()
        if self.stm is not None and getattr(self.stm, "_driver", None) is not None:
            self.stm.driver.stop()
        self.root.quit()
        self.root.destroy()

    # ---- UI HELPERS AND LAYOUT ----
    def validate_order_form(self):
        return all((self.entry_name.get().strip(), self.entry_location.get().strip(), self.entry_medicine.get().strip()))

    def clear_form(self):
        for entry in (self.entry_name, self.entry_location, self.entry_medicine):
            entry.delete(0, tk.END)

    def show_frame(self, frame_name):
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[frame_name].pack(fill=tk.BOTH, expand=True, pady=10)

    def configure_window(self):
        self.root.title("User Frontend")
        self.root.geometry("380x440")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_button_exit)

    def build_status_area(self):
        self.status_text = tk.StringVar(value="Idle")
        self.status_label = tk.Label(self.root, textvariable=self.status_text, fg="#2b2b2b")
        self.status_label.pack(pady=(8, 4))

    def build_start_view(self):
        tk.Label(self.start_frame, image=self.idle_image).pack(pady=8)
        self.button_order_drone = tk.Button(self.start_frame, text="Order Drone", width=18, command=self.on_button_order_drone)
        self.button_order_drone.pack(pady=4)
        self.button_exit_idle = tk.Button(self.start_frame, text="Exit", width=18, command=self.on_button_exit)
        self.button_exit_idle.pack(pady=4)

    def build_labeled_entry(self, label):
        tk.Label(self.info_frame, text=label).pack(anchor="w", padx=40)
        entry = tk.Entry(self.info_frame, width=32)
        entry.pack(padx=40, pady=(0, 8))
        return entry

    def build_enter_info_view(self):
        self.entry_name = self.build_labeled_entry("Name")
        self.entry_location = self.build_labeled_entry("Location")
        self.entry_medicine = self.build_labeled_entry("Medicine")
        self.entry_medicine.pack_configure(pady=(0, 10))

        info_buttons = tk.Frame(self.info_frame)
        info_buttons.pack(pady=4)
        self.button_send_info = tk.Button(info_buttons, text="Send Info", width=12, command=self.on_button_send_info)
        self.button_send_info.pack(side=tk.LEFT, padx=4)
        self.button_cancel = tk.Button(info_buttons, text="Cancel", width=12, command=self.on_button_cancel)
        self.button_cancel.pack(side=tk.LEFT, padx=4)
        self.button_exit_info = tk.Button(self.info_frame, text="Exit", width=26, command=self.on_button_exit)
        self.button_exit_info.pack(pady=6)

    def build_delivery_view(self):
        tk.Label(self.delivery_frame, image=self.delivering_image).pack(pady=8)
        actions = [
            ("Refresh", self.on_button_refresh, "button_refresh"),
            ("Medicine Received", self.on_button_medicine_received, "button_medicine_received"),
            ("Cancel", self.on_button_cancel, "button_cancel_delivery"),
            ("Exit", self.on_button_exit, "button_exit_delivery"),
        ]
        for text, callback, attr in actions:
            button = tk.Button(self.delivery_frame, text=text, width=18, command=callback)
            button.pack(pady=4)
            setattr(self, attr, button)

    def build_views(self):
        self.start_frame = tk.Frame(self.root)
        self.info_frame = tk.Frame(self.root)
        self.delivery_frame = tk.Frame(self.root)
        self.frames = {
            "idle": self.start_frame,
            "enter_info": self.info_frame,
            "drone_delivering": self.delivery_frame,
        }

        self.build_start_view()
        self.build_enter_info_view()
        self.build_delivery_view()
    
    def display(self):
        self.configure_window()
        self.build_status_area()
        self.build_views()

        self.show_frame("idle")
        
    def __init__(self):
        self.stm = None
        self.mqtt_client = None
        self.is_shutting_down = False
        self.current_state = 'idle'
        self.current_order = {}
        self.latest_display_status = "Idle"
        self.root = tk.Tk()
        self.load_images()
        self.display()
        
    # ---- STATE ENTRY AND EFFECTS ----
    def show_idle(self):
        self.current_state = 'idle'
        if self.latest_display_status == "delivery cancelled by system":
            self.set_status("delivery cancelled by system")
        else:
            self.set_status("Idle")
        self.show_frame_with_clear("idle", clear=True)

    def show_enter_info(self):
        self.current_state = 'enter_info'
        self.set_status("Enter delivery information")
        self.show_frame_with_clear("enter_info")

    def show_drone_delivering(self):
        self.current_state = 'drone_delivering'
        status_to_show = self.latest_display_status if self.latest_display_status != "Idle" else "Drone is delivering medicine"
        self.set_status(status_to_show)
        self.show_frame_with_clear("drone_delivering")

    def prepare_order_from_form(self):
        if not self.validate_order_form():
            self.show_alert("Please fill in Name, Location, and Medicine.")
            return

        self.current_order = {
            "name": self.entry_name.get().strip(),
            "location": self.entry_location.get().strip(),
            "medicine": self.entry_medicine.get().strip(),
        }
        self.stm.send('send_info')

    def request_drone(self):
        if self.mqtt_client is not None:
            self.mqtt_client.publish_control(
                "new_order",
                name=self.current_order.get("name", ""),
                location=self.current_order.get("location", ""),
                medicine=self.current_order.get("medicine", ""),
            )
        self.show_alert(
            f"Request sent for {self.current_order.get('name', 'user')} "
            f"to {self.current_order.get('location', 'location')} "
            f"({self.current_order.get('medicine', 'medicine')})."
        )

    def transmit_to_drone(self, message):
        if self.mqtt_client is not None:
            self.mqtt_client.publish_control(message)

    def store_display_status(self, status):
        self.latest_display_status = status

    def handle_refresh_event(self):
        if "cancel" in self.latest_display_status.lower():
            self.stm.send('cancel')
            return
        self.refresh_status()

    def handle_system_cancel(self):
        self.store_display_status("delivery cancelled by system")

    def refresh_status(self):
        self.set_status(self.latest_display_status)

    def show_alert(self, message):
        self.status_text.set(message)

    def run(self):
        self.root.mainloop()
        

transitions = [
    {'source': 'initial', 'target': 'idle'},
    {'trigger': 'order_drone', 'source': 'idle', 'target': 'enter_info', 'effect': 'show_enter_info()'},
    {'trigger': 'cancel', 'source': 'enter_info', 'target': 'idle'},
    {'trigger': 'send_info_clicked', 'source': 'enter_info', 'target': 'enter_info', 'effect': 'prepare_order_from_form()'},
    {'trigger': 'send_info', 'source': 'enter_info', 'target': 'drone_delivering', 'effect': 'request_drone()'},
    {'trigger': 'refresh', 'source': 'drone_delivering', 'target': 'drone_delivering', 'effect': 'handle_refresh_event()'},
    {'trigger': 'medicine_received', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'transmit_to_drone("delivery_completed")'},
    {'trigger': 'cancel', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'transmit_to_drone("cancel")'},
    {'trigger': 'cancelled_by_system', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'handle_system_cancel()'},
]

# ---- STATE DECLARATIONS ----
idle = {'name': 'idle',
            'entry': 'show_idle'}

enter_info = {'name': 'enter_info',
    'entry': 'show_enter_info'}

drone_delivering = {'name': 'drone_delivering',
    'entry': 'show_drone_delivering'}


# ---- MQTT DRIVER SETUP ----

if __name__ == "__main__":
    frontend = UserFrontend()
    stm_frontend = Machine(name='stm_frontend', transitions=transitions, states=[idle, enter_info, drone_delivering], obj=frontend)
    frontend.stm = stm_frontend

    mqtt_driver = Driver()
    mqtt_driver.add_machine(stm_frontend)

    mqtt_client = UserMQTTClient(frontend)
    frontend.mqtt_client = mqtt_client

    mqtt_driver.start(keep_active=True)
    mqtt_client.start(broker, port)
    frontend.run()
