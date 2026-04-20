import tkinter as tk
from tkinter import ttk
import paho.mqtt.client as mqtt
import json
from datetime import datetime

BROKER = "mqtt20.iik.ntnu.no"
PORT = 1883
TEAM = "team08"
TOPIC_CTRL = f"{TEAM}/hospital/control"
TOPIC_DISP = f"{TEAM}/hospital/display"

DRONES = [
    {"id": "drone-01", "name": "Drone 01", "status": "idle",      "battery": "92%",  "location": "Hangar A"},
    {"id": "drone-02", "name": "Drone 02", "status": "loaded",    "battery": "78%",  "location": "Ward 3"},
    {"id": "drone-03", "name": "Drone 03", "status": "returning", "battery": "45%",  "location": "In transit"},
    {"id": "drone-04", "name": "Drone 04", "status": "idle",      "battery": "100%", "location": "Hangar B"},
    {"id": "drone-05", "name": "Drone 05", "status": "idle",      "battery": "61%",  "location": "Charging bay"},
]

class DroneApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Hospital Drone Control")
        self.root.geometry("700x500")
        self.selected = None

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.username_pw_set(TEAM)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.connect(BROKER, PORT)
        self.mqtt_client.loop_start()

        self.build_ui()

    def build_ui(self):
        # Top label
        tk.Label(self.root, text="Hospital Drone Control", font=("Helvetica", 16, "bold")).pack(pady=(16, 4))

        main = tk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=16, pady=8)

        # Left — drone list
        left = tk.Frame(main, width=280)
        left.pack(side="left", fill="y", padx=(0, 8))
        tk.Label(left, text="All drones", font=("Helvetica", 11), fg="gray").pack(anchor="w", pady=(0, 6))

        self.drone_buttons = {}
        for drone in DRONES:
            btn = tk.Button(
                left,
                text=f"{drone['name']}  —  {drone['status']}  ·  {drone['location']}",
                anchor="w",
                relief="flat",
                bg="#f5f5f5",
                padx=12, pady=8,
                command=lambda d=drone: self.select_drone(d)
            )
            btn.pack(fill="x", pady=2)
            self.drone_buttons[drone["id"]] = btn

        # Right — detail panel
        right = tk.Frame(main, bg="#f0f0f0", relief="flat", bd=1)
        right.pack(side="left", fill="both", expand=True)

        self.detail_label = tk.Label(right, text="No drone selected", fg="gray", bg="#f0f0f0", font=("Helvetica", 11))
        self.detail_label.pack(pady=20)

        self.detail_frame = tk.Frame(right, bg="#f0f0f0")

        self.name_label    = tk.Label(self.detail_frame, font=("Helvetica", 14, "bold"), bg="#f0f0f0")
        self.status_label  = tk.Label(self.detail_frame, font=("Helvetica", 10), fg="gray", bg="#f0f0f0")
        self.battery_label = tk.Label(self.detail_frame, font=("Helvetica", 10), fg="gray", bg="#f0f0f0")

        self.name_label.pack(anchor="w", padx=16, pady=(16, 2))
        self.status_label.pack(anchor="w", padx=16)
        self.battery_label.pack(anchor="w", padx=16, pady=(0, 12))

        btn_frame = tk.Frame(self.detail_frame, bg="#f0f0f0")
        btn_frame.pack(anchor="w", padx=16, pady=8)

        tk.Button(btn_frame, text="Medicine loaded", command=lambda: self.send_command("medicine_loaded"),
                  bg="#d4edda", relief="flat", padx=10, pady=6).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Return", command=lambda: self.send_command("return"),
                  bg="#f8d7da", relief="flat", padx=10, pady=6).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Back", command=self.deselect,
                  relief="flat", padx=10, pady=6).pack(side="left")

        # Log
        log_frame = tk.Frame(self.root)
        log_frame.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(log_frame, text="Activity log", font=("Helvetica", 10), fg="gray").pack(anchor="w")
        self.log_box = tk.Text(log_frame, height=6, state="disabled", font=("Courier", 10), bg="#fafafa", relief="flat")
        self.log_box.pack(fill="x")

    def select_drone(self, drone):
        self.selected = drone
        self.detail_label.pack_forget()
        self.detail_frame.pack(fill="both", expand=True)
        self.name_label.config(text=drone["name"])
        self.status_label.config(text=f"Status: {drone['status']}  ·  {drone['location']}")
        self.battery_label.config(text=f"Battery: {drone['battery']}")
        for d in DRONES:
            self.drone_buttons[d["id"]].config(bg="#f5f5f5")
        self.drone_buttons[drone["id"]].config(bg="#cce5ff")
        self.mqtt_client.publish(TOPIC_CTRL, json.dumps({"command": "select_drone", "drone": drone["id"]}))
        self.add_log(f"Selected {drone['name']}")

    def deselect(self):
        self.selected = None
        self.detail_frame.pack_forget()
        self.detail_label.pack(pady=20)
        for d in DRONES:
            self.drone_buttons[d["id"]].config(bg="#f5f5f5")
        self.mqtt_client.publish(TOPIC_CTRL, json.dumps({"command": "back"}))
        self.add_log("Back to overview")

    def send_command(self, cmd):
        if not self.selected:
            return
        self.mqtt_client.publish(TOPIC_CTRL, json.dumps({
            "command": cmd,
            "drone": self.selected["id"]
        }))
        self.add_log(f"{self.selected['name']}: {cmd} → published")

    def add_log(self, message):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("1.0", f"{now}  {message}\n")
        self.log_box.config(state="disabled")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_client.subscribe(TOPIC_DISP)
        self.add_log(f"Connected to broker ({reason_code})")

    def on_message(self, client, userdata, msg):
        payload = json.loads(msg.payload.decode())
        self.add_log(f"Received: {payload.get('status', '')} {payload.get('drone', '')}")


root = tk.Tk()
app = DroneApp(root)
root.mainloop()