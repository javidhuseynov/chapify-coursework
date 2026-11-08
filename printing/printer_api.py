"""Printer API: used by print stations (the separate print_station application).

Authentication is per printer: ``Authorization: Printer <station key>``.
These endpoints never accept user tokens, and user endpoints never accept
station keys.
"""

import hashlib

from django.contrib.auth.models import AnonymousUser
from django.http import FileResponse
from django.urls import reverse
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from . import stations
from .models import AuditLog, Printer, PrintJob
from .serializers import ErrorSerializer
from .services import WorkflowError, audit, finish_print_job


class PrinterKeyAuthentication(BaseAuthentication):
    keyword = b"printer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()

        if not parts or parts[0].lower() != self.keyword:
            return None

        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid printer key header.")

        printer = stations.printer_for_key(parts[1].decode("ascii", errors="replace"))

        if printer is None:
            raise exceptions.AuthenticationFailed("Unknown or replaced printer key.")

        return AnonymousUser(), printer

    def authenticate_header(self, request):
        return "Printer"


class PrinterKeyScheme(OpenApiAuthenticationExtension):
    target_class = "printing.printer_api.PrinterKeyAuthentication"
    name = "printerKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Value: 'Printer <station key>' (generated on the Printers page).",
        }


class IsPrintStation(BasePermission):
    message = "A printer key is required."

    def has_permission(self, request, view):
        return isinstance(request.auth, Printer)


class StationThrottle(SimpleRateThrottle):
    """Rate limit per printer (settings: DEFAULT_THROTTLE_RATES["print_station"])."""

    scope = "print_station"

    def get_cache_key(self, request, view):
        ident = f"printer-{request.auth.pk}" if isinstance(request.auth, Printer) else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def station_endpoint(methods):
    """Common decorators for printer API views."""

    def decorate(func):
        func = throttle_classes([StationThrottle])(func)
        func = permission_classes([IsPrintStation])(func)
        func = authentication_classes([PrinterKeyAuthentication])(func)
        return api_view(methods)(func)

    return decorate


# --- Serializers -------------------------------------------------------------

class HeartbeatSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=stations.STATION_STATUSES)
    message = serializers.CharField(required=False, allow_blank=True, max_length=200)
    paper_sheets = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100000)
    toner_percent = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100)
    station = serializers.CharField(required=False, allow_blank=True, max_length=150,
                                    help_text="Name and version of the station software.")


class PrinterInfoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    location = serializers.CharField()
    status = serializers.CharField()


class HeartbeatResponseSerializer(serializers.Serializer):
    printer = PrinterInfoSerializer()
    queued_jobs = serializers.IntegerField()


class StationJobSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    resumed = serializers.BooleanField(help_text="True if this job was already started before (station restart).")
    print_request = serializers.IntegerField()
    owner = serializers.CharField(help_text="Username of the person who paid (for the output tray label).")
    file_name = serializers.CharField()
    pages = serializers.IntegerField()
    copies = serializers.IntegerField()
    color_mode = serializers.CharField()
    paper_format = serializers.CharField()
    duplex_mode = serializers.CharField()
    document_url = serializers.CharField()
    document_size = serializers.IntegerField()
    document_sha256 = serializers.CharField(help_text="Station checks the download against this hash.")


class FailureSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)


class JobResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    job_status = serializers.CharField()


# --- Helpers -------------------------------------------------------------------

def printer_info(printer):
    return {
        "id": printer.pk,
        "name": printer.printer_name,
        "location": printer.location,
        "status": printer.printer_status,
    }


def job_payload(job, resumed):
    print_request = job.print_request
    document = print_request.document
    digest = hashlib.sha256()

    with document.file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)

    return {
        "id": job.pk,
        "resumed": resumed,
        "print_request": print_request.pk,
        "owner": print_request.user.username,
        "file_name": document.file_name,
        "pages": print_request.document_pages,
        "copies": print_request.settings.copies,
        "color_mode": print_request.settings.color_mode,
        "paper_format": print_request.settings.paper_format,
        "duplex_mode": print_request.settings.duplex_mode,
        "document_url": reverse("printer_api_document", args=[job.pk]),
        "document_size": document.file.size,
        "document_sha256": digest.hexdigest(),
    }


