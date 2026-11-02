"""Business logic of the Chapify print-and-pay workflow.

Web views, REST API views and management commands all call these functions,
so every rule (allowed status changes, payment checks, file retention, audit
logging) is implemented exactly once.

Concurrency: every status change is a conditional UPDATE ("change the status
only if it is still X"). If two actions race (double click, confirm and
cancel at the same time, a replayed gateway notification), only one of them
can win; the other gets a WorkflowError instead of creating duplicates.
Each function runs inside a database transaction, so a failure part-way
leaves no half-finished state behind.
"""

import os
import random
import uuid
from dataclasses import dataclass
from typing import NoReturn
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    AuditLog,
    Document,
    PaymentTransaction,
    Printer,
    PrintJob,
    PrintRequest,
    PrintSettings,
)


class WorkflowError(Exception):
    """An action is not allowed in the current state. The message is user-facing."""


# Allowed print request status changes (thesis section 4.4, with payment retry).
ALLOWED_TRANSITIONS = {
    PrintRequest.STATUS_AWAITING_PAYMENT: {
        PrintRequest.STATUS_PAYMENT_CONFIRMED,
        PrintRequest.STATUS_PAYMENT_REJECTED,
        PrintRequest.STATUS_CANCELLED,
    },
    PrintRequest.STATUS_PAYMENT_REJECTED: {
        PrintRequest.STATUS_AWAITING_PAYMENT,  # user retries the payment
        PrintRequest.STATUS_CANCELLED,
    },
    PrintRequest.STATUS_PAYMENT_CONFIRMED: {
        PrintRequest.STATUS_COMPLETED,
        PrintRequest.STATUS_FAILED,
    },
}


def audit(event_type, description, user=None, print_request=None):
    return AuditLog.objects.create(
        user=user,
        print_request=print_request,
        event_type=event_type,
        description=description,
    )


def transition(print_request, new_status):
    """Atomically move a request to ``new_status`` if the move is allowed."""
    allowed_from = [
        status for status, targets in ALLOWED_TRANSITIONS.items() if new_status in targets
    ]

    updated = PrintRequest.objects.filter(
        pk=print_request.pk,
        status__in=allowed_from,
    ).update(status=new_status, updated_at=timezone.now())

    if not updated:
        print_request.refresh_from_db(fields=["status"])
        raise WorkflowError(
            f"Request #{print_request.pk} cannot change from "
            f"{print_request.get_status_display()} to "
            f"{dict(PrintRequest.STATUS_CHOICES)[new_status]}."
        )

    previous_status = print_request.status
    print_request.refresh_from_db(fields=["status", "updated_at"])
    return previous_status


def _delete_document_file(print_request, user, reason):
    document = print_request.document

    if document.delete_file_from_storage():
        audit(
            AuditLog.EVENT_DOCUMENT_DELETED,
            f"Uploaded document file for request #{print_request.pk} was deleted from storage ({reason}).",
            user=user,
            print_request=print_request,
        )
        return True

    return False


def _cancel_open_payment_attempts(print_request):
    return PaymentTransaction.objects.filter(
        print_request=print_request,
        payment_status=PaymentTransaction.STATUS_INITIATED,
    ).update(payment_status=PaymentTransaction.STATUS_CANCELLED, updated_at=timezone.now())


# ---------------------------------------------------------------------------
# Documents and print requests
# ---------------------------------------------------------------------------

def store_uploaded_document(user, uploaded_file, channel="web"):
    """Save an already validated upload and record it in the audit log."""
    extension = os.path.splitext(uploaded_file.name)[1].lower().lstrip(".")
    original_name = os.path.basename(uploaded_file.name)

    with transaction.atomic():
        document = Document.objects.create(
            user=user,
            file=uploaded_file,
            file_name=original_name,
            file_type=extension,
            file_size=uploaded_file.size,
            validation_status=Document.STATUS_VALID,
        )
        # Record the name the storage actually used (it may add a suffix).
        document.temporary_storage_path = document.file.name
        document.save(update_fields=["temporary_storage_path"])

        label = "API document" if channel == "api" else "Document"
        audit(
            AuditLog.EVENT_DOCUMENT_UPLOADED,
            f"{label} uploaded: {document.file_name} ({document.file_size} bytes).",
            user=user,
        )
        audit(
            AuditLog.EVENT_DOCUMENT_VALIDATED,
            f"{label} passed type and size validation: {document.file_name}.",
            user=user,
        )

    return document


