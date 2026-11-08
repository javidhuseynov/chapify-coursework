"""The simulated printer hardware.

Models what matters for a self-service printer: it can be switched off,
runs out of paper and toner, prints at a given speed, and can jam. A jam
puts the printer in an error state until the operator clears it.
"""

import math
import random
import threading
import time
from dataclasses import dataclass

STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFLINE = "OFFLINE"
STATUS_ERROR = "ERROR"

# Toner used per printed side, in percent of a full cartridge.
TONER_PER_SIDE = {"BW": 0.05, "COLOR": 0.12}


@dataclass
class PrintOutcome:
    success: bool
    reason: str = ""
    sides_printed: int = 0
    sheets_used: int = 0


def sides_and_sheets(job):
    """(printed sides, sheets of paper) needed for a job."""
    pages, copies = int(job["pages"]), int(job["copies"])
    sides = pages * copies

    if job.get("duplex_mode") == "DOUBLE_SIDED":
        sheets = math.ceil(pages / 2) * copies
    else:
        sheets = sides

    return sides, sheets


class SimulatedPrinter:
    def __init__(
        self,
        paper_sheets=500,
        paper_capacity=500,
        toner_percent=100.0,
        seconds_per_page=0.5,
        jam_rate=0.0,
        rng=None,
        sleep=time.sleep,
    ):
        self.paper_capacity = paper_capacity
        self.paper_sheets = min(paper_sheets, paper_capacity)
        self.toner_percent = float(toner_percent)
        self.seconds_per_page = seconds_per_page
        self.jam_rate = jam_rate
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.online = True
        self.jammed = False
        self.jam_next_job = False  # operator/demo switch
        self._lock = threading.Lock()

    # --- state seen by Chapify -------------------------------------------------

    def status(self):
        """(status, message) to report in the heartbeat."""
        if not self.online:
            return STATUS_OFFLINE, "Switched off by the operator"
        if self.jammed:
            return STATUS_ERROR, "Paper jam: remove the jammed paper"
        if self.paper_sheets == 0:
            return STATUS_ERROR, "Out of paper"
        if self.toner_percent < 1:
            return STATUS_ERROR, "Toner empty"
        return STATUS_AVAILABLE, "Ready"

    def toner_level(self):
        return int(self.toner_percent)

    # --- operator actions -------------------------------------------------------

    def set_online(self, online):
        self.online = bool(online)

    def load_paper(self):
        with self._lock:
            self.paper_sheets = self.paper_capacity

    def replace_toner(self):
        with self._lock:
            self.toner_percent = 100.0

    def clear_jam(self):
        self.jammed = False

    # --- printing ---------------------------------------------------------------

    def precheck(self, job):
        """Reason why the job cannot start, or None."""
        sides, sheets = sides_and_sheets(job)
        toner = sides * TONER_PER_SIDE.get(job.get("color_mode"), TONER_PER_SIDE["COLOR"])

        if sheets > self.paper_sheets:
            return f"Not enough paper: the job needs {sheets} sheets, {self.paper_sheets} loaded"
        if toner > self.toner_percent:
            return "Not enough toner for this job"
        return None

    def print_job(self, job, document, on_progress=None):
        """Print ``document`` (PDF bytes) according to ``job``. Returns a PrintOutcome.

        ``on_progress(side, total_sides)`` is called after every printed side.
        """
        if not document.startswith(b"%PDF-"):
            return PrintOutcome(False, "The downloaded file is not a PDF")

        reason = self.precheck(job)
        if reason:
            return PrintOutcome(False, reason)

        sides, sheets = sides_and_sheets(job)
        sides_per_sheet = sides / sheets
        toner_per_side = TONER_PER_SIDE.get(job.get("color_mode"), TONER_PER_SIDE["COLOR"])

        jam_at = None
        if self.jam_next_job or (self.jam_rate and self.rng.random() < self.jam_rate):
            self.jam_next_job = False
            jam_at = self.rng.randint(1, sides)

        sheets_used = 0
        for side in range(1, sides + 1):
            if not self.online:
                return PrintOutcome(False, f"Printer was switched off on page {side}", side - 1, sheets_used)

            self.sleep(self.seconds_per_page)

            if side == jam_at:
                self.jammed = True
                return PrintOutcome(False, f"Paper jam on page {side} of {sides}", side - 1, sheets_used)

            with self._lock:
                new_sheet = math.ceil(side / sides_per_sheet) > sheets_used
                if new_sheet:
                    self.paper_sheets -= 1
                    sheets_used += 1
                self.toner_percent = max(0.0, self.toner_percent - toner_per_side)

            if on_progress:
                on_progress(side, sides)

        return PrintOutcome(True, "", sides, sheets_used)
