"""The print station's work loop.

    every few seconds: heartbeat (status, paper, toner)
    when available:    ask for the next job
    for each job:      download the PDF, check its SHA-256 hash, print it,
                       report "complete" or "fail", write a receipt

The document is kept in memory only while it is printed and is never written
to disk; the receipt contains job details, not the document.
"""

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .client import ApiError, ConnectionProblem
from .device import STATUS_AVAILABLE, sides_and_sheets


class Station:
    def __init__(
        self,
        client,
        device,
        poll_interval=3.0,
        heartbeat_interval=10.0,
        receipts_dir=None,
        on_event=None,
        clock=time.monotonic,
    ):
        self.client = client
        self.device = device
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.receipts_dir = Path(receipts_dir) if receipts_dir else None
        self.on_event = on_event or (lambda kind, data: None)
        self.clock = clock
        self.connected = False
        self.printer = None  # {"id", "name", "location", "status"} from Chapify
        self.current_job = None
        self._last_heartbeat = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()

    # --- events (for the window or the console) ---------------------------------

    def emit(self, kind, **data):
        self.on_event(kind, data)

    def log(self, message):
        self.emit("log", message=message)

    # --- heartbeat --------------------------------------------------------------

    def heartbeat(self):
        status, message = self.device.status()
        try:
            reply = self.client.heartbeat(
                status, message, self.device.paper_sheets, self.device.toner_level()
            )
        except ConnectionProblem as error:
            self._set_connected(False, str(error))
            return False
        except ApiError as error:
            self._set_connected(False, f"Chapify refused the station: {error.detail}")
            return False

        self._last_heartbeat = self.clock()
        self.printer = reply["printer"]
        self._set_connected(True, "")
        self.emit("heartbeat", printer=self.printer, queued=reply.get("queued_jobs", 0), status=status, message=message)
        return True

    def request_heartbeat(self):
        """Send the state at the next opportunity (after an operator action)."""
        self._last_heartbeat = None
        self._wakeup.set()

    def heartbeat_if_due(self):
        if self._last_heartbeat is None or self.clock() - self._last_heartbeat >= self.heartbeat_interval:
            self.heartbeat()

    def _set_connected(self, connected, problem):
        if connected != self.connected:
            self.connected = connected
            self.emit("connection", connected=connected, problem=problem)
            self.log("Connected to Chapify." if connected else f"Connection lost. {problem}")

    # --- jobs -------------------------------------------------------------------

    def step(self):
        """One cycle: heartbeat if due, then take and print at most one job.

        Returns True if a job was processed.
        """
        self.heartbeat_if_due()

        if not self.connected or self.device.status()[0] != STATUS_AVAILABLE:
            return False

        try:
            job = self.client.next_job()
        except ConnectionProblem as error:
            self._set_connected(False, str(error))
            return False
        except ApiError as error:
            if error.status == 409:
                # Chapify still considers the printer unavailable: report our state now.
                self.heartbeat()
            else:
                self.log(f"Could not take a job: {error.detail}")
            return False

        if job is None:
            return False

        self.process(job)
        return True

    def process(self, job):
        self.current_job = job
        sides, sheets = sides_and_sheets(job)
        self.emit("job_started", job=job, sides=sides, sheets=sheets)
        self.log(
            f"Job #{job['id']}{' (resumed)' if job.get('resumed') else ''}: {job['file_name']} for "
            f"{job['owner']}, {job['pages']} page(s) x {job['copies']}, {job['color_mode']}, "
            f"{job['paper_format']}, {job['duplex_mode']}."
        )
        started = datetime.now(timezone.utc)

        try:
            outcome = self._print(job)
            if outcome.success:
                self.client.complete(job["id"])
                self.log(f"Job #{job['id']} printed: {outcome.sides_printed} side(s) on {outcome.sheets_used} sheet(s).")
            else:
                self.client.fail(job["id"], outcome.reason)
                self.log(f"Job #{job['id']} failed: {outcome.reason}.")
        except ConnectionProblem as error:
            # Chapify's watchdog fails the job if the station stays away.
            self._set_connected(False, str(error))
            self.emit("job_finished", job=job, success=False, reason="Connection lost")
            self.current_job = None
            return
        except ApiError as error:
            self.log(f"Chapify did not accept the result of job #{job['id']}: {error.detail}")
            self.emit("job_finished", job=job, success=False, reason=error.detail)
            self.current_job = None
            return

        self._write_receipt(job, outcome, started)
        self.emit("job_finished", job=job, success=outcome.success, reason=outcome.reason)
        self.current_job = None
        self.heartbeat()

    def _print(self, job):
        from .device import PrintOutcome

        document = self.client.download(job["document_url"])

        if len(document) != job["document_size"] or hashlib.sha256(document).hexdigest() != job["document_sha256"]:
            return PrintOutcome(False, "The downloaded document is damaged (size or SHA-256 hash mismatch)")

        def progress(side, total):
            self.emit("progress", job=job, side=side, total=total)
            self.heartbeat_if_due()

        try:
            return self.device.print_job(job, document, on_progress=progress)
        finally:
            del document  # never written to disk

    def _write_receipt(self, job, outcome, started):
        if self.receipts_dir is None:
            return
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        receipt = {
            "job": job["id"],
            "print_request": job["print_request"],
            "printer": (self.printer or {}).get("name"),
            "owner": job["owner"],
            "file_name": job["file_name"],
            "settings": {key: job[key] for key in ("pages", "copies", "color_mode", "paper_format", "duplex_mode")},
            "result": "printed" if outcome.success else "failed",
            "reason": outcome.reason,
            "sides_printed": outcome.sides_printed,
            "sheets_used": outcome.sheets_used,
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        path = self.receipts_dir / f"job-{job['id']}.json"
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    # --- running ----------------------------------------------------------------

    def run_once(self):
        """Heartbeat, then print every job that is waiting. Returns the number processed."""
        self.heartbeat()
        processed = 0
        while self.step():
            processed += 1
        return processed

    def run_forever(self):
        self.log("Print station started.")
        while not self.stop_event.is_set():
            try:
                worked = self.step()
            except Exception as error:  # keep the station alive; report the problem
                self.log(f"Unexpected error: {error!r}")
                worked = False
            if not worked:
                self._wakeup.wait(self.poll_interval)
                self._wakeup.clear()
        self.log("Print station stopped.")

    def stop(self):
        self.stop_event.set()
        self._wakeup.set()