def ensure_document_can_be_used(document):
    if PrintRequest.objects.filter(document=document).exists():
        raise WorkflowError(
            "This document already belongs to a print request. Upload the file again to create a new request."
        )

    if not document.has_file():
        raise WorkflowError(
            "The uploaded file is no longer available. Please upload the document again."
        )


@dataclass
class PrintOptions:
    document_pages: int
    copies: int
    color_mode: str
    paper_format: str
    duplex_mode: str

    @classmethod
    def from_cleaned_data(cls, data):
        return cls(
            document_pages=data["document_pages"],
            copies=data["copies"],
            color_mode=data["color_mode"],
            paper_format=data["paper_format"],
            duplex_mode=data["duplex_mode"],
        )


def create_print_request(user, document, options, channel="web"):
    if document.user_id != user.pk:
        raise WorkflowError("Document not found.")

    with transaction.atomic():
        ensure_document_can_be_used(document)

        print_settings = PrintSettings.objects.create(
            copies=options.copies,
            color_mode=options.color_mode,
            paper_format=options.paper_format,
            duplex_mode=options.duplex_mode,
        )
        print_request = PrintRequest(
            user=user,
            document=document,
            settings=print_settings,
            document_pages=options.document_pages,
            status=PrintRequest.STATUS_AWAITING_PAYMENT,
        )
        print_request.calculate_price()
        print_request.save()

        prefix = "API print request" if channel == "api" else "Print request"
        audit(
            AuditLog.EVENT_PRINT_REQUEST_CREATED,
            (
                f"{prefix} #{print_request.pk} created. Pages: {print_request.document_pages}, "
                f"copies: {print_settings.copies}, total price: {print_request.total_price} EUR."
            ),
            user=user,
            print_request=print_request,
        )

    return print_request


def update_print_request(print_request, options, user):
    with transaction.atomic():
        print_request = PrintRequest.objects.select_related("settings").get(pk=print_request.pk)

        if not print_request.is_open:
            raise WorkflowError("Only requests that have not been paid can be edited.")

        print_settings = print_request.settings
        print_settings.copies = options.copies
        print_settings.color_mode = options.color_mode
        print_settings.paper_format = options.paper_format
        print_settings.duplex_mode = options.duplex_mode

        print_request.document_pages = options.document_pages
        new_total = print_request.calculate_price()

        # Conditional update: refuse if a payment confirmed the request meanwhile.
        updated = PrintRequest.objects.filter(
            pk=print_request.pk,
            status__in=PrintRequest.OPEN_STATUSES,
        ).update(
            document_pages=options.document_pages,
            total_price=new_total,
            updated_at=timezone.now(),
        )

        if not updated:
            raise WorkflowError("Only requests that have not been paid can be edited.")

        print_settings.save()
        # A checkout opened for the old price must not be completed any more.
        _cancel_open_payment_attempts(print_request)

        audit(
            AuditLog.EVENT_PRINT_REQUEST_UPDATED,
            (
                f"User updated print request #{print_request.pk}. New pages: {options.document_pages}, "
                f"copies: {options.copies}, total price: {new_total} EUR."
            ),
            user=user,
            print_request=print_request,
        )

    print_request.refresh_from_db()
    return print_request


def cancel_print_request(print_request, user, reason="cancelled by the user"):
    with transaction.atomic():
        transition(print_request, PrintRequest.STATUS_CANCELLED)
        _cancel_open_payment_attempts(print_request)

        audit(
            AuditLog.EVENT_PRINT_REQUEST_CANCELLED,
            f"Print request #{print_request.pk} was {reason}.",
            user=user,
            print_request=print_request,
        )
        _delete_document_file(print_request, user, "request cancelled")

    return print_request


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def initiate_payment(print_request, user):
    """Create (or reuse) the payment attempt that the gateway checkout will use."""
    with transaction.atomic():
        print_request = PrintRequest.objects.select_related("document").get(pk=print_request.pk)

        if not print_request.is_open:
            raise WorkflowError("This request is not waiting for payment.")

        if not print_request.document.has_file():
            raise WorkflowError(
                "The uploaded file is no longer available, so this request cannot be paid. "
                "Please cancel it and upload the document again."
            )

        if print_request.status == PrintRequest.STATUS_PAYMENT_REJECTED:
            transition(print_request, PrintRequest.STATUS_AWAITING_PAYMENT)

        # Reuse an open attempt for the same amount (e.g. user pressed "Pay" twice).
        existing = (
            PaymentTransaction.objects
            .filter(
                print_request=print_request,
                payment_status=PaymentTransaction.STATUS_INITIATED,
                amount=print_request.total_price,
            )
            .order_by("-payment_date")
            .first()
        )

        if existing:
            return existing

        _cancel_open_payment_attempts(print_request)

        payment = PaymentTransaction.objects.create(
            print_request=print_request,
            amount=print_request.total_price,
            currency=settings.PAYMENT_CURRENCY,
            payment_status=PaymentTransaction.STATUS_INITIATED,
        )

        audit(
            AuditLog.EVENT_PAYMENT_INITIATED,
            (
                f"Payment {payment.reference} initiated for request #{print_request.pk}: "
                f"{payment.amount} {payment.currency}."
            ),
            user=user,
            print_request=print_request,
        )

    return payment


@dataclass
class PaymentOutcome:
    payment: PaymentTransaction
    result: str  # "confirmed", "rejected" or "duplicate"


GATEWAY_STATUS_APPROVED = "APPROVED"
GATEWAY_STATUS_DECLINED = "DECLINED"


def refuse_notification(reason, print_request=None) -> NoReturn:
    audit(
        AuditLog.EVENT_PAYMENT_NOTIFICATION_REFUSED,
        f"Payment notification refused: {reason}",
        print_request=print_request,
    )
    raise WorkflowError(f"Payment notification refused: {reason}")


def apply_payment_notification(data):
    """Apply a payment result whose signature has ALREADY been verified.

    ``data`` comes from the gateway and contains: reference, status
    (APPROVED/DECLINED), amount, currency and gateway_transaction_id.
    Processing is idempotent: the same notification delivered twice has an
    effect only once.
    """
    reference = str(data.get("reference", ""))
    gateway_status = data.get("status")
    gateway_transaction_id = str(data.get("gateway_transaction_id", ""))[:100]

    try:
        amount = Decimal(str(data.get("amount")))
    except (InvalidOperation, TypeError):
        refuse_notification("invalid amount.")

    payment = (
        PaymentTransaction.objects
        .select_related("print_request")
        .filter(reference=reference)
        .first()
        if _is_uuid(reference)
        else None
    )

    if payment is None:
        refuse_notification(f"unknown payment reference '{reference[:40]}'.")

    print_request = payment.print_request

    if gateway_status not in (GATEWAY_STATUS_APPROVED, GATEWAY_STATUS_DECLINED):
        refuse_notification(f"unknown payment status for {payment.reference}.", print_request)

    # Repeated delivery of a notification that was already applied.
    final_status = (
        PaymentTransaction.STATUS_CONFIRMED
        if gateway_status == GATEWAY_STATUS_APPROVED
        else PaymentTransaction.STATUS_REJECTED
    )

    if payment.payment_status == final_status and payment.gateway_reference == gateway_transaction_id:
        return PaymentOutcome(payment, "duplicate")

    if payment.payment_status != PaymentTransaction.STATUS_INITIATED:
        refuse_notification(
            f"payment {payment.reference} is no longer active (status {payment.payment_status}).",
            print_request,
        )

    if amount != payment.amount or data.get("currency") != payment.currency:
        refuse_notification(
            f"amount/currency mismatch for payment {payment.reference}: "
            f"expected {payment.amount} {payment.currency}, got {amount} {data.get('currency')}.",
            print_request,
        )

    try:
        with transaction.atomic():
            claimed = PaymentTransaction.objects.filter(
                pk=payment.pk,
                payment_status=PaymentTransaction.STATUS_INITIATED,
            ).update(
                payment_status=final_status,
                gateway_reference=gateway_transaction_id,
                payment_date=timezone.now(),
                updated_at=timezone.now(),
            )

            if not claimed:
                # Another delivery of this notification won the race.
                payment.refresh_from_db()
                if payment.payment_status == final_status:
                    return PaymentOutcome(payment, "duplicate")
                raise WorkflowError("This payment was already processed.")

            if final_status == PaymentTransaction.STATUS_CONFIRMED:
                transition(print_request, PrintRequest.STATUS_PAYMENT_CONFIRMED)
                audit(
                    AuditLog.EVENT_PAYMENT_CONFIRMED,
                    (
                        f"Payment {payment.reference} confirmed by the gateway "
                        f"(gateway transaction {gateway_transaction_id}, {payment.amount} {payment.currency})."
                    ),
                    user=print_request.user,
                    print_request=print_request,
                )
                _queue_print_job(print_request)
                result = "confirmed"
            else:
                transition(print_request, PrintRequest.STATUS_PAYMENT_REJECTED)
                audit(
                    AuditLog.EVENT_PAYMENT_REJECTED,
                    (
                        f"Payment {payment.reference} declined by the gateway "
                        f"(gateway transaction {gateway_transaction_id}). The user may retry."
                    ),
                    user=print_request.user,
                    print_request=print_request,
                )
                result = "rejected"
    except IntegrityError:
        # Database safety net: a second CONFIRMED payment or second print job.
        raise WorkflowError("This request has already been paid.")

    payment.refresh_from_db()
    return PaymentOutcome(payment, result)


def _is_uuid(value):
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


# ---------------------------------------------------------------------------
# Print jobs (simulated print server)
# ---------------------------------------------------------------------------

def _queue_print_job(print_request):
    printer = (
        Printer.objects
        .filter(printer_status=Printer.STATUS_AVAILABLE)
        .order_by("id")
        .first()
    )
    job = PrintJob.objects.create(
        print_request=print_request,
        printer=printer,
        job_status=PrintJob.STATUS_QUEUED,
    )
    audit(
        AuditLog.EVENT_PRINT_JOB_CREATED,
        f"Print job #{job.pk} queued for request #{print_request.pk}"
        + (f" on {printer.printer_name}." if printer else " (waiting for an available printer)."),
        user=print_request.user,
        print_request=print_request,
    )
    return job


def start_next_print_job():
    """Take the oldest queued job and mark it IN_PROGRESS on an available printer.

    Returns the job, or None when nothing can be started (empty queue or no
    available printer).
    """
    with transaction.atomic():
        job = (
            PrintJob.objects
            .filter(job_status=PrintJob.STATUS_QUEUED)
            .select_related("printer", "print_request")
            .order_by("created_at", "id")
            .first()
        )

        if job is None:
            return None

        printer = job.printer

        if printer is None or printer.printer_status != Printer.STATUS_AVAILABLE:
            printer = (
                Printer.objects
                .filter(printer_status=Printer.STATUS_AVAILABLE)
                .order_by("id")
                .first()
            )

        if printer is None:
            return None

        claimed_printer = Printer.objects.filter(
            pk=printer.pk,
            printer_status=Printer.STATUS_AVAILABLE,
        ).update(printer_status=Printer.STATUS_BUSY)

        claimed_job = PrintJob.objects.filter(
            pk=job.pk,
            job_status=PrintJob.STATUS_QUEUED,
        ).update(job_status=PrintJob.STATUS_IN_PROGRESS, printer=printer, started_at=timezone.now())

        if not (claimed_printer and claimed_job):
            transaction.set_rollback(True)
            return None

        audit(
            AuditLog.EVENT_PRINT_JOB_STATUS_CHANGED,
            f"Print job #{job.pk} started on {printer.printer_name} (QUEUED -> IN_PROGRESS).",
            print_request=job.print_request,
        )

    job.refresh_from_db()
    return job


def finish_print_job(job, success, failure_reason="", actor=None):
    """Complete or fail an IN_PROGRESS job and close its print request."""
    with transaction.atomic():
        new_status = PrintJob.STATUS_COMPLETED if success else PrintJob.STATUS_FAILED

        updated = PrintJob.objects.filter(
            pk=job.pk,
            job_status=PrintJob.STATUS_IN_PROGRESS,
        ).update(
            job_status=new_status,
            completed_at=timezone.now(),
            failure_reason="" if success else failure_reason[:255],
        )

        if not updated:
            raise WorkflowError(f"Print job #{job.pk} is not in progress.")

        job.refresh_from_db()

        if job.printer_id:
            Printer.objects.filter(
                pk=job.printer_id,
                printer_status=Printer.STATUS_BUSY,
            ).update(printer_status=Printer.STATUS_AVAILABLE)

        print_request = job.print_request
        transition(
            print_request,
            PrintRequest.STATUS_COMPLETED if success else PrintRequest.STATUS_FAILED,
        )

        audit(
            AuditLog.EVENT_PRINT_JOB_STATUS_CHANGED,
            (
                f"Print job #{job.pk} finished: IN_PROGRESS -> {new_status}"
                + ("." if success else f" ({failure_reason}).")
            ),
            user=actor,
            print_request=print_request,
        )
        _delete_document_file(
            print_request,
            actor,
            "print job completed" if success else "print job failed",
        )

    return job


def process_next_print_job(fail_rate=0.0, force_failure=False, rng=None, actor=None):
    """Simulated print server step: start the next job and finish it.

    The job fails when ``force_failure`` is set, when the document file is
    missing, or randomly with probability ``fail_rate`` (0.0 - 1.0).
    Returns the finished job, or None if nothing could be processed.
    """
    job = start_next_print_job()

    if job is None:
        return None

    rng = rng or random.Random()

    if not job.print_request.document.has_file():
        return finish_print_job(job, False, "Document file is missing.", actor=actor)

    if force_failure or (fail_rate > 0 and rng.random() < fail_rate):
        return finish_print_job(job, False, "Simulated printer error.", actor=actor)

    return finish_print_job(job, True, actor=actor)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def cleanup_documents(older_than_hours=None, dry_run=False, now=None):
    """Apply the retention policy (NFR-10). Returns a summary dict."""
    hours = settings.DOCUMENT_RETENTION_HOURS if older_than_hours is None else older_than_hours
    cutoff = (now or timezone.now()) - timedelta(hours=hours)
    summary = {"expired_requests": 0, "orphan_files": 0, "terminal_files": 0}

    # 1. Requests that were never paid: expire (cancel) them.
    stale_requests = PrintRequest.objects.filter(
        status__in=PrintRequest.OPEN_STATUSES,
        updated_at__lt=cutoff,
    )
    for print_request in stale_requests:
        summary["expired_requests"] += 1
        if not dry_run:
            try:
                cancel_print_request(
                    print_request,
                    user=None,
                    reason=f"expired by the retention policy (not paid within {hours} h)",
                )
            except WorkflowError:
                summary["expired_requests"] -= 1

    # 2. Uploads that never became a print request.
    orphan_documents = Document.objects.filter(
        upload_time__lt=cutoff,
        printrequest__isnull=True,
    )
    for document in orphan_documents:
        if document.has_file():
            summary["orphan_files"] += 1
            if not dry_run:
                document.delete_file_from_storage()
                audit(
                    AuditLog.EVENT_DOCUMENT_DELETED,
                    f"Abandoned upload {document.file_name} (document #{document.pk}) deleted by the retention policy.",
                    user=document.user,
                )

    # 3. Safety net: finished requests must not keep files.
    finished_requests = PrintRequest.objects.filter(
        status__in=PrintRequest.TERMINAL_STATUSES,
    ).select_related("document")
    for print_request in finished_requests:
        if print_request.document.has_file():
            summary["terminal_files"] += 1
            if not dry_run:
                _delete_document_file(print_request, None, "retention policy")

    return summary
