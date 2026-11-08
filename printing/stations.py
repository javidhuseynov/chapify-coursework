"""Print stations: printers driven by the separate print station application.

An administrator connects a printer to a print station by generating a
station key (shown once; only its SHA-256 hash is stored). The station then
calls the printer API (printing/printer_api.py) with that key:

    heartbeat  -> "I am online, this is my status, paper and toner"
    jobs/next  -> "give me the next job" (QUEUED -> IN_PROGRESS)
    document   -> download the PDF of the job it is printing
    complete / fail -> report the result (IN_PROGRESS -> COMPLETED / FAILED)

If a station stops sending heartbeats, the watchdog marks its printer OFFLINE
and fails the job it was printing, so that an administrator can print it again.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AuditLog, Printer, PrintJob
from .services import WorkflowError, audit, finish_print_job, start_next_print_job

KEY_PREFIX = "prn_"
STATION_STATUSES = (Printer.STATUS_AVAILABLE, Printer.STATUS_OFFLINE, Printer.STATUS_ERROR)


def _who(actor):
    return f"Administrator {actor.username}" if actor is not None else "The command line"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def issue_station_key(printer, actor):
    """Generate a new key for ``printer``; any previous key stops working.

    The printer is OFFLINE until the station's first heartbeat. Returns the
    raw key, which is shown to the administrator once.
    """
    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)

    with transaction.atomic():
        printer = Printer.objects.select_for_update().get(pk=printer.pk)
        _fail_running_jobs(printer, "Print station was replaced by a new one.")
        printer.station_key_hash = hash_key(raw_key)
        printer.station_key_prefix = raw_key[:12]
        printer.station_last_seen_at = None
        printer.station_info = ""
        printer.printer_status = Printer.STATUS_OFFLINE
        printer.save()
        audit(
            AuditLog.EVENT_PRINT_STATION,
            f"{_who(actor)} generated a print station key for {printer.printer_name} "
            f"({printer.station_key_prefix}...). The printer is offline until the station connects.",
            user=actor,
        )

    return raw_key


def disconnect_station(printer, actor):
    """Remove the station key: the printer goes back to the built-in simulator."""
    with transaction.atomic():
        printer = Printer.objects.select_for_update().get(pk=printer.pk)

        if not printer.has_station:
            raise WorkflowError(f"{printer.printer_name} has no print station.")

        _fail_running_jobs(printer, "Print station was disconnected by an administrator.")
        printer.station_key_hash = ""
        printer.station_key_prefix = ""
        printer.station_last_seen_at = None
        printer.station_info = ""
        printer.paper_sheets = None
        printer.toner_percent = None
        printer.printer_status = Printer.STATUS_OFFLINE
        printer.save()
        audit(
            AuditLog.EVENT_PRINT_STATION,
            f"{_who(actor)} disconnected the print station of {printer.printer_name}. "
            "The printer is offline; set it to Available to use the built-in simulator.",
            user=actor,
        )

    return printer


def printer_for_key(raw_key):
    if not raw_key or not raw_key.startswith(KEY_PREFIX):
        return None
    return Printer.objects.filter(station_key_hash=hash_key(raw_key)).first()


def _fail_running_jobs(printer, reason):
    for job in PrintJob.objects.filter(printer=printer, job_status=PrintJob.STATUS_IN_PROGRESS):
        finish_print_job(job, False, reason)


def record_heartbeat(printer, status, message="", paper_sheets=None, toner_percent=None, station_info=""):
    """Store what the station reports. Returns the updated printer."""
    if status not in STATION_STATUSES:
        raise WorkflowError("Status must be AVAILABLE, OFFLINE or ERROR.")

    with transaction.atomic():
        printer = Printer.objects.select_for_update().get(pk=printer.pk)
        old_status = printer.printer_status
        was_silent = printer.station_last_seen_at is None

        printer.station_last_seen_at = timezone.now()
        printer.paper_sheets = paper_sheets
        printer.toner_percent = toner_percent
        if station_info:
            printer.station_info = station_info[:150]

        # While a job is printing the printer stays BUSY; the job result frees it.
        if old_status != Printer.STATUS_BUSY:
            printer.printer_status = status

        printer.save()

        if was_silent:
            audit(
                AuditLog.EVENT_PRINT_STATION,
                f"Print station of {printer.printer_name} connected"
                + (f" ({printer.station_info})." if printer.station_info else "."),
            )

        if printer.printer_status != old_status:
            audit(
                AuditLog.EVENT_PRINT_STATION,
                f"Print station reported {printer.printer_name}: {old_status} -> {printer.printer_status}"
                + (f" ({message[:120]})." if message else "."),
            )

    return printer


def claim_next_job(printer):
    """Return the job this station should print now, or None.

    If the station still has a job IN_PROGRESS (for example after a restart),
    that job is returned again so it can be finished.
    """
    running = (
        PrintJob.objects
        .filter(printer=printer, job_status=PrintJob.STATUS_IN_PROGRESS)
        .select_related("print_request__document", "print_request__settings")
        .first()
    )

    if running is not None:
        return running, True

    job = start_next_print_job(printer=printer)
    return job, False


def running_job(printer, job_id):
    """The station's own IN_PROGRESS job with this id, or None."""
    return (
        PrintJob.objects
        .filter(pk=job_id, printer=printer, job_status=PrintJob.STATUS_IN_PROGRESS)
        .select_related("print_request__document", "print_request__settings", "print_request__user")
        .first()
    )


def expire_silent_stations(now=None):
    """Watchdog: mark printers whose station stopped responding OFFLINE.

    Their running jobs fail (with the file kept) so that an administrator can
    print them again. Returns the number of printers marked offline.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.PRINT_STATION_TIMEOUT_SECONDS)
    silent = (
        Printer.objects
        .exclude(station_key_hash="")
        .exclude(printer_status=Printer.STATUS_OFFLINE)
        .filter(Q(station_last_seen_at__lt=cutoff) | Q(station_last_seen_at__isnull=True))
    )
    count = 0

    for printer in silent:
        with transaction.atomic():
            _fail_running_jobs(printer, "Print station stopped responding.")
            updated = Printer.objects.filter(pk=printer.pk).exclude(
                printer_status=Printer.STATUS_OFFLINE
            ).update(printer_status=Printer.STATUS_OFFLINE)

            if updated:
                count += 1
                audit(
                    AuditLog.EVENT_PRINT_STATION,
                    f"Print station of {printer.printer_name} stopped responding; printer set to OFFLINE.",
                )

    return count


def is_connected(printer, now=None):
    if not printer.has_station or printer.station_last_seen_at is None:
        return False
    limit = timedelta(seconds=settings.PRINT_STATION_TIMEOUT_SECONDS)
    return (now or timezone.now()) - printer.station_last_seen_at <= limit