def not_your_job():
    return Response(
        {"detail": "No such job in progress on this printer."},
        status=status.HTTP_404_NOT_FOUND,
    )


# --- Endpoints -----------------------------------------------------------------

TAGS = ["Print stations"]
AUTH = [{"printerKey": []}]


@extend_schema(
    tags=TAGS, auth=AUTH, summary="Report that the station is alive",
    description="Sent every few seconds. Reports the printer's status and consumables.",
    request=HeartbeatSerializer,
    responses={200: HeartbeatResponseSerializer},
)
@station_endpoint(["POST"])
def heartbeat(request):
    stations.expire_silent_stations()
    serializer = HeartbeatSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    printer = stations.record_heartbeat(
        request.auth,
        data["status"],
        message=data.get("message", ""),
        paper_sheets=data.get("paper_sheets"),
        toner_percent=data.get("toner_percent"),
        station_info=data.get("station", ""),
    )

    return Response(
        {
            "printer": printer_info(printer),
            "queued_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).count(),
        }
    )


@extend_schema(
    tags=TAGS, auth=AUTH, summary="Take the next job",
    description=(
        "Starts the oldest job this printer may print (QUEUED -> IN_PROGRESS) and returns it. "
        "204 when there is nothing to print. If the station already has a job in progress "
        "(for example after a restart), that job is returned again with resumed=true."
    ),
    request=None,
    responses={
        200: StationJobSerializer,
        204: OpenApiResponse(description="No job to print."),
        409: OpenApiResponse(ErrorSerializer, description="The printer is not available."),
    },
)
@station_endpoint(["POST"])
def next_job(request):
    stations.expire_silent_stations()
    printer = Printer.objects.get(pk=request.auth.pk)

    try:
        job, resumed = stations.claim_next_job(printer)
    except WorkflowError as error:
        return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)

    if job is None:
        if printer.printer_status != Printer.STATUS_AVAILABLE:
            return Response(
                {"detail": f"The printer is {printer.get_printer_status_display().lower()}; send a heartbeat with status AVAILABLE first."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    job = stations.running_job(printer, job.pk)

    if not job.print_request.document.has_file():
        finish_print_job(job, False, "Document file is missing.")
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(job_payload(job, resumed))


@extend_schema(
    tags=TAGS, auth=AUTH, summary="Download the document of a job in progress",
    responses={(200, "application/pdf"): OpenApiTypes.BINARY, 404: ErrorSerializer},
)
@station_endpoint(["GET"])
def job_document(request, job_id):
    job = stations.running_job(request.auth, job_id)

    if job is None or not job.print_request.document.has_file():
        return not_your_job()

    document = job.print_request.document
    audit(
        AuditLog.EVENT_PRINT_STATION,
        f"Print station of {request.auth.printer_name} downloaded {document.file_name} for job #{job.pk}.",
        print_request=job.print_request,
    )
    response = FileResponse(document.file.open("rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="job-{job.pk}.pdf"'
    response["Cache-Control"] = "no-store"
    return response


@extend_schema(
    tags=TAGS, auth=AUTH, summary="Report that a job was printed",
    request=None, responses={200: JobResultSerializer, 404: ErrorSerializer},
)
@station_endpoint(["POST"])
def complete_job(request, job_id):
    job = stations.running_job(request.auth, job_id)

    if job is None:
        return not_your_job()

    job = finish_print_job(job, True)
    return Response({"id": job.pk, "job_status": job.job_status})


@extend_schema(
    tags=TAGS, auth=AUTH, summary="Report that a job failed",
    description="The document is kept so that an administrator can print the job again.",
    request=FailureSerializer, responses={200: JobResultSerializer, 404: ErrorSerializer},
)
@station_endpoint(["POST"])
def fail_job(request, job_id):
    serializer = FailureSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    job = stations.running_job(request.auth, job_id)

    if job is None:
        return not_your_job()

    job = finish_print_job(job, False, f"Print station: {serializer.validated_data['reason']}")
    return Response({"id": job.pk, "job_status": job.job_status})
