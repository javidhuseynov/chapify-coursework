import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import payments, services
from .forms import DocumentUploadForm, PrintSettingsForm, RegisterForm
from .models import (
    AuditLog,
    Document,
    PaymentTransaction,
    Printer,
    PrintJob,
    PrintRequest,
    Profile,
)
from .login_protection import ThrottledAuthenticationForm
from .permissions import IsChapifyAdmin, chapify_admin_required
from .serializers import (
    AuditLogSerializer,
    CreatePrintRequestSerializer,
    PaymentTransactionSerializer,
    PrintJobSerializer,
    PrintRequestSerializer,
    PrinterSerializer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_user_print_request_or_404(request, request_id):
    """Object-level access control: users only ever see their own requests."""
    return get_object_or_404(
        PrintRequest.objects.select_related("document", "settings"),
        id=request_id,
        user=request.user,
    )


def get_user_document_or_404(request, document_id):
    return get_object_or_404(Document, id=document_id, user=request.user)


def filter_print_requests(queryset, params, include_username=False):
    status_filter = params.get("status", "").strip()
    search_query = params.get("q", "").strip()

    if status_filter:
        queryset = queryset.filter(status=status_filter)

    if search_query:
        query_filter = Q(document__file_name__icontains=search_query)

        if include_username:
            query_filter |= Q(user__username__icontains=search_query)

        if search_query.isdigit():
            query_filter |= Q(id=int(search_query))

        queryset = queryset.filter(query_filter)

    return queryset, status_filter, search_query


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def home(request):
    return render(request, "printing/home.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()  # the Profile is created by printing.signals
            services.audit(
                AuditLog.EVENT_ACCOUNT_REGISTERED,
                f"New account registered: {user.username}",
                user=user,
            )
            login(request, user)  # LOGIN_SUCCESS is logged by printing.signals

            return redirect("home")
    else:
        form = RegisterForm()

    return render(request, "printing/register.html", {"form": form})


class ChapifyLoginView(LoginView):
    template_name = "printing/login.html"
    form_class = ThrottledAuthenticationForm  # locks out after repeated failures


class ChapifyLogoutView(LogoutView):
    pass


# ---------------------------------------------------------------------------
# User workflow (web)
# ---------------------------------------------------------------------------

@login_required
def upload_document(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)

        if form.is_valid():
            document = services.store_uploaded_document(
                request.user,
                form.cleaned_data["file"],
                page_count=form.page_count,
            )
            return redirect("print_settings", document_id=document.id)
    else:
        form = DocumentUploadForm()

    return render(request, "printing/upload_document.html", {"form": form})


@login_required
def print_settings(request, document_id):
    document = get_user_document_or_404(request, document_id)

    try:
        services.ensure_document_can_be_used(document)
    except services.WorkflowError as error:
        messages.error(request, str(error))
        existing = PrintRequest.objects.filter(document=document, user=request.user).first()
        if existing:
            return redirect("request_status", request_id=existing.id)
        return redirect("upload_document")

    if request.method == "POST":
        form = PrintSettingsForm(request.POST)

        if form.is_valid():
            try:
                print_request = services.create_print_request(
                    request.user,
                    document,
                    services.PrintOptions.from_cleaned_data(form.cleaned_data),
                )
            except services.WorkflowError as error:
                messages.error(request, str(error))
                return redirect("request_history")

            return redirect("payment", request_id=print_request.id)
    else:
        form = PrintSettingsForm()

    return render(request, "printing/print_settings.html", {"form": form, "document": document})


@login_required
def payment(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    if not print_request.is_open:
        return redirect("request_status", request_id=print_request.id)

    if request.method == "POST":
        try:
            payment_attempt = services.initiate_payment(print_request, request.user)
        except services.WorkflowError as error:
            messages.error(request, str(error))
            return redirect("request_status", request_id=print_request.id)

        return redirect(payments.build_checkout_url(request, payment_attempt))

    return render(
        request,
        "printing/payment.html",
        {
            "print_request": print_request,
            "last_payment": print_request.latest_payment(),
        },
    )


@require_GET
def payment_return(request):
    """Return URL: the gateway sends the payer back here with a signed result."""
    token = request.GET.get("notification", "")

    try:
        outcome = payments.handle_notification(token)
    except services.WorkflowError as error:
        messages.error(request, str(error))
        return redirect("request_history")

    if outcome.payment.payment_status == PaymentTransaction.STATUS_CONFIRMED:
        messages.success(request, "Payment confirmed by the gateway. Your print job is in the queue.")
    else:
        messages.warning(request, "The payment was declined by the gateway. You can try again or cancel the request.")

    return redirect("request_status", request_id=outcome.payment.print_request_id)


@csrf_exempt
@require_POST
def payment_callback(request):
    """Server-to-server notification endpoint for the gateway (webhook).

    Accepts the signed notification as form field "notification" or as JSON
    {"notification": "..."}. CSRF protection is not applicable here because
    the request is authenticated by its HMAC signature, not by a session.
    """
    token = request.POST.get("notification", "")

    if not token and request.content_type == "application/json":
        try:
            token = json.loads(request.body or b"{}").get("notification", "")
        except (ValueError, AttributeError):
            token = ""

    try:
        outcome = payments.handle_notification(token)
    except services.WorkflowError as error:
        return JsonResponse({"accepted": False, "detail": str(error)}, status=400)

    return JsonResponse(
        {
            "accepted": True,
            "result": outcome.result,
            "payment_reference": str(outcome.payment.reference),
            "payment_status": outcome.payment.payment_status,
        }
    )


@login_required
def request_status(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    return render(
        request,
        "printing/request_status.html",
        {
            "print_request": print_request,
            "payment_transaction": print_request.latest_payment(),
            "payment_attempts": print_request.payments.order_by("-payment_date", "-id"),
            "print_job": PrintJob.objects.filter(print_request=print_request).select_related("printer").first(),
        },
    )


@login_required
def request_history(request):
    print_requests = (
        PrintRequest.objects
        .filter(user=request.user)
        .select_related("document", "settings")
        .order_by("-created_at")
    )
    print_requests, status_filter, search_query = filter_print_requests(print_requests, request.GET)

    return render(
        request,
        "printing/request_history.html",
        {
            "print_requests": print_requests,
            "status_choices": PrintRequest.STATUS_CHOICES,
            "selected_status": status_filter,
            "search_query": search_query,
        },
    )


@login_required
def edit_print_request(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    if not print_request.is_open:
        return redirect("request_status", request_id=print_request.id)

    if request.method == "POST":
        form = PrintSettingsForm(request.POST)

        if form.is_valid():
            try:
                services.update_print_request(
                    print_request,
                    services.PrintOptions.from_cleaned_data(form.cleaned_data),
                    request.user,
                )
            except services.WorkflowError as error:
                messages.error(request, str(error))
                return redirect("request_status", request_id=print_request.id)

            return redirect("payment", request_id=print_request.id)
    else:
        form = PrintSettingsForm(
            initial={
                "copies": print_request.settings.copies,
                "color_mode": print_request.settings.color_mode,
                "paper_format": print_request.settings.paper_format,
                "duplex_mode": print_request.settings.duplex_mode,
            }
        )

    return render(
        request,
        "printing/edit_print_request.html",
        {"form": form, "print_request": print_request},
    )


@login_required
def cancel_print_request(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    if not print_request.is_open:
        return redirect("request_status", request_id=print_request.id)

    if request.method == "POST":
        try:
            services.cancel_print_request(print_request, request.user)
        except services.WorkflowError as error:
            messages.error(request, str(error))
            return redirect("request_status", request_id=print_request.id)

        messages.success(request, f"Print request #{print_request.id} was cancelled.")
        return redirect("request_history")

    return render(request, "printing/cancel_print_request.html", {"print_request": print_request})


# ---------------------------------------------------------------------------
# Administrator pages (web)
# ---------------------------------------------------------------------------

@chapify_admin_required
def admin_report(request):
    confirmed_payments = PaymentTransaction.objects.filter(
        payment_status=PaymentTransaction.STATUS_CONFIRMED
    )
    rejected_payments = PaymentTransaction.objects.filter(
        payment_status=PaymentTransaction.STATUS_REJECTED
    )

    return render(
        request,
        "printing/admin_report.html",
        {
            "total_requests": PrintRequest.objects.count(),
            "confirmed_payments_count": confirmed_payments.count(),
            "rejected_payments_count": rejected_payments.count(),
            "total_confirmed_amount": confirmed_payments.aggregate(total=Sum("amount"))["total"] or 0,
            "requests_by_status": (
                PrintRequest.objects.values("status").annotate(total=Count("id")).order_by("status")
            ),
            "payments_by_status": (
                PaymentTransaction.objects.values("payment_status").annotate(total=Count("id")).order_by("payment_status")
            ),
            "jobs_by_status": (
                PrintJob.objects.values("job_status").annotate(total=Count("id")).order_by("job_status")
            ),
            "recent_requests": (
                PrintRequest.objects.select_related("user", "document", "settings").order_by("-created_at")[:20]
            ),
            "recent_logs": AuditLog.objects.select_related("user").order_by("-event_timestamp")[:20],
        },
    )


@chapify_admin_required
def admin_dashboard(request):
    all_requests = (
        PrintRequest.objects
        .select_related("user", "document", "settings")
        .order_by("-created_at")
    )
    filtered_requests, status_filter, search_query = filter_print_requests(
        all_requests, request.GET, include_username=True
    )

    active_jobs = (
        PrintJob.objects
        .filter(job_status__in=[PrintJob.STATUS_QUEUED, PrintJob.STATUS_IN_PROGRESS])
        .select_related("print_request__user", "printer")
        .order_by("created_at")
    )
    failed_jobs = (
        PrintJob.objects
        .filter(job_status=PrintJob.STATUS_FAILED)
        .select_related("print_request__user", "printer")
        .order_by("-completed_at")[:10]
    )

    return render(
        request,
        "printing/admin_dashboard.html",
        {
            "total_requests": PrintRequest.objects.count(),
            "confirmed_payments": PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_CONFIRMED
            ).count(),
            "rejected_payments": PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_REJECTED
            ).count(),
            "completed_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_COMPLETED).count(),
            "failed_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_FAILED).count(),
            "queued_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).count(),
            "active_jobs": active_jobs,
            "failed_job_list": failed_jobs,
            "printers": Printer.objects.order_by("printer_name"),
            "recent_requests": filtered_requests[:10],
            "recent_logs": AuditLog.objects.select_related("user").order_by("-event_timestamp")[:10],
            "status_choices": PrintRequest.STATUS_CHOICES,
            "selected_status": status_filter,
            "search_query": search_query,
        },
    )


@chapify_admin_required
@require_POST
def admin_process_print_job(request):
    """Demo control for the simulated print server: process the next queued job."""
    job = services.process_next_print_job(
        force_failure=request.POST.get("simulate_failure") == "1",
        actor=request.user,
    )

    if job is None:
        messages.info(request, "No job could be processed: the queue is empty or no printer is available.")
    elif job.job_status == PrintJob.STATUS_COMPLETED:
        messages.success(request, f"Print job #{job.id} completed on {job.printer}.")
    else:
        messages.warning(request, f"Print job #{job.id} failed: {job.failure_reason}")

    return redirect("admin_dashboard")


USER_ACTIONS = {
    "block": ("status", Profile.STATUS_BLOCKED, "blocked"),
    "unblock": ("status", Profile.STATUS_ACTIVE, "unblocked"),
    "make_admin": ("role", Profile.ROLE_ADMIN, "is now an administrator"),
    "make_user": ("role", Profile.ROLE_USER, "is now a normal user"),
}


@chapify_admin_required
def admin_users(request):
    """User account management (FR-13)."""
    users = (
        get_user_model().objects
        .select_related("profile")
        .annotate(request_count=Count("printrequest"))
        .order_by("username")
    )
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        users = users.filter(Q(username__icontains=search_query) | Q(email__icontains=search_query))

    if status_filter:
        users = users.filter(profile__account_status=status_filter)

    return render(
        request,
        "printing/admin_users.html",
        {
            "users": users,
            "search_query": search_query,
            "selected_status": status_filter,
            "status_choices": Profile.STATUS_CHOICES,
        },
    )


@chapify_admin_required
@require_POST
def admin_user_action(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    action = USER_ACTIONS.get(request.POST.get("action"))

    if action is None:
        messages.error(request, "Unknown action.")
        return redirect("admin_users")

    kind, value, label = action

    try:
        if kind == "status":
            services.set_account_status(target, value, request.user)
        else:
            services.set_role(target, value, request.user)
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{target.username} {label}.")

    return redirect("admin_users")


@chapify_admin_required
def admin_transactions(request):
    """Payment transaction records (FR-11)."""
    transactions = (
        PaymentTransaction.objects
        .select_related("print_request__user")
        .order_by("-payment_date", "-id")
    )
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if status_filter:
        transactions = transactions.filter(payment_status=status_filter)

    if search_query:
        query_filter = (
            Q(print_request__user__username__icontains=search_query)
            | Q(gateway_reference__icontains=search_query)
        )
        if search_query.isdigit():
            query_filter |= Q(print_request_id=int(search_query))
        if services.is_uuid(search_query):
            query_filter |= Q(reference=search_query)
        transactions = transactions.filter(query_filter)

    return render(
        request,
        "printing/admin_transactions.html",
        {
            "transactions": transactions[:200],
            "confirmed_total": (
                transactions.filter(payment_status=PaymentTransaction.STATUS_CONFIRMED)
                .aggregate(total=Sum("amount"))["total"] or 0
            ),
            "search_query": search_query,
            "selected_status": status_filter,
            "status_choices": PaymentTransaction.STATUS_CHOICES,
        },
    )


@chapify_admin_required
def admin_printers(request):
    """Printer resources: add printers and change their availability."""
    if request.method == "POST":
        try:
            printer = services.add_printer(
                request.POST.get("printer_name", ""),
                request.POST.get("location", ""),
                request.user,
            )
        except services.WorkflowError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Printer {printer.printer_name} added.")
        return redirect("admin_printers")

    printers = Printer.objects.annotate(job_count=Count("printjob")).order_by("printer_name")

    return render(
        request,
        "printing/admin_printers.html",
        {
            "printers": printers,
            "manual_statuses": [
                (value, label) for value, label in Printer.STATUS_CHOICES
                if value in services.MANUAL_PRINTER_STATUSES
            ],
        },
    )


@chapify_admin_required
@require_POST
def admin_printer_status(request, printer_id):
    printer = get_object_or_404(Printer, pk=printer_id)

    try:
        services.set_printer_status(printer, request.POST.get("printer_status", ""), request.user)
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{printer.printer_name} is now {printer.get_printer_status_display()}.")

    return redirect("admin_printers")


@chapify_admin_required
@require_POST
def admin_retry_print_job(request, job_id):
    job = get_object_or_404(PrintJob, pk=job_id)

    try:
        services.retry_print_job(job, request.user)
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Print job #{job.id} is back in the queue.")

    return redirect("admin_dashboard")


# ---------------------------------------------------------------------------
# REST API - user endpoints
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_requests(request):
    print_requests = (
        PrintRequest.objects
        .filter(user=request.user)
        .select_related("document", "settings")
        .order_by("-created_at")
    )
    print_requests, _, _ = filter_print_requests(print_requests, request.GET)
    return Response(PrintRequestSerializer(print_requests, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_request_detail(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)
    return Response(PrintRequestSerializer(print_request).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_payments(request):
    user_payments = PaymentTransaction.objects.filter(
        print_request__user=request.user
    ).order_by("-payment_date")
    return Response(PaymentTransactionSerializer(user_payments, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_print_jobs(request):
    jobs = PrintJob.objects.filter(
        print_request__user=request.user
    ).select_related("printer").order_by("-created_at")
    return Response(PrintJobSerializer(jobs, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_create_print_request(request):
    serializer = CreatePrintRequestSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    document = services.store_uploaded_document(
        request.user,
        data["file"],
        page_count=serializer.page_count,
        channel="api",
    )

    try:
        print_request = services.create_print_request(
            request.user,
            document,
            services.PrintOptions.from_cleaned_data(data),
            channel="api",
        )
    except services.WorkflowError as error:
        return Response({"detail": str(error)}, status=400)

    return Response(
        {
            "message": "Print request created successfully.",
            "print_request": PrintRequestSerializer(print_request).data,
        },
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_initiate_payment(request, request_id):
    """Start a payment. Returns the gateway checkout URL for the payer.

    There is deliberately no endpoint that lets a user confirm or reject a
    payment: only a signed gateway notification can do that.
    """
    print_request = get_user_print_request_or_404(request, request_id)

    try:
        payment_attempt = services.initiate_payment(print_request, request.user)
    except services.WorkflowError as error:
        return Response({"detail": str(error), "current_status": print_request.status}, status=409)

    return Response(
        {
            "payment_reference": str(payment_attempt.reference),
            "amount": str(payment_attempt.amount),
            "currency": payment_attempt.currency,
            "payment_status": payment_attempt.payment_status,
            "checkout_url": request.build_absolute_uri(
                payments.build_checkout_url(request, payment_attempt)
            ),
        },
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_cancel_print_request(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    try:
        services.cancel_print_request(print_request, request.user)
    except services.WorkflowError as error:
        return Response({"detail": str(error)}, status=409)

    print_request.refresh_from_db()
    return Response(PrintRequestSerializer(print_request).data)


# ---------------------------------------------------------------------------
# REST API - administrator endpoints
# ---------------------------------------------------------------------------

ADMIN_API_PERMISSIONS = [IsAuthenticated, IsChapifyAdmin]


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_summary(request):
    return Response(
        {
            "total_requests": PrintRequest.objects.count(),
            "confirmed_payments": PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_CONFIRMED
            ).count(),
            "rejected_payments": PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_REJECTED
            ).count(),
            "queued_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).count(),
            "completed_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_COMPLETED).count(),
            "failed_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_FAILED).count(),
        }
    )


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_requests(request):
    print_requests = (
        PrintRequest.objects
        .select_related("document", "settings", "user")
        .order_by("-created_at")
    )
    print_requests, _, _ = filter_print_requests(print_requests, request.GET, include_username=True)
    return Response(PrintRequestSerializer(print_requests, many=True).data)


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_transactions(request):
    all_payments = PaymentTransaction.objects.all().order_by("-payment_date")
    return Response(PaymentTransactionSerializer(all_payments, many=True).data)


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_print_jobs(request):
    jobs = PrintJob.objects.select_related("printer").order_by("-created_at")
    return Response(PrintJobSerializer(jobs, many=True).data)


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_printers(request):
    printers = Printer.objects.all().order_by("printer_name")
    return Response(PrinterSerializer(printers, many=True).data)


@api_view(["GET"])
@permission_classes(ADMIN_API_PERMISSIONS)
def api_admin_audit_logs(request):
    logs = AuditLog.objects.select_related("user").order_by("-event_timestamp")[:100]
    return Response(AuditLogSerializer(logs, many=True).data)
