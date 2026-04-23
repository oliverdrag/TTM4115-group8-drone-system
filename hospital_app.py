import csv
import json
import logging
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Optional

import requests
from websocket import WebSocketApp

import ui_theme as theme

log = logging.getLogger("hospital_app")

APP_SERVER_URL = os.environ.get("APP_SERVER_URL", "http://localhost:5000")
WS_URL = APP_SERVER_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/live"

DEFAULT_CSV = "drone_log.csv"
CSV_HEADERS = [
    "timestamp", "event_type", "drone_id", "drone_name",
    "command", "status", "location", "battery", "medicine", "message", "raw_payload",
]


class DroneApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        theme.apply_window(self.root, "Hospital Drone Control", 1100, 820, resizable=True)
        self.selected: Optional[dict] = None
        self.drones: dict[str, dict] = {}
        self.watched_drone_id: Optional[str] = None
        self.csv_path = DEFAULT_CSV
        self._init_csv()
        self.ws_app: Optional[WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._stop = False
        self.build_ui()
        self._log_event("app_start", status="started")
        self._seed_from_rest()
        self._fetch_viewer_state()
        self._start_ws()

    def _init_csv(self) -> None:
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

    def _log_event(self, event_type: str, drone: Optional[dict] = None, command: str = "",
                   status: str = "", location: str = "", battery: str = "", medicine: str = "",
                   message: str = "", raw_payload: str = "") -> None:
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "drone_id": drone["id"] if drone else "",
            "drone_name": drone["name"] if drone else "",
            "command": command,
            "status": status or (drone.get("status", "") if drone else ""),
            "location": location or (self._loc_str(drone) if drone else ""),
            "battery": battery or (drone.get("battery_state", "") if drone else ""),
            "medicine": medicine or (drone.get("medicine", "") if drone else ""),
            "message": message,
            "raw_payload": raw_payload,
        }
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)
        self.root.after(0, self._refresh_csv_view)

    def _loc_str(self, drone: Optional[dict]) -> str:
        if not drone:
            return ""
        return f"({drone.get('x', '?')}, {drone.get('y', '?')})"

    def _refresh_csv_view(self) -> None:
        self.csv_table.config(state="normal")
        self.csv_table.delete("1.0", "end")
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in reversed(rows[-50:]):
                ts = row.get("timestamp", "")
                etype = (row.get("event_type", "") or "").ljust(14)
                did = (row.get("drone_id", "") or "").ljust(10)
                cmd = (row.get("command", "") or "").ljust(18)
                st = (row.get("status", "") or "").ljust(24)
                med = (row.get("medicine", "") or "").ljust(14)
                msg = row.get("message", "")
                self.csv_table.insert("end", f"{ts}  {etype}  {did}  {cmd}  {st}  {med}  {msg}\n")
        except Exception as e:
            self.csv_table.insert("end", f"(could not read CSV: {e})\n")
        self.csv_table.config(state="disabled")

    def _export_csv_as(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile="drone_log.csv", title="Export log as…")
        if not path:
            return
        import shutil
        shutil.copy2(self.csv_path, path)
        messagebox.showinfo("Exported", f"Log saved to:\n{path}")
        self._add_log(f"Exported → {os.path.basename(path)}")

    def build_ui(self) -> None:
        self.conn_var = tk.StringVar(value="connecting…")
        self.csv_path_var = tk.StringVar(value=f"Logging → {os.path.basename(self.csv_path)}")
        theme.header_bar(self.root, "Hospital Drone Control",
                         subtitle_var=self.csv_path_var, right_var=self.conn_var)

        toolbar = tk.Frame(self.root, bg=theme.BG_SUBTLE)
        toolbar.pack(fill="x")
        theme.neutral_button(toolbar, "Export CSV as…", self._export_csv_as).pack(side="right", padx=14, pady=8)
        tk.Label(toolbar, text="Fleet overview", bg=theme.BG_SUBTLE, fg=theme.FG,
                 font=theme.FONT_HEADER).pack(side="left", padx=18, pady=8)

        main = tk.Frame(self.root, bg=theme.BG)
        main.pack(fill="both", expand=True, padx=14, pady=(10, 6))

        left = tk.Frame(main, bg=theme.BG, width=380)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        tk.Label(left, text="All drones", bg=theme.BG, fg=theme.FG_MUTED,
                 font=theme.FONT_SMALL).pack(anchor="w", pady=(0, 6))
        self.drone_list_frame = tk.Frame(left, bg=theme.BG)
        self.drone_list_frame.pack(fill="x")
        self.drone_buttons: dict[str, tk.Frame] = {}

        right = tk.Frame(main, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True)
        self.detail_card = tk.Frame(right, bg=theme.BG_PANEL,
                                    highlightthickness=1, highlightbackground=theme.BORDER)
        self.detail_card.pack(fill="x")
        self.detail_label = tk.Label(self.detail_card, text="No drone selected",
                                     fg=theme.FG_MUTED, bg=theme.BG_PANEL,
                                     font=theme.FONT_BODY, pady=28)
        self.detail_label.pack()

        self.detail_frame = tk.Frame(self.detail_card, bg=theme.BG_PANEL)
        head = tk.Frame(self.detail_frame, bg=theme.BG_PANEL)
        head.pack(fill="x", padx=18, pady=(14, 2))
        self.detail_dot = tk.Label(head, text="●", bg=theme.BG_PANEL,
                                   fg=theme.BTN_PRIMARY_BG, font=("Helvetica", 18, "bold"))
        self.detail_dot.pack(side="left", padx=(0, 8))
        self.name_label = tk.Label(head, bg=theme.BG_PANEL, fg=theme.FG, font=theme.FONT_TITLE)
        self.name_label.pack(side="left")

        self.status_label = tk.Label(self.detail_frame, bg=theme.BG_PANEL,
                                     fg=theme.FG_MUTED, font=theme.FONT_BODY)
        self.battery_label = tk.Label(self.detail_frame, bg=theme.BG_PANEL,
                                      fg=theme.FG_MUTED, font=theme.FONT_BODY)
        self.medicine_label = tk.Label(self.detail_frame, bg=theme.BG_PANEL,
                                       fg="#6a0dad", font=theme.FONT_BODY)
        self.status_label.pack(anchor="w", padx=18)
        self.battery_label.pack(anchor="w", padx=18, pady=(0, 2))
        self.medicine_label.pack(anchor="w", padx=18, pady=(0, 8))

        btn_frame = tk.Frame(self.detail_frame, bg=theme.BG_PANEL)
        btn_frame.pack(anchor="w", padx=14, pady=(4, 16))
        theme.success_button(btn_frame, "Medicine loaded", self._on_medicine_loaded).pack(side="left", padx=4)
        theme.danger_button(btn_frame, "Return", self._on_return).pack(side="left", padx=4)
        theme.neutral_button(btn_frame, "Back", self._deselect).pack(side="left", padx=4)

        viz = tk.Frame(right, bg=theme.BG_PANEL,
                       highlightthickness=1, highlightbackground=theme.BORDER)
        viz.pack(fill="x", pady=(10, 0))
        tk.Label(viz, text="Fleet map", bg=theme.BG_PANEL, fg=theme.FG,
                 font=theme.FONT_LABEL).pack(anchor="w", padx=14, pady=(10, 2))
        self.viz_text = tk.StringVar(value="(Sense-HAT map mirrors this data live)")
        tk.Label(viz, textvariable=self.viz_text, bg=theme.BG_PANEL,
                 fg=theme.FG_MUTED, font=theme.FONT_MONO).pack(anchor="w", padx=14, pady=(0, 10))

        log_frame = tk.Frame(self.root, bg=theme.BG)
        log_frame.pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(log_frame, text="Activity log", bg=theme.BG, fg=theme.FG_MUTED,
                 font=theme.FONT_SMALL).pack(anchor="w")
        self.log_box = tk.Text(log_frame, height=4, state="disabled",
                               font=theme.FONT_MONO, bg=theme.BG_PANEL, fg=theme.FG,
                               relief="flat", highlightthickness=1, highlightbackground=theme.BORDER)
        self.log_box.pack(fill="x")

        csv_frame = tk.Frame(self.root, bg=theme.BG)
        csv_frame.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        tk.Label(csv_frame, text="Live CSV log  (newest first)", bg=theme.BG,
                 fg=theme.FG_MUTED, font=theme.FONT_SMALL).pack(anchor="w")
        tk.Label(csv_frame,
                 text="timestamp            event_type      drone_id    command             status                    medicine        message",
                 bg=theme.BG, fg="#aaaaaa", font=theme.FONT_MONO_SM, anchor="w").pack(fill="x")
        scroll = tk.Scrollbar(csv_frame)
        scroll.pack(side="right", fill="y")
        self.csv_table = tk.Text(csv_frame, height=8, state="disabled",
                                 font=theme.FONT_MONO, bg=theme.BG_PANEL, fg=theme.FG,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=theme.BORDER, yscrollcommand=scroll.set)
        self.csv_table.pack(fill="both", expand=True)
        scroll.config(command=self.csv_table.yview)
        self._refresh_csv_view()

    def _make_drone_button(self, drone: dict) -> None:
        row = tk.Frame(self.drone_list_frame, bg=theme.BG_PANEL,
                       highlightthickness=1, highlightbackground=theme.BORDER)
        row.pack(fill="x", pady=3)
        row._drone_id = drone["id"]  # type: ignore[attr-defined]
        stripe = tk.Frame(row, bg=theme.drone_color(drone["id"]), width=6)
        stripe.pack(side="left", fill="y")
        body = tk.Frame(row, bg=theme.BG_PANEL)
        body.pack(side="left", fill="both", expand=True, padx=10, pady=8)
        top = tk.Frame(body, bg=theme.BG_PANEL)
        top.pack(fill="x")
        name_lbl = tk.Label(top, text=drone["name"], bg=theme.BG_PANEL,
                            fg=theme.FG, font=theme.FONT_LABEL)
        name_lbl.pack(side="left")
        watch_lbl = tk.Label(top, text="", bg=theme.BG_PANEL,
                             fg=theme.BTN_PRIMARY_BG, font=theme.FONT_SMALL)
        watch_lbl.pack(side="right")
        status_lbl = tk.Label(body, bg=theme.BG_PANEL, fg=theme.FG_MUTED,
                              font=theme.FONT_SMALL, anchor="w")
        status_lbl.pack(fill="x", pady=(2, 0))
        for widget in (row, body, top, name_lbl, watch_lbl, status_lbl):
            widget.bind("<Button-1>", lambda _e, d=drone: self._select_drone(d))
        self.drone_buttons[drone["id"]] = row
        row._labels = (name_lbl, status_lbl, watch_lbl, stripe, body)  # type: ignore[attr-defined]
        self._refresh_drone_button(drone)

    def _refresh_drone_button(self, drone: dict) -> None:
        row = self.drone_buttons.get(drone["id"])
        if row is None:
            self._make_drone_button(drone)
            return
        name_lbl, status_lbl, watch_lbl, _stripe, body = row._labels  # type: ignore[attr-defined]
        med = f"  ·  {drone['medicine']}" if drone.get("medicine") else ""
        status = drone.get("status", "")
        status_lbl.config(text=f"{status}  ·  {self._loc_str(drone)}{med}")
        name_lbl.config(text=drone["name"])
        status_bg = theme.STATUS_COLORS.get(status, theme.BG_PANEL)
        if self.selected and self.selected["id"] == drone["id"]:
            status_bg = "#dbeafe"
        row.config(bg=status_bg, highlightbackground=theme.BORDER)
        for w in (body, name_lbl, status_lbl, watch_lbl):
            w.config(bg=status_bg)
        watch_lbl.config(text="📺 watching" if self.watched_drone_id == drone["id"] else "")

    def _select_drone(self, drone: dict) -> None:
        self.selected = drone
        self.detail_label.pack_forget()
        self.detail_frame.pack(fill="x")
        self._update_detail_panel()
        for d in self.drones.values():
            self._refresh_drone_button(d)
        self._add_log(f"Selected {drone['name']}")
        self._log_event("select", drone=drone, command="select_drone")

    def _deselect(self) -> None:
        self.selected = None
        self.detail_frame.pack_forget()
        self.detail_label.pack()
        for d in self.drones.values():
            self._refresh_drone_button(d)
        self._add_log("Back to overview")

    def _on_medicine_loaded(self) -> None:
        if not self.selected:
            return
        self._post(f"/api/drones/{self.selected['id']}/medicine_loaded")
        self._log_event("command", drone=self.selected, command="medicine_loaded")

    def _on_return(self) -> None:
        if not self.selected:
            return
        self._post(f"/api/drones/{self.selected['id']}/return")
        self._log_event("command", drone=self.selected, command="return")

    def _post(self, path: str) -> None:
        def go() -> None:
            try:
                r = requests.post(f"{APP_SERVER_URL}{path}", json={}, timeout=5)
                if not r.ok:
                    self.root.after(0, lambda: self._add_log(
                        f"POST {path} → {r.status_code} {r.text[:80]}"))
            except Exception as e:
                self.root.after(0, lambda: self._add_log(f"POST {path} failed: {e}"))
        threading.Thread(target=go, daemon=True).start()

    def _update_detail_panel(self) -> None:
        if not self.selected:
            return
        d = self.selected
        self.name_label.config(text=d["name"])
        self.detail_dot.config(fg=theme.drone_color(d["id"]))
        self.status_label.config(text=f"Status: {d['status']}  ·  {self._loc_str(d)}")
        self.battery_label.config(text=f"Battery: {d.get('battery_state', '?')}")
        med = d.get("medicine", "")
        self.medicine_label.config(text=f"Requested medicine: {med}" if med else "")

    def _add_log(self, message: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("1.0", f"{now}  {message}\n")
        self.log_box.config(state="disabled")

    def _seed_from_rest(self) -> None:
        def fetch() -> None:
            try:
                r = requests.get(f"{APP_SERVER_URL}/api/drones", timeout=3)
                r.raise_for_status()
                drones = r.json().get("drones", [])
            except Exception as e:
                self.root.after(0, lambda: self._add_log(f"Could not load fleet: {e}"))
                return
            self.root.after(0, lambda: self._bulk_update_drones(drones))
        threading.Thread(target=fetch, daemon=True).start()

    def _fetch_viewer_state(self) -> None:
        def fetch() -> None:
            try:
                r = requests.get(f"{APP_SERVER_URL}/api/viewer", timeout=3)
                if not r.ok:
                    return
                drone_id = (r.json() or {}).get("drone_id")
                if drone_id:
                    self.root.after(0, lambda: self._set_watched(drone_id))
            except Exception:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    def _bulk_update_drones(self, drones: list[dict]) -> None:
        for drone in drones:
            self.drones[drone["id"]] = drone
            self._refresh_drone_button(drone)

    def _set_watched(self, drone_id: Optional[str]) -> None:
        self.watched_drone_id = drone_id
        for d in self.drones.values():
            self._refresh_drone_button(d)
        if drone_id:
            self.viz_text.set(f"Sense-HAT is following {drone_id}  ·  map mirrors this data live")

    def _start_ws(self) -> None:
        def run() -> None:
            while not self._stop:
                try:
                    self.ws_app = WebSocketApp(
                        WS_URL,
                        on_open=self._on_ws_open,
                        on_message=self._on_ws_message,
                        on_error=self._on_ws_error,
                        on_close=self._on_ws_close,
                    )
                    self.ws_app.run_forever(ping_interval=20)
                except Exception as e:
                    self.root.after(0, lambda: self._add_log(f"WS error: {e}"))
                if self._stop:
                    break
                time.sleep(3)
        self._ws_thread = threading.Thread(target=run, daemon=True)
        self._ws_thread.start()

    def _on_ws_open(self, ws) -> None:
        self.root.after(0, lambda: self.conn_var.set("live ✓"))
        self.root.after(0, lambda: self._add_log("WebSocket connected"))

    def _on_ws_close(self, ws, code, msg) -> None:
        self.root.after(0, lambda: self.conn_var.set("reconnecting…"))

    def _on_ws_error(self, ws, err) -> None:
        self.root.after(0, lambda: self._add_log(f"WS error: {err}"))

    def _on_ws_message(self, ws, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        event = data.get("event", "")
        payload = data.get("payload", {}) or {}
        if event == "snapshot":
            self.root.after(0, lambda: self._bulk_update_drones(payload.get("drones", [])))
            viewer = payload.get("viewer") or {}
            if viewer.get("drone_id"):
                self.root.after(0, lambda: self._set_watched(viewer["drone_id"]))
        elif event in ("drone_updated", "drone_telemetry", "drone_status", "drone_battery"):
            drone_id = payload.get("drone_id") or payload.get("id")
            if drone_id:
                self._patch_drone(drone_id, payload)
        elif event == "viewer_changed":
            self.root.after(0, lambda: self._set_watched(payload.get("drone_id")))
        elif event.startswith("order_"):
            self.root.after(0, lambda: self._add_log(
                f"{event}: order {payload.get('id', '?')} {payload.get('status', '')}"))
            self._log_event(event, command=event, status=payload.get("status", ""),
                            raw_payload=json.dumps(payload))

    def _patch_drone(self, drone_id: str, payload: dict) -> None:
        def apply() -> None:
            drone = self.drones.get(drone_id)
            if drone is None:
                if "id" in payload and "home_x" in payload:
                    drone = dict(payload)
                    self.drones[drone_id] = drone
                else:
                    return
            else:
                for k in ("status", "x", "y", "battery_state", "medicine"):
                    if k in payload and payload[k] not in (None, ""):
                        drone[k] = payload[k]
            self._refresh_drone_button(drone)
            if self.selected and self.selected["id"] == drone_id:
                self.selected = drone
                self._update_detail_panel()
        self.root.after(0, apply)

    def shutdown(self) -> None:
        self._stop = True
        try:
            if self.ws_app:
                self.ws_app.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    app = DroneApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.shutdown(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
