import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import payments, pricing, services
from .forms import DocumentUploadForm, PrintSettingsForm, RegisterForm
from .models import (
    AuditLog,
    Document,
    PaymentTransaction,
    Printer,
    PrintJob,
    PrintRequest,
    PrintSettings,
    Profile,
)
from . import rate_limits
from .login_protection import ThrottledAuthenticationForm, client_ip
from .permissions import IsChapifyAdmin, chapify_admin_required, is_chapify_admin
from .validators import MAX_DOCUMENT_PAGES, MAX_DOCUMENT_SIZE
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

# Statuses a request can actually have (the remaining codes are design-time states).
USER_STATUS_CHOICES = [
    (value, label) for value, label in PrintRequest.STATUS_CHOICES
    if value in (
        PrintRequest.STATUS_AWAITING_PAYMENT,
        PrintRequest.STATUS_PAYMENT_REJECTED,
        PrintRequest.STATUS_PAYMENT_CONFIRMED,
        PrintRequest.STATUS_COMPLETED,
        PrintRequest.STATUS_FAILED,
        PrintRequest.STATUS_CANCELLED,
    )
]


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
    """Front door: visitors see the login page; after login the role decides."""
    if not request.user.is_authenticated:
        return redirect("login")

    if is_chapify_admin(request.user):
        return redirect("admin_dashboard")

    own_requests = PrintRequest.objects.filter(user=request.user).select_related("document", "settings")
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    completed_this_month = own_requests.filter(
        status=PrintRequest.STATUS_COMPLETED,
        updated_at__gte=month_start,
    )

    return render(
        request,
        "printing/home.html",
        {
            "active_requests": own_requests.filter(
                status__in=[
                    PrintRequest.STATUS_AWAITING_PAYMENT,
                    PrintRequest.STATUS_PAYMENT_REJECTED,
                    PrintRequest.STATUS_PAYMENT_CONFIRMED,
                    PrintRequest.STATUS_FAILED,
                ]
            ).order_by("-updated_at"),
            "recent_requests": own_requests.filter(
                status__in=[PrintRequest.STATUS_COMPLETED, PrintRequest.STATUS_CANCELLED]
            ).order_by("-updated_at")[:5],
            "pages_this_month": sum(
                item.document_pages * item.settings.copies for item in completed_this_month
            ),
            "spent_this_month": money(PaymentTransaction.objects.filter(
                print_request__user=request.user,
                payment_status=PaymentTransaction.STATUS_CONFIRMED,
                payment_date__gte=month_start,
            ).aggregate(total=Sum("amount"))["total"]),
            "total_requests": own_requests.count(),
        },
    )


def money(value):
    """Sums of DecimalFields come back without cents on SQLite (Decimal('4')); show 4.00."""
    return (value or Decimal("0")).quantize(Decimal("0.01"))


def paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def pricing_context(pages, form=None):
    """Coefficients for the live price estimate on the settings pages."""
    data = {
        "pages": pages,
        "base": float(pricing.BASE_PAGE_PRICE),
        "color": {key: float(value) for key, value in pricing.COLOR_COEFFICIENTS.items()},
        "paper": {key: float(value) for key, value in pricing.PAPER_COEFFICIENTS.items()},
        "duplex": {key: float(value) for key, value in pricing.DUPLEX_COEFFICIENTS.items()},
    }
    estimate = None
    values = form.initial if form is not None and not form.is_bound else {}
    try:
        estimate = pricing.calculate_total_price(
            pages,
            int(values.get("copies", 1)),
            values.get("color_mode", "BW"),
            values.get("paper_format", "A4"),
            values.get("duplex_mode", "ONE_SIDED"),
        )
    except (ValueError, TypeError):
        estimate = None
    return {"pricing_data": data, "estimate": estimate}


def format_page_price(value):
    """0.090 -> 0.09, 0.162 -> 0.162 (page prices can have three decimals)."""
    text = f"{value:.3f}"
    return text[:-1] if text.endswith("0") else text


@login_required
def help_page(request):
    prices = []
    for paper, paper_label in PrintSettings.PAPER_CHOICES:
        prices.append(
            {
                "paper": paper_label,
                "prices": [
                    format_page_price(pricing.calculate_page_price(color, paper, duplex))
                    for color, duplex in (
                        ("BW", "ONE_SIDED"),
                        ("BW", "DOUBLE_SIDED"),
                        ("COLOR", "ONE_SIDED"),
                        ("COLOR", "DOUBLE_SIDED"),
                    )
                ],
            }
        )

    return render(
        request,
        "printing/help.html",
        {
            "price_rows": prices,
            "example_price": pricing.calculate_total_price(10, 2, "COLOR", "A4", "ONE_SIDED"),
            "max_size_mb": MAX_DOCUMENT_SIZE // (1024 * 1024),
            "max_pages": MAX_DOCUMENT_PAGES,
            "retention_hours": settings.DOCUMENT_RETENTION_HOURS,
            "login_limit": settings.LOGIN_FAILURE_LIMIT,
            "lockout_minutes": settings.LOGIN_LOCKOUT_SECONDS // 60,
        },
    )


