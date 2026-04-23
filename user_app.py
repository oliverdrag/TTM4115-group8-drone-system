"""Bruker frontend — tkinter GUI som  snakker med applikasjons serveren via REST.

Appen følger Bruker Frontend tilstandsmaskina i  speksen
(Idle → Enter-Info → Drone-leverer), men effektne fyrer nå ekte HTTP
kall istedetfor mockede varslinger.

Destinasjonen er en tilfeldi  ledig celle på 80x80 gridet; gridet er
hentet fra servern ved oppstart så vi vet hvilke cellr som er  restrikterte.
"""

import logging
import os
import random
import threading
import tkinter as tk
from typing import Optional

import requests
from stmpy import Driver, Machine

import ui_theme as theme


log = logging.getLogger("user_app")

APP_SERVER_URL = os.environ.get("APP_SERVER_URL", "http://localhost:5000")
POLL_INTERVAL_MS = 1500


class UserFrontend:

    # ---- bilder / hjelpere ----------------------------------------------
    def load_images(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        image_dir = os.path.join(base_dir, "images")
        try:
            self.idle_image = tk.PhotoImage(file=os.path.join(image_dir, "idle_image.png"))
        except Exception:
            self.idle_image = None
        try:
            self.delivering_image = tk.PhotoImage(file=os.path.join(image_dir, "delivering_image.png"))
        except Exception:
            self.delivering_image = None

    def set_status(self, status: str) -> None:
        self.status_text.set(status)

    def show_frame_with_clear(self, frame_name: str, clear: bool = False) -> None:
        if clear:
            self.clear_form()
        self.show_frame(frame_name)

    # ---- knappe handlere ------------------------------------------------
    def on_button_cancel(self):
        self.stm.send("cancel")

    def on_button_order_drone(self):
        self.stm.send("order_drone")

    def on_button_send_info(self):
        if not self.validate_order_form():
            self.show_alert("Please fill in Name, Location, and Medicine.")
            return
        self.current_order = {
            "name": self.entry_name.get().strip(),
            "location": self.entry_location.get().strip(),
            "medicine": self.entry_medicine.get().strip(),
        }
        self.stm.send("send_info")

    def on_button_refresh(self):
        self._refresh_order_status()

    def on_button_medicine_received(self):
        self.stm.send("medicine_received")

    def on_button_exit(self):
        self.is_shutting_down = True
        if self.stm is not None and self.stm.driver is not None:
            self.stm.driver.stop()
        self.root.quit()
        self.root.destroy()

    def validate_order_form(self):
        return all(
            (
                self.entry_name.get().strip(),
                self.entry_location.get().strip(),
                self.entry_medicine.get().strip(),
            )
        )

    def clear_form(self):
        for entry in (self.entry_name, self.entry_location, self.entry_medicine):
            entry.delete(0, tk.END)

    def show_frame(self, frame_name: str) -> None:
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[frame_name].pack(fill="both", expand=True, padx=18, pady=14)

    # ---- UI konstruksjon -----------------------------------------------
    def configure_window(self):
        theme.apply_window(self.root, "Drone Delivery — User", 440, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_button_exit)

    def build_header(self):
        self.subtitle_var = tk.StringVar(value="")
        theme.header_bar(self.root, "Drone Delivery", subtitle_var=self.subtitle_var)
        strip = tk.Frame(self.root, bg=theme.BG_SUBTLE)
        strip.pack(fill="x")
        self.status_text = tk.StringVar(value="Idle")
        theme.status_pill(strip, self.status_text).pack(side="left", padx=18, pady=6)
        self.coord_text = tk.StringVar(value="")
        tk.Label(strip, textvariable=self.coord_text, bg=theme.BG_SUBTLE,
                 fg=theme.FG_MUTED, font=theme.FONT_MONO).pack(side="right", padx=18)

    def _image_panel(self, parent: tk.Misc, image: Optional[tk.PhotoImage]) -> tk.Frame:
        panel = tk.Frame(parent, bg=theme.BG_PANEL)
        if image is not None:
            tk.Label(panel, image=image, bg=theme.BG_PANEL).pack(pady=(18, 10))
        return panel

    def build_start_view(self):
        self.start_frame.configure(bg=theme.BG)
        card = tk.Frame(self.start_frame, bg=theme.BG_PANEL,
                        highlightthickness=1, highlightbackground=theme.BORDER)
        card.pack(fill="both", expand=True)
        self._image_panel(card, self.idle_image).pack(fill="x")
        tk.Label(card, text="Need medicine delivered?",
                 bg=theme.BG_PANEL, fg=theme.FG,
                 font=theme.FONT_HEADER).pack(pady=(4, 2))
        tk.Label(card, text="Request a drone and we'll dispatch the closest one.",
                 bg=theme.BG_PANEL, fg=theme.FG_MUTED,
                 font=theme.FONT_BODY).pack(pady=(0, 14))
        theme.primary_button(card, "Order Drone",
                             self.on_button_order_drone, width=18).pack(pady=4)
        theme.neutral_button(card, "Exit",
                             self.on_button_exit, width=18).pack(pady=(4, 18))

    def _build_labeled_entry(self, parent: tk.Misc, label: str) -> tk.Entry:
        tk.Label(parent, text=label, bg=theme.BG_PANEL, fg=theme.FG,
                 font=theme.FONT_LABEL).pack(anchor="w", padx=24, pady=(10, 2))
        entry = tk.Entry(parent, width=34, font=theme.FONT_BODY,
                         relief="flat", bg=theme.BG_SUBTLE,
                         highlightthickness=1,
                         highlightbackground=theme.BORDER,
                         highlightcolor=theme.BTN_PRIMARY_BG)
        entry.pack(padx=24, pady=(0, 4), ipady=5, fill="x")
        return entry

    def build_enter_info_view(self):
        self.info_frame.configure(bg=theme.BG)
        card = tk.Frame(self.info_frame, bg=theme.BG_PANEL,
                        highlightthickness=1, highlightbackground=theme.BORDER)
        card.pack(fill="both", expand=True)
        tk.Label(card, text="Delivery information",
                 bg=theme.BG_PANEL, fg=theme.FG,
                 font=theme.FONT_HEADER).pack(anchor="w", padx=24, pady=(18, 4))
        self.entry_name     = self._build_labeled_entry(card, "Name")
        self.entry_location = self._build_labeled_entry(card, "Location (area description)")
        self.entry_medicine = self._build_labeled_entry(card, "Medicine")

        buttons = tk.Frame(card, bg=theme.BG_PANEL)
        buttons.pack(pady=(18, 16))
        theme.primary_button(buttons, "Send Info",
                             self.on_button_send_info, width=12).pack(side="left", padx=6)
        theme.neutral_button(buttons, "Cancel",
                             self.on_button_cancel, width=12).pack(side="left", padx=6)

    def build_delivery_view(self):
        self.delivery_frame.configure(bg=theme.BG)
        card = tk.Frame(self.delivery_frame, bg=theme.BG_PANEL,
                        highlightthickness=1, highlightbackground=theme.BORDER)
        card.pack(fill="both", expand=True)
        self._image_panel(card, self.delivering_image).pack(fill="x")
        tk.Label(card, text="A drone is on the way",
                 bg=theme.BG_PANEL, fg=theme.FG,
                 font=theme.FONT_HEADER).pack(pady=(4, 2))
        tk.Label(card, text="Tap 'Medicine Received' when it arrives.",
                 bg=theme.BG_PANEL, fg=theme.FG_MUTED,
                 font=theme.FONT_BODY).pack(pady=(0, 12))

        actions = tk.Frame(card, bg=theme.BG_PANEL)
        actions.pack(pady=4)
        theme.success_button(actions, "Medicine Received",
                             self.on_button_medicine_received, width=16).grid(
            row=0, column=0, padx=4, pady=4)
        theme.neutral_button(actions, "Refresh",
                             self.on_button_refresh, width=16).grid(
            row=0, column=1, padx=4, pady=4)
        theme.danger_button(actions, "Cancel",
                            self.on_button_cancel, width=16).grid(
            row=1, column=0, padx=4, pady=4)
        theme.neutral_button(actions, "Exit",
                             self.on_button_exit, width=16).grid(
            row=1, column=1, padx=4, pady=(4, 18))

    def build_views(self):
        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(fill="both", expand=True)
        self.start_frame    = tk.Frame(body, bg=theme.BG)
        self.info_frame     = tk.Frame(body, bg=theme.BG)
        self.delivery_frame = tk.Frame(body, bg=theme.BG)
        self.frames = {
            "idle":             self.start_frame,
            "enter_info":       self.info_frame,
            "drone_delivering": self.delivery_frame,
        }
        self.build_start_view()
        self.build_enter_info_view()
        self.build_delivery_view()

    def display(self):
        self.configure_window()
        self.build_header()
        self.build_views()
        self.show_frame("idle")

    # ---- tilstand / init --------------------------------------------------
    def __init__(self):
        self.stm: Optional[Machine] = None
        self.is_shutting_down = False
        self.current_order: dict = {}
        self.current_order_id: Optional[int] = None
        self.free_cells: list[tuple[int, int]] = []
        self.root = tk.Tk()
        self.load_images()
        self.display()
        threading.Thread(target=self._fetch_grid, daemon=True).start()

    # ---- grid / koordinater --------------------------------------------
    def _fetch_grid(self):
        try:
            r = requests.get(f"{APP_SERVER_URL}/api/grid", timeout=5)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("could not fetch grid: %s", e)
            self.root.after(0, lambda: self.show_alert(f"Server unreachable: {e}"))
            return
        width, height = data["width"], data["height"]
        restricted = set()
        for zone in data.get("zones", []):
            for cell in zone.get("cells", []):
                restricted.add((cell[0], cell[1]))
        # Unngå øverste-venstre hangar hjørne — droner spawner der. Skaler
        # sikkerhets margen med gridet så vi fortsat har  ledige celler på en 80x80.
        margin = max(4, min(width, height) // 5)
        free = []
        for y in range(margin, height):
            for x in range(margin, width):
                if (x, y) not in restricted:
                    free.append((x, y))
        self.free_cells = free
        log.info("Grid loaded: %dx%d with %d free target cells", width, height, len(free))

    def _pick_random_destination(self) -> tuple[int, int]:
        if not self.free_cells:
            # Grid ikkje lasta enda; fall tilbake til en tilfeldi  celle.
            return (random.randint(50, 75), random.randint(50, 75))
        return random.choice(self.free_cells)

    # ---- tilstand entry aksjoner -------------------------------------------
    def show_idle(self):
        self.set_status("Idle")
        self.coord_text.set("")
        self.current_order_id = None
        self.show_frame_with_clear("idle", clear=True)

    def show_enter_info(self):
        self.set_status("Enter delivery information")
        self.show_frame_with_clear("enter_info")

    def show_drone_delivering(self):
        self.set_status("Drone is on its way")
        self.show_frame_with_clear("drone_delivering")
        # Sparkk igang  polling.
        self.root.after(POLL_INTERVAL_MS, self._refresh_order_status)

    # ---- REST aksjoner --------------------------------------------------
    def request_drone(self):
        dest_x, dest_y = self._pick_random_destination()
        self.coord_text.set(f"Destination: ({dest_x}, {dest_y})")
        payload = {
            "user_name": self.current_order.get("name", ""),
            "medicine": self.current_order.get("medicine", ""),
            "location": {"x": dest_x, "y": dest_y},
        }
        threading.Thread(target=self._post_order, args=(payload,), daemon=True).start()

    def _post_order(self, payload: dict) -> None:
        try:
            r = requests.post(f"{APP_SERVER_URL}/api/orders", json=payload, timeout=5)
        except Exception as e:
            self.root.after(0, lambda: self._order_failed(f"Network error: {e}"))
            return
        if r.status_code == 201:
            order = r.json()
            self.current_order_id = order["id"]
            self.root.after(
                0,
                lambda: self.show_alert(
                    f"Order #{order['id']} assigned to {order.get('drone_id', '?')}"
                ),
            )
        else:
            err = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else r.text
            self.root.after(0, lambda: self._order_failed(err or "Order failed"))

    def _order_failed(self, message: str):
        self.show_alert(f"Order failed: {message}")
        self.stm.send("cancelled_by_system")

    def _refresh_order_status(self):
        if self.current_order_id is None or self.is_shutting_down:
            return
        oid = self.current_order_id
        threading.Thread(target=self._poll_order, args=(oid,), daemon=True).start()

    def _poll_order(self, order_id: int):
        try:
            r = requests.get(f"{APP_SERVER_URL}/api/orders/{order_id}", timeout=3)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("poll failed: %s", e)
            self.root.after(POLL_INTERVAL_MS, self._refresh_order_status)
            return
        status = data.get("status", "?")
        drone_id = data.get("drone_id", "?")
        self.root.after(0, lambda: self.show_alert(f"Order #{order_id} · {status} · {drone_id}"))
        if status in ("cancelled", "failed"):
            self.root.after(0, lambda: self.stm.send("cancelled_by_system"))
            return
        if status == "completed":
            self.root.after(0, lambda: self.stm.send("medicine_received"))
            return
        if not self.is_shutting_down:
            self.root.after(POLL_INTERVAL_MS, self._refresh_order_status)

    def confirm_delivery(self):
        if self.current_order_id is None:
            return
        oid = self.current_order_id

        def do_post():
            try:
                requests.post(f"{APP_SERVER_URL}/api/orders/{oid}/complete", timeout=5)
            except Exception as e:
                log.warning("confirm failed: %s", e)

        threading.Thread(target=do_post, daemon=True).start()

    def cancel_delivery(self):
        if self.current_order_id is None:
            return
        oid = self.current_order_id

        def do_post():
            try:
                requests.post(f"{APP_SERVER_URL}/api/orders/{oid}/cancel", timeout=5)
            except Exception as e:
                log.warning("cancel failed: %s", e)

        threading.Thread(target=do_post, daemon=True).start()

    # ---- diverse ---------------------------------------------------------
    def show_alert(self, message):
        self.status_text.set(message)

    def run(self):
        self.root.mainloop()


def main():
    logging.basicConfig(level=logging.INFO)
    frontend = UserFrontend()

    transitions = [
        {"source": "initial", "target": "idle"},
        {"trigger": "order_drone", "source": "idle", "target": "enter_info"},
        {"trigger": "cancel", "source": "enter_info", "target": "idle"},
        {
            "trigger": "send_info",
            "source": "enter_info",
            "target": "drone_delivering",
            "effect": "request_drone",
        },
        {"trigger": "refresh", "source": "drone_delivering", "target": "drone_delivering"},
        {
            "trigger": "medicine_received",
            "source": "drone_delivering",
            "target": "idle",
            "effect": "confirm_delivery",
        },
        {
            "trigger": "cancel",
            "source": "drone_delivering",
            "target": "idle",
            "effect": "cancel_delivery",
        },
        {
            "trigger": "cancelled_by_system",
            "source": "drone_delivering",
            "target": "idle",
            "effect": 'show_alert("delivery cancelled by system")',
        },
    ]

    states = [
        {"name": "idle", "entry": "show_idle"},
        {"name": "enter_info", "entry": "show_enter_info"},
        {"name": "drone_delivering", "entry": "show_drone_delivering"},
    ]

    stm = Machine(name="stm_frontend", transitions=transitions, states=states, obj=frontend)
    frontend.stm = stm
    driver = Driver()
    driver.add_machine(stm)
    driver.start()
    frontend.run()


if __name__ == "__main__":
    main()
