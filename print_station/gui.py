"""The operator window of the print station (tkinter, part of standard Python).

The station's work loop runs in a background thread and reports events
through a queue; the window reads the queue ten times per second. Buttons
change the simulated printer (switch on/off, load paper, replace toner,
clear a jam) and send the new state to Chapify straight away.
"""

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

INK = "#18202e"
MUTED = "#4e5869"
PAPER = "#f3f5f8"
SHEET = "#ffffff"
RULE = "#d8dde5"
BLUE = "#0b63b6"
OK = "#1f7a3d"
BAD = "#b42318"
WARN = "#a66a00"

STATUS_TEXT = {
    "AVAILABLE": ("Ready", OK),
    "OFFLINE": ("Switched off", MUTED),
    "ERROR": ("Needs attention", BAD),
}


class StationWindow:
    def __init__(self, root, station):
        self.root = root
        self.station = station
        self.device = station.device
        self.events = queue.Queue()

        root.title("Chapify Print Station")
        root.geometry("760x620")
        root.minsize(680, 560)
        root.configure(bg=PAPER)
        self._styles()
        self._layout()
        self._refresh_device()

    # --- look -------------------------------------------------------------------

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        base = ("Segoe UI", 10)
        style.configure(".", background=PAPER, foreground=INK, font=base)
        style.configure("Sheet.TFrame", background=SHEET, relief="solid", borderwidth=1)
        style.configure("Sheet.TLabel", background=SHEET)
        style.configure("Muted.TLabel", background=SHEET, foreground=MUTED)
        style.configure("Title.TLabel", background=PAPER, font=("Bahnschrift", 18, "bold"))
        style.configure("Sub.TLabel", background=PAPER, foreground=MUTED)
        style.configure("Big.TLabel", background=SHEET, font=("Bahnschrift", 20, "bold"))
        style.configure("Head.TLabel", background=SHEET, font=("Bahnschrift", 11, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background=BLUE, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#094f92")])
        style.configure("Job.Horizontal.TProgressbar", troughcolor=PAPER, background=BLUE, thickness=14)
        style.configure("Level.Horizontal.TProgressbar", troughcolor=PAPER, background=MUTED, thickness=10)
        style.configure("TCheckbutton", background=SHEET)

    def _sheet(self, parent, **grid):
        frame = ttk.Frame(parent, style="Sheet.TFrame", padding=14)
        frame.grid(sticky="nsew", **grid)
        return frame

    def _layout(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(2, weight=1)

        # Header: which printer this is, and the connection to Chapify.
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        self.title = ttk.Label(header, text="Connecting to Chapify…", style="Title.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.location = ttk.Label(header, text=self.station.client.server, style="Sub.TLabel")
        self.location.grid(row=1, column=0, sticky="w")
        self.connection = tk.Label(header, text="● Not connected", bg=PAPER, fg=BAD, font=("Segoe UI", 10, "bold"))
        self.connection.grid(row=0, column=1, rowspan=2, sticky="e")

        # Current state and job.
        state = self._sheet(outer, row=1, column=0, padx=(0, 12))
        state.columnconfigure(0, weight=1)
        self.state_label = tk.Label(state, text="Starting", bg=SHEET, fg=MUTED, font=("Bahnschrift", 20, "bold"))
        self.state_label.grid(row=0, column=0, sticky="w")
        self.state_detail = ttk.Label(state, text="", style="Muted.TLabel")
        self.state_detail.grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.job_label = ttk.Label(state, text="No job", style="Head.TLabel")
        self.job_label.grid(row=2, column=0, sticky="w")
        self.job_detail = ttk.Label(state, text="Waiting for paid print jobs.", style="Muted.TLabel", wraplength=380)
        self.job_detail.grid(row=3, column=0, sticky="w", pady=(2, 8))
        self.progress = ttk.Progressbar(state, style="Job.Horizontal.TProgressbar", maximum=1, value=0)
        self.progress.grid(row=4, column=0, sticky="ew")
        self.progress_text = ttk.Label(state, text="", style="Muted.TLabel")
        self.progress_text.grid(row=5, column=0, sticky="w", pady=(4, 0))

        # Consumables and operator controls.
        side = self._sheet(outer, row=1, column=1)
        side.columnconfigure(0, weight=1)
        ttk.Label(side, text="Paper", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.paper_bar = ttk.Progressbar(side, style="Level.Horizontal.TProgressbar", maximum=self.device.paper_capacity)
        self.paper_bar.grid(row=1, column=0, sticky="ew")
        self.paper_text = ttk.Label(side, style="Muted.TLabel")
        self.paper_text.grid(row=2, column=0, sticky="w", pady=(2, 8))
        ttk.Label(side, text="Toner", style="Head.TLabel").grid(row=3, column=0, sticky="w")
        self.toner_bar = ttk.Progressbar(side, style="Level.Horizontal.TProgressbar", maximum=100)
        self.toner_bar.grid(row=4, column=0, sticky="ew")
        self.toner_text = ttk.Label(side, style="Muted.TLabel")
        self.toner_text.grid(row=5, column=0, sticky="w", pady=(2, 12))

        buttons = ttk.Frame(side, style="Sheet.TFrame", padding=0)
        buttons.grid(row=6, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1)
        self.power_button = ttk.Button(buttons, text="Switch off", command=self.toggle_power)
        self.power_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=2)
        self.jam_button = ttk.Button(buttons, text="Clear jam", command=self.clear_jam, state="disabled")
        self.jam_button.grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Button(buttons, text="Load paper", command=self.load_paper).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=2)
        ttk.Button(buttons, text="Replace toner", command=self.replace_toner).grid(row=1, column=1, sticky="ew", pady=2)
        self.jam_next = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="Jam the next job (demonstration)", variable=self.jam_next,
                        command=self.set_jam_next).grid(row=7, column=0, sticky="w", pady=(10, 0))

        # Activity log.
        log_sheet = self._sheet(outer, row=2, column=0, columnspan=2, pady=(12, 0))
        log_sheet.columnconfigure(0, weight=1)
        log_sheet.rowconfigure(1, weight=1)
        ttk.Label(log_sheet, text="Activity", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.log = tk.Text(log_sheet, height=8, bg=SHEET, fg=INK, relief="flat", font=("Consolas", 9),
                           wrap="word", state="disabled", highlightthickness=0)
        self.log.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        scroll = ttk.Scrollbar(log_sheet, command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.log.configure(yscrollcommand=scroll.set)

    # --- operator actions ---------------------------------------------------------

    def toggle_power(self):
        self.device.set_online(not self.device.online)
        self.add_log("Printer switched " + ("on." if self.device.online else "off."))
        self._after_action()

    def load_paper(self):
        self.device.load_paper()
        self.add_log(f"Paper tray filled ({self.device.paper_capacity} sheets).")
        self._after_action()

    def replace_toner(self):
        self.device.replace_toner()
        self.add_log("Toner cartridge replaced.")
        self._after_action()

    def clear_jam(self):
        self.device.clear_jam()
        self.add_log("Jam cleared.")
        self._after_action()

    def set_jam_next(self):
        self.device.jam_next_job = self.jam_next.get()

    def _after_action(self):
        self._refresh_device()
        self.station.request_heartbeat()

    # --- events from the station thread -------------------------------------------

    def handle(self, kind, data):
        self.events.put((kind, data))

    def poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                self._apply(kind, data)
        except queue.Empty:
            pass
        self._refresh_device()
        self.root.after(100, self.poll_events)

    def _apply(self, kind, data):
        if kind == "log":
            self.add_log(data["message"])
        elif kind == "connection":
            if data["connected"]:
                self.connection.configure(text="● Connected to Chapify", fg=OK)
            else:
                self.connection.configure(text="● Not connected", fg=BAD)
        elif kind == "heartbeat":
            printer = data["printer"]
            self.title.configure(text=printer["name"])
            self.location.configure(text=f"{printer['location']}  ·  {self.station.client.server.rstrip('/')}")
            self.root.title(f"Chapify Print Station – {printer['name']}")
        elif kind == "job_started":
            job = data["job"]
            self.job_label.configure(text=f"Job #{job['id']} · {job['file_name']}")
            colour = "Color" if job["color_mode"] == "COLOR" else "Black and white"
            sides = "double-sided" if job["duplex_mode"] == "DOUBLE_SIDED" else "one-sided"
            self.job_detail.configure(
                text=f"For {job['owner']} · {job['pages']} page(s) × {job['copies']} · {colour}, "
                     f"{job['paper_format']}, {sides} · {data['sheets']} sheet(s)"
            )
            self.progress.configure(maximum=data["sides"], value=0)
            self.progress_text.configure(text="Downloading the document…")
        elif kind == "progress":
            self.progress.configure(value=data["side"])
            self.progress_text.configure(text=f"Printed {data['side']} of {data['total']}")
        elif kind == "job_finished":
            job = data["job"]
            if data["success"]:
                self.progress_text.configure(text=f"Job #{job['id']} printed. Collect it from the tray.")
            else:
                self.progress_text.configure(text=f"Job #{job['id']} failed: {data['reason']}")
            self.jam_next.set(self.device.jam_next_job)

    def _refresh_device(self):
        status, message = self.device.status()
        if self.station.current_job is not None and status == "AVAILABLE":
            text, colour = "Printing", BLUE
        else:
            text, colour = STATUS_TEXT.get(status, (status, MUTED))
        self.state_label.configure(text=text, fg=colour)
        self.state_detail.configure(text=message if status != "AVAILABLE" else "Waiting for jobs from Chapify")

        sheets = self.device.paper_sheets
        self.paper_bar.configure(value=sheets)
        self.paper_text.configure(text=f"{sheets} of {self.device.paper_capacity} sheets")
        toner = self.device.toner_level()
        self.toner_bar.configure(value=toner)
        self.toner_text.configure(text=f"{toner}%")
        self.power_button.configure(text="Switch off" if self.device.online else "Switch on")
        self.jam_button.configure(state="normal" if self.device.jammed else "disabled")

    def add_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {message}\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 300:
            self.log.delete("1.0", f"{lines - 300}.0")
        self.log.see("end")
        self.log.configure(state="disabled")


def run_window(args, build_station):
    root = tk.Tk()
    holder = {}
    station = build_station(args, lambda kind, data: holder["window"].handle(kind, data))
    window = StationWindow(root, station)
    holder["window"] = window

    worker = threading.Thread(target=station.run_forever, name="print-station", daemon=True)
    worker.start()
    window.poll_events()

    def close():
        station.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0