@login_required
def account(request):
    if request.method == "POST":
        password_form = PasswordChangeForm(request.user, request.POST)

        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)  # stay logged in on this device
            services.audit(
                AuditLog.EVENT_USER_MANAGED,
                f"User {user.username} changed their password.",
                user=user,
            )
            messages.success(request, "Your password has been changed.")
            return redirect("account")
    else:
        password_form = PasswordChangeForm(request.user)

    return render(request, "printing/account.html", {"password_form": password_form})


def register(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        ip = client_ip(request)

        if not rate_limits.hit(
            "register",
            ip,
            settings.REGISTRATION_LIMIT_PER_IP,
            settings.REGISTRATION_LIMIT_WINDOW_SECONDS,
        ):
            services.audit(
                AuditLog.EVENT_REGISTRATION_REFUSED,
                f"Registration refused: too many attempts from {ip}.",
            )
            messages.error(request, "Too many registration attempts from your network. Please try again later.")
            return render(request, "printing/register.html", {"form": RegisterForm()}, status=429)

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

        if form.bot_suspected:
            services.audit(
                AuditLog.EVENT_REGISTRATION_REFUSED,
                f"Registration refused by bot protection (honeypot or fill time) from {ip}.",
            )
    else:
        form = RegisterForm()

    return render(request, "printing/register.html", {"form": form})


class ChapifyLoginView(LoginView):
    template_name = "printing/login.html"
    form_class = ThrottledAuthenticationForm  # locks out after repeated failures
    redirect_authenticated_user = True


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

    return render(
        request,
        "printing/print_settings.html",
        {"form": form, "document": document, **pricing_context(document.page_count, form)},
    )


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
    payment_attempts = list(print_request.payments.order_by("payment_date", "id"))
    print_job = PrintJob.objects.filter(print_request=print_request).select_related("printer").first()

    return render(
        request,
        "printing/request_status.html",
        {
            "print_request": print_request,
            "payment_transaction": payment_attempts[-1] if payment_attempts else None,
            "payment_attempts": payment_attempts,
            "print_job": print_job,
            "timeline": build_timeline(print_request, payment_attempts, print_job),
            "status_explanation": STATUS_EXPLANATIONS.get(print_request.status, ""),
        },
    )


STATUS_EXPLANATIONS = {
    PrintRequest.STATUS_AWAITING_PAYMENT: "Waiting for your payment. Printing starts as soon as it is confirmed.",
    PrintRequest.STATUS_PAYMENT_REJECTED: "The payment was declined. You can try again or change the settings.",
    PrintRequest.STATUS_PAYMENT_CONFIRMED: "Paid. Your document is in the print queue.",
    PrintRequest.STATUS_COMPLETED: "Printed. Collect your pages from the printer shown below.",
    PrintRequest.STATUS_FAILED: "The printer had a problem. Staff can send your job to the printer again.",
    PrintRequest.STATUS_CANCELLED: "This request was cancelled and the file has been deleted.",
}


def build_timeline(print_request, payment_attempts, print_job):
    """User-facing history of one request, built from its records (oldest first)."""
    events = [{"what": "Request created", "when": print_request.created_at, "state": "done"}]

    for attempt in payment_attempts:
        label = {
            PaymentTransaction.STATUS_INITIATED: "Payment started",
            PaymentTransaction.STATUS_CONFIRMED: "Payment confirmed",
            PaymentTransaction.STATUS_REJECTED: "Payment declined",
            PaymentTransaction.STATUS_CANCELLED: "Payment not completed",
        }[attempt.payment_status]
        state = "failed" if attempt.payment_status == PaymentTransaction.STATUS_REJECTED else "done"
        events.append({"what": f"{label} ({attempt.amount} {attempt.currency})", "when": attempt.payment_date, "state": state})

    if print_job:
        events.append({"what": "Added to the print queue", "when": print_job.created_at, "state": "done"})
        if print_job.started_at:
            events.append({"what": "Printing started", "when": print_job.started_at, "state": "done"})
        if print_job.job_status == PrintJob.STATUS_COMPLETED:
            events.append({"what": "Printed", "when": print_job.completed_at, "state": "done"})
        elif print_job.job_status == PrintJob.STATUS_FAILED:
            events.append({
                "what": "Printing failed",
                "when": print_job.completed_at,
                "state": "failed",
                "detail": print_job.failure_reason,
            })

    if print_request.status == PrintRequest.STATUS_CANCELLED:
        events.append({"what": "Request cancelled", "when": print_request.updated_at, "state": "done"})

    next_step = {
        PrintRequest.STATUS_AWAITING_PAYMENT: "Waiting for payment",
        PrintRequest.STATUS_PAYMENT_REJECTED: "Waiting for a new payment",
        PrintRequest.STATUS_PAYMENT_CONFIRMED: "Printing" if print_job and print_job.started_at else "Waiting for a printer",
    }.get(print_request.status)
    if next_step:
        events.append({"what": next_step, "when": None, "state": "current"})

    return events


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
            "page_obj": paginate(request, print_requests, per_page=15),
            "status_choices": USER_STATUS_CHOICES,
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
        {
            "form": form,
            "print_request": print_request,
            **pricing_context(print_request.document_pages, form),
        },
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
    completed = PrintRequest.objects.filter(status=PrintRequest.STATUS_COMPLETED).select_related("settings")

    def breakdown(queryset, field):
        return [
            {"code": row[field], "total": row["total"]}
            for row in queryset.values(field).annotate(total=Count("id")).order_by("-total")
        ]

    return render(
        request,
        "printing/admin_report.html",
        {
            "total_requests": PrintRequest.objects.count(),
            "confirmed_payments_count": confirmed_payments.count(),
            "rejected_payments_count": PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_REJECTED
            ).count(),
            "total_confirmed_amount": money(confirmed_payments.aggregate(total=Sum("amount"))["total"]),
            "printed_pages": sum(item.document_pages * item.settings.copies for item in completed),
            "breakdowns": [
                {"title": "Requests", "rows": breakdown(PrintRequest.objects, "status")},
                {"title": "Payments", "rows": breakdown(PaymentTransaction.objects, "payment_status")},
                {"title": "Print jobs", "rows": breakdown(PrintJob.objects, "job_status")},
                {"title": "Printers", "rows": breakdown(Printer.objects, "printer_status")},
            ],
        },
    )


@chapify_admin_required
def admin_dashboard(request):
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    return render(
        request,
        "printing/admin_dashboard.html",
        {
            "queued_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).count(),
            "completed_today": PrintJob.objects.filter(
                job_status=PrintJob.STATUS_COMPLETED, completed_at__gte=today_start
            ).count(),
            "failed_jobs": PrintJob.objects.filter(job_status=PrintJob.STATUS_FAILED).count(),
            "revenue_today": money(PaymentTransaction.objects.filter(
                payment_status=PaymentTransaction.STATUS_CONFIRMED, payment_date__gte=today_start
            ).aggregate(total=Sum("amount"))["total"]),
            "open_requests": PrintRequest.objects.filter(status__in=PrintRequest.OPEN_STATUSES).count(),
            "active_jobs": (
                PrintJob.objects
                .filter(job_status__in=[PrintJob.STATUS_QUEUED, PrintJob.STATUS_IN_PROGRESS])
                .select_related("print_request__user", "print_request__settings", "printer")
                .order_by("created_at")
            ),
            "failed_job_list": (
                PrintJob.objects
                .filter(job_status=PrintJob.STATUS_FAILED)
                .select_related("print_request__user", "printer")
                .order_by("-completed_at")[:10]
            ),
            "printers": Printer.objects.order_by("printer_name"),
            "recent_logs": AuditLog.objects.select_related("user").order_by("-event_timestamp")[:8],
        },
    )


@chapify_admin_required
def admin_requests(request):
    all_requests = (
        PrintRequest.objects
        .select_related("user", "document", "settings")
        .order_by("-created_at")
    )
    filtered, status_filter, search_query = filter_print_requests(all_requests, request.GET, include_username=True)

    return render(
        request,
        "printing/admin_requests.html",
        {
            "page_obj": paginate(request, filtered),
            "status_choices": USER_STATUS_CHOICES,
            "selected_status": status_filter,
            "search_query": search_query,
        },
    )


@chapify_admin_required
def admin_audit(request):
    logs = AuditLog.objects.select_related("user").order_by("-event_timestamp", "-id")
    search_query = request.GET.get("q", "").strip()
    event_filter = request.GET.get("status", "").strip()

    if event_filter:
        logs = logs.filter(event_type=event_filter)

    if search_query:
        logs = logs.filter(Q(description__icontains=search_query) | Q(user__username__icontains=search_query))

    return render(
        request,
        "printing/admin_audit.html",
        {
            "page_obj": paginate(request, logs, per_page=50),
            "status_choices": AuditLog.EVENT_CHOICES,
            "selected_status": event_filter,
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
            "page_obj": paginate(request, users, per_page=25),
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
            "page_obj": paginate(request, transactions, per_page=25),
            "confirmed_total": money(
                transactions.filter(payment_status=PaymentTransaction.STATUS_CONFIRMED)
                .aggregate(total=Sum("amount"))["total"]
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
