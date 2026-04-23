import os
import tkinter as tk
from stmpy import Machine, Driver

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
    
    def on_button_cancel(self):
        self.stm.send('cancel')
    
    def on_button_order_drone(self):
        self.stm.send('order_drone')
        
    def on_button_send_info(self):
        if not self.validate_order_form():
            self.show_alert("Please fill in Name, Location, and Medicine.")
            return

        self.current_order = {
            "name": self.entry_name.get().strip(),
            "location": self.entry_location.get().strip(),
            "medicine": self.entry_medicine.get().strip(),
        }
        self.stm.send('send_info')
        
    def on_button_refresh(self):
        self.stm.send('refresh')
    
    def on_button_medicine_received(self):
        self.stm.send('medicine_received')
        
    def on_button_exit(self):
        self.is_shutting_down = True
        if self.stm is not None and self.stm.driver is not None:
            self.stm.driver.stop()
        self.root.quit()
        self.root.destroy()

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
        self.root.geometry("380x300")
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

    def _build_labeled_entry(self, label):
        tk.Label(self.info_frame, text=label).pack(anchor="w", padx=40)
        entry = tk.Entry(self.info_frame, width=32)
        entry.pack(padx=40, pady=(0, 8))
        return entry

    def build_enter_info_view(self):
        self.entry_name = self._build_labeled_entry("Name")
        self.entry_location = self._build_labeled_entry("Location")
        self.entry_medicine = self._build_labeled_entry("Medicine")
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
        self.is_shutting_down = False
        self.current_order = {}
        self.root = tk.Tk()
        self.load_images()
        self.display()
        
    def show_idle(self):
        self.set_status("Idle")
        self.show_frame_with_clear("idle", clear=True)

    def show_enter_info(self):
        self.set_status("Enter delivery information")
        self.show_frame_with_clear("enter_info")

    def show_drone_delivering(self):
        self.set_status("Drone is delivering medicine")
        self.show_frame_with_clear("drone_delivering")

    def request_drone(self):
        self.show_alert(
            f"Request sent for {self.current_order.get('name', 'user')} "
            f"to {self.current_order.get('location', 'location')} "
            f"({self.current_order.get('medicine', 'medicine')})."
        )
        # TODO: Send the order details to the backend

    def transmit_to_drone(self, message):
        self.show_alert(f"Drone message: {message}")

    def show_alert(self, message):
        self.status_text.set(message)

    def run(self):
        self.root.mainloop()
        
frontend = UserFrontend()

transitions = [
    {'source': 'initial', 'target': 'idle'},
    {'trigger': 'order_drone', 'source': 'idle', 'target': 'enter_info'},
    {'trigger': 'cancel', 'source': 'enter_info', 'target': 'idle'},
    {'trigger': 'send_info', 'source': 'enter_info', 'target': 'drone_delivering', 'effect': 'request_drone()'},
    {'trigger': 'refresh', 'source': 'drone_delivering', 'target': 'drone_delivering'},
    {'trigger': 'medicine_received', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'transmit_to_drone("delivery completed")'},
    {'trigger': 'cancel', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'transmit_to_drone("cancel delivery")'},
    {'trigger': 'cancelled_by_system', 'source': 'drone_delivering', 'target': 'idle', 'effect': 'show_alert("delivery cancelled by system")'},
]

# the states:
idle = {'name': 'idle',
            'entry': 'show_idle'}

enter_info = {'name': 'enter_info',
    'entry': 'show_enter_info'}

drone_delivering = {'name': 'drone_delivering',
    'entry': 'show_drone_delivering'}

stm_frontend = Machine(name='stm_frontend', transitions=transitions, states=[idle, enter_info, drone_delivering], obj=frontend)
frontend.stm = stm_frontend

driver = Driver()
driver.add_machine(stm_frontend)
driver.start()
frontend.run()