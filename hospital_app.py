import tkinter as tk
from tkinter import filedialog, messagebox
import paho.mqtt.client as mqtt
import json
import csv
import os
from datetime import datetime

BROKER = "mqtt20.iik.ntnu.no"
PORT   = 1883
TEAM   = "team08"
TOPIC_CTRL = f"{TEAM}/hospital/control"
TOPIC_DISP = f"{TEAM}/hospital/display"

DEFAULT_CSV = "drone_log.csv"
CSV_HEADERS = ["timestamp", "event_type", "drone_id", "drone_name",
               "command", "status", "location", "battery", "medicine", "message", "raw_payload"]

DRONES = [
    {"id": "drone-01", "name": "Drone 01", "status": "idle",      "battery": "92%",  "location": "Hangar A", "medicine": ""},
    {"id": "drone-02", "name": "Drone 02", "status": "loaded",    "battery": "78%",  "location": "Ward 3",   "medicine": ""},
    {"id": "drone-03", "name": "Drone 03", "status": "returning", "battery": "45%",  "location": "In transit","medicine": ""},
    {"id": "drone-04", "name": "Drone 04", "status": "idle",      "battery": "100%", "location": "Hangar B", "medicine": ""},
    {"id": "drone-05", "name": "Drone 05", "status": "idle",      "battery": "61%",  "location": "Charging bay","medicine": ""},
]

STATUS_COLORS = {
    "idle":      "#e8f5e9",
    "loaded":    "#fff9c4",
    "returning": "#fce4ec",
    "returned":  "#e8f5e9",
    "requested": "#ede7f6",
    "charging":  "#e3f2fd",
}


class DroneApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Hospital Drone Control")
        self.root.geometry("900x680")
        self.selected = None
        self.csv_path = DEFAULT_CSV
        self._init_csv()

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.username_pw_set(TEAM)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.connect(BROKER, PORT)
        self.mqtt_client.loop_start()

        self.build_ui()
        self._log_event("app_start", status="started")

    # ── CSV ───────────────────────────────────────────────────────────────────

    def _init_csv(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

    def _log_event(self, event_type, drone=None, command="", status="",
                   location="", battery="", medicine="", message="", raw_payload=""):
        row = {
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type":  event_type,
            "drone_id":    drone["id"]       if drone else "",
            "drone_name":  drone["name"]     if drone else "",
            "command":     command,
            "status":      status  or (drone["status"]   if drone else ""),
            "location":    location or (drone["location"] if drone else ""),
            "battery":     battery  or (drone["battery"]  if drone else ""),
            "medicine":    medicine or (drone.get("medicine", "") if drone else ""),
            "message":     message,
            "raw_payload": raw_payload,
        }
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)
        self.root.after(0, self._refresh_csv_view)

    def _refresh_csv_view(self):
        self.csv_table.config(state="normal")
        self.csv_table.delete("1.0", "end")
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in reversed(rows[-50:]):
                ts    = row.get("timestamp", "")
                etype = row.get("event_type", "").ljust(14)
                did   = row.get("drone_id", "").ljust(10)
                cmd   = row.get("command", "").ljust(18)
                st    = row.get("status", "").ljust(12)
                med   = row.get("medicine", "").ljust(14)
                msg   = row.get("message", "")
                self.csv_table.insert("end", f"{ts}  {etype}  {did}  {cmd}  {st}  {med}  {msg}\n")
        except Exception as e:
            self.csv_table.insert("end", f"(could not read CSV: {e})\n")
        self.csv_table.config(state="disabled")

    def _export_csv_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile="drone_log.csv", title="Export log as…")
        if not path:
            return
        import shutil; shutil.copy2(self.csv_path, path)
        messagebox.showinfo("Exported", f"Log saved to:\n{path}")
        self._add_log(f"Exported → {os.path.basename(path)}")

    def _change_csv_path(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=self.csv_path, title="Auto-log destination…")
        if not path:
            return
        self.csv_path = path
        self._init_csv()
        self.csv_path_var.set(f"Logging → {os.path.basename(path)}")
        self._add_log(f"CSV path → {os.path.basename(path)}")

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        tk.Label(self.root, text="Hospital Drone Control",
                 font=("Helvetica", 16, "bold")).pack(pady=(14, 2))

        bar = tk.Frame(self.root, bg="#ddeeff")
        bar.pack(fill="x", padx=16, pady=(0, 6))
        self.csv_path_var = tk.StringVar(value=f"Logging → {os.path.basename(self.csv_path)}")
        tk.Label(bar, textvariable=self.csv_path_var, font=("Courier", 9),
                 bg="#ddeeff", fg="#1a4a7a").pack(side="left", padx=8, pady=3)
        tk.Button(bar, text="Change log file…", command=self._change_csv_path,
                  font=("Helvetica", 9), relief="flat", bg="#aaccee", padx=6, pady=2).pack(side="right", padx=(0,4), pady=3)
        tk.Button(bar, text="Export CSV as…", command=self._export_csv_as,
                  font=("Helvetica", 9), relief="flat", bg="#aaeebb", padx=6, pady=2).pack(side="right", padx=4, pady=3)

        main = tk.Frame(self.root)
        main.pack(fill="both", expand=False, padx=16, pady=4)

        left = tk.Frame(main, width=320)
        left.pack(side="left", fill="y", padx=(0, 8))
        tk.Label(left, text="All drones", font=("Helvetica", 11), fg="gray").pack(anchor="w", pady=(0, 4))

        self.drone_buttons = {}
        for drone in DRONES:
            self._make_drone_button(left, drone)

        right = tk.Frame(main, bg="#f0f0f0", relief="flat", bd=1, width=340)
        right.pack(side="left", fill="both", expand=True)

        self.detail_label = tk.Label(right, text="No drone selected",
                                     fg="gray", bg="#f0f0f0", font=("Helvetica", 11))
        self.detail_label.pack(pady=20)

        self.detail_frame = tk.Frame(right, bg="#f0f0f0")
        self.name_label     = tk.Label(self.detail_frame, font=("Helvetica", 14, "bold"), bg="#f0f0f0")
        self.status_label   = tk.Label(self.detail_frame, font=("Helvetica", 10), fg="gray", bg="#f0f0f0")
        self.battery_label  = tk.Label(self.detail_frame, font=("Helvetica", 10), fg="gray", bg="#f0f0f0")
        self.medicine_label = tk.Label(self.detail_frame, font=("Helvetica", 10), fg="#6a0dad", bg="#f0f0f0")

        self.name_label.pack(anchor="w", padx=16, pady=(16, 2))
        self.status_label.pack(anchor="w", padx=16)
        self.battery_label.pack(anchor="w", padx=16, pady=(0, 2))
        self.medicine_label.pack(anchor="w", padx=16, pady=(0, 8))

        btn_frame = tk.Frame(self.detail_frame, bg="#f0f0f0")
        btn_frame.pack(anchor="w", padx=16, pady=8)
        tk.Button(btn_frame, text="Medicine loaded",
                  command=lambda: self._send_command("medicine_loaded"),
                  bg="#d4edda", relief="flat", padx=10, pady=6).pack(side="left", padx=(0,8))
        tk.Button(btn_frame, text="Return",
                  command=lambda: self._send_command("return"),
                  bg="#f8d7da", relief="flat", padx=10, pady=6).pack(side="left", padx=(0,8))
        tk.Button(btn_frame, text="Back", command=self._deselect,
                  relief="flat", padx=10, pady=6).pack(side="left")

        log_frame = tk.Frame(self.root)
        log_frame.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(log_frame, text="Activity log", font=("Helvetica", 10), fg="gray").pack(anchor="w")
        self.log_box = tk.Text(log_frame, height=4, state="disabled",
                               font=("Courier", 10), bg="#fafafa", relief="flat")
        self.log_box.pack(fill="x")

        csv_frame = tk.Frame(self.root)
        csv_frame.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        hdr = tk.Frame(csv_frame)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Live CSV log  (newest first)",
                 font=("Helvetica", 10), fg="gray").pack(side="left")
        tk.Button(hdr, text="↻ Refresh", command=self._refresh_csv_view,
                  font=("Helvetica", 9), relief="flat", bg="#eeeeee", padx=6, pady=1).pack(side="right")
        tk.Label(csv_frame,
                 text="timestamp            event_type      drone_id    command             status        medicine        message",
                 font=("Courier", 8), fg="#aaaaaa", anchor="w").pack(fill="x")
        scroll = tk.Scrollbar(csv_frame)
        scroll.pack(side="right", fill="y")
        self.csv_table = tk.Text(csv_frame, height=8, state="disabled",
                                 font=("Courier", 9), bg="#f8f8f8",
                                 relief="flat", yscrollcommand=scroll.set)
        self.csv_table.pack(fill="both", expand=True)
        scroll.config(command=self.csv_table.yview)

        self._refresh_csv_view()

    def _make_drone_button(self, parent, drone):
        color = STATUS_COLORS.get(drone["status"], "#f5f5f5")
        btn = tk.Button(
            parent,
            text=self._btn_text(drone),
            anchor="w", relief="flat", bg=color, padx=12, pady=7,
            command=lambda d=drone: self._select_drone(d)
        )
        btn.pack(fill="x", pady=2)
        self.drone_buttons[drone["id"]] = btn

    def _btn_text(self, drone):
        med = f"  [{drone['medicine']}]" if drone.get("medicine") else ""
        return f"{drone['name']}  —  {drone['status']}  ·  {drone['location']}{med}"

    def _refresh_drone_button(self, drone):
        color = STATUS_COLORS.get(drone["status"], "#f5f5f5")
        if self.selected and self.selected["id"] == drone["id"]:
            color = "#cce5ff"
        self.drone_buttons[drone["id"]].config(text=self._btn_text(drone), bg=color)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _select_drone(self, drone):
        self.selected = drone
        self.detail_label.pack_forget()
        self.detail_frame.pack(fill="both", expand=True)
        self._update_detail_panel()
        for d in DRONES:
            self._refresh_drone_button(d)
        payload = json.dumps({"command": "select_drone", "drone": drone["id"]})
        self.mqtt_client.publish(TOPIC_CTRL, payload)
        self._add_log(f"Selected {drone['name']}")
        self._log_event("select", drone=drone, command="select_drone", raw_payload=payload)

    def _deselect(self):
        self.selected = None
        self.detail_frame.pack_forget()
        self.detail_label.pack(pady=20)
        for d in DRONES:
            self._refresh_drone_button(d)
        payload = json.dumps({"command": "back"})
        self.mqtt_client.publish(TOPIC_CTRL, payload)
        self._add_log("Back to overview")
        self._log_event("deselect", command="back", raw_payload=payload)

    def _send_command(self, cmd):
        if not self.selected:
            return
        drone = self.selected

        if cmd == "medicine_loaded":
            drone["status"] = "loaded"
        elif cmd == "return":
            drone["status"] = "returning"

        self._refresh_drone_button(drone)
        self._update_detail_panel()

        payload = json.dumps({"command": cmd, "drone": drone["id"]})
        self.mqtt_client.publish(TOPIC_CTRL, payload)
        self._add_log(f"{drone['name']}: {cmd}  →  status: {drone['status']}")
        self._log_event("command", drone=drone, command=cmd, status=drone["status"], raw_payload=payload)

    def _update_detail_panel(self):
        if not self.selected:
            return
        d = self.selected
        self.name_label.config(text=d["name"])
        self.status_label.config(text=f"Status: {d['status']}  ·  {d['location']}")
        self.battery_label.config(text=f"Battery: {d['battery']}")
        med = d.get("medicine", "")
        self.medicine_label.config(text=f"Requested medicine: {med}" if med else "")

    def _add_log(self, message):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("1.0", f"{now}  {message}\n")
        self.log_box.config(state="disabled")

    # ── MQTT callbacks ────────────────────────────────────────────────────────

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_client.subscribe(TOPIC_DISP)
        self.root.after(0, lambda: self._add_log(f"Connected to broker ({reason_code})"))
        self._log_event("broker_connect", status=str(reason_code))

    def on_message(self, client, userdata, msg):
        raw = msg.payload.decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        drone_id = payload.get("drone", "")
        status   = payload.get("status", "")
        location = payload.get("location", "")
        battery  = payload.get("battery", "")
        medicine = payload.get("medicine", "")
        message  = payload.get("message", "")
        command  = payload.get("command", "")
        print("DISPLAY MSG:", payload)

        drone_obj = next((d for d in DRONES if d["id"] == drone_id), None)

        if drone_obj:
            # Request from user UI — handle first so medicine is always saved
            if command == "request" or status == "requested":
                drone_obj["status"] = "requested"
                if medicine:
                    drone_obj["medicine"] = medicine

            # Drone returned → reset to idle and clear medicine
            elif status == "returned" or command == "returned":
                drone_obj["status"] = "idle"
                drone_obj["location"] = "Hangar"
                drone_obj["medicine"] = ""

            # All other status updates from drone or state machine
            else:
                if status in ["requested", "loaded", "returning", "returned", "idle"]:
                    drone_obj["status"] = status
                if command == "medicine_loaded":
                    drone_obj["status"] = "loaded"
                elif command == "return":
                    drone_obj["status"] = "returning"

            # Always update location and battery if provided
            if location:
                drone_obj["location"] = location
            if battery:
                drone_obj["battery"] = battery

        topic_short = msg.topic.split("/")[-1]
        med_info = f"  medicine: {medicine}" if medicine else ""
        log_msg = f"[{topic_short}] {status or command}  {drone_id}{med_info}"
        self.root.after(0, lambda m=log_msg: self._add_log(m))

        if drone_obj:
            self.root.after(0, lambda d=drone_obj: self._refresh_drone_button(d))
            if self.selected and self.selected["id"] == drone_id:
                self.root.after(0, self._update_detail_panel)

        self._log_event(
            "mqtt_in",
            drone=drone_obj,
            command=command,
            status=status or (drone_obj["status"] if drone_obj else ""),
            location=location,
            battery=battery,
            medicine=medicine,
            message=message,
            raw_payload=raw,
        )


root = tk.Tk()
app = DroneApp(root)
root.mainloop()