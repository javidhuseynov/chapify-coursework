import os

from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .serializers import (
    AuditLogSerializer,
    CreatePrintRequestSerializer,
    PaymentTransactionSerializer,
    PrintJobSerializer,
    PrintRequestSerializer,
    PrinterSerializer,
)

from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

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

def get_user_print_request_or_404(request, request_id):
    return get_object_or_404(
        PrintRequest,
        id=request_id,
        user=request.user,
    )


def get_user_document_or_404(request, document_id):
    return get_object_or_404(
        Document,
        id=document_id,
        user=request.user,
    )

def is_chapify_admin(user):
    return (
        user.is_authenticated
        and hasattr(user, "profile")
        and user.profile.role == Profile.ROLE_ADMIN
    )


def admin_required_response():
    return Response(
        {"detail": "Administrator privileges are required."},
        status=403,
    )

def home(request):
    return render(request, "printing/home.html")

def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            AuditLog.objects.create(
                user=user,
                event_type=AuditLog.EVENT_LOGIN_SUCCESS,
                description=f"New user registered and logged in: {user.username}",
            )

            return redirect("home")
    else:
        form = RegisterForm()

    return render(request, "printing/register.html", {"form": form})


class ChapifyLoginView(LoginView):
    template_name = "printing/login.html"


class ChapifyLogoutView(LogoutView):
    pass

@login_required
def upload_document(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            extension = os.path.splitext(uploaded_file.name)[1].lower().replace(".", "")

            document = Document.objects.create(
                user=request.user,
                file=uploaded_file,
                file_name=uploaded_file.name,
                file_type=extension,
                file_size=uploaded_file.size,
                validation_status=Document.STATUS_VALID,
                temporary_storage_path=f"documents/{uploaded_file.name}",
            )

            AuditLog.objects.create(
                user=request.user,
                event_type=AuditLog.EVENT_DOCUMENT_UPLOADED,
                description=f"User uploaded document: {document.file_name}",
            )

            AuditLog.objects.create(
                user=request.user,
                event_type=AuditLog.EVENT_DOCUMENT_VALIDATED,
                description=f"Document validated successfully: {document.file_name}",
            )

            return redirect("print_settings", document_id=document.id)
    else:
        form = DocumentUploadForm()

    return render(request, "printing/upload_document.html", {"form": form})


@login_required
def print_settings(request, document_id):
    document = get_user_document_or_404(request, document_id)

    if request.method == "POST":
        form = PrintSettingsForm(request.POST)

        if form.is_valid():
            settings = form.save()
            document_pages = form.cleaned_data["document_pages"]

            print_request = PrintRequest.objects.create(
                user=request.user,
                document=document,
                settings=settings,
                document_pages=document_pages,
                status=PrintRequest.STATUS_PRICE_CALCULATED,
            )

            print_request.calculate_price()
            print_request.status = PrintRequest.STATUS_AWAITING_PAYMENT
            print_request.save()
            AuditLog.objects.create(
                user=request.user,
                print_request=print_request,
                event_type=AuditLog.EVENT_PRINT_REQUEST_CREATED,
                description=(
                    f"Print request #{print_request.id} created. "
                    f"Pages: {print_request.document_pages}, "
                    f"copies: {settings.copies}, "
                    f"total price: {print_request.total_price:.2f} EUR."
                ),
            )

            return redirect("payment", request_id=print_request.id)
    else:
        form = PrintSettingsForm()

    return render(
        request,
        "printing/print_settings.html",
        {
            "form": form,
            "document": document,
        },
    )


@login_required
def payment(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)
    existing_payment = PaymentTransaction.objects.filter(print_request=print_request).first()

    if existing_payment:
        return redirect("request_status", request_id=print_request.id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "confirm":
            payment_transaction = PaymentTransaction.objects.create(
                print_request=print_request,
                amount=print_request.total_price,
                payment_status=PaymentTransaction.STATUS_CONFIRMED,
                gateway_reference=f"SIM-{print_request.id:05d}",
            )

            print_request.status = PrintRequest.STATUS_PAYMENT_CONFIRMED
            print_request.save()

            printer = Printer.objects.filter(printer_status=Printer.STATUS_AVAILABLE).first()

            if printer is None:
                printer = Printer.objects.create(
                    printer_name="Default Printer",
                    location="Library / Study Center",
                    printer_status=Printer.STATUS_AVAILABLE,
                )

            print_job = PrintJob.objects.create(
                print_request=print_request,
                printer=printer,
                job_status=PrintJob.STATUS_COMPLETED,
                completed_at=timezone.now(),
            )

            AuditLog.objects.create(
                user=request.user,
                print_request=print_request,
                event_type=AuditLog.EVENT_PAYMENT_CONFIRMED,
                description=f"Payment confirmed. Transaction reference: {payment_transaction.gateway_reference}",
            )

            AuditLog.objects.create(
                user=request.user,
                print_request=print_request,
                event_type=AuditLog.EVENT_PRINT_JOB_CREATED,
                description=f"Print job created for request #{print_request.id}.",
            )

            file_deleted = print_request.document.delete_file_from_storage()

            if file_deleted:
                AuditLog.objects.create(
                    user=request.user,
                    print_request=print_request,
                    event_type=AuditLog.EVENT_DOCUMENT_DELETED,
                    description=(
                        f"Uploaded document file for request #{print_request.id} "
                        f"was deleted from storage after print job completion."
                    ),
                )

            return redirect("request_status", request_id=print_request.id)

        if action == "reject":
            PaymentTransaction.objects.create(
                print_request=print_request,
                amount=print_request.total_price,
                payment_status=PaymentTransaction.STATUS_REJECTED,
                gateway_reference=f"SIM-REJECT-{print_request.id:05d}",
            )

            print_request.status = PrintRequest.STATUS_PAYMENT_REJECTED
            print_request.save()

            AuditLog.objects.create(
                user=request.user,
                print_request=print_request,
                event_type=AuditLog.EVENT_PAYMENT_REJECTED,
                description=f"Payment rejected for request #{print_request.id}.",
            )

            file_deleted = print_request.document.delete_file_from_storage()

            if file_deleted:
                AuditLog.objects.create(
                    user=request.user,
                    print_request=print_request,
                    event_type=AuditLog.EVENT_DOCUMENT_DELETED,
                    description=(
                        f"Uploaded document file for request #{print_request.id} "
                        f"was deleted from storage after payment rejection."
                    ),
                )

            return redirect("request_status", request_id=print_request.id)

    return render(
        request,
        "printing/payment.html",
        {
            "print_request": print_request,
        },
    )

@login_required
def request_status(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)
    payment_transaction = PaymentTransaction.objects.filter(print_request=print_request).first()
    print_job = PrintJob.objects.filter(print_request=print_request).first()

    return render(
        request,
        "printing/request_status.html",
        {
            "print_request": print_request,
            "payment_transaction": payment_transaction,
            "print_job": print_job,
        },
    )

@login_required
def request_history(request):
    print_requests = (
        PrintRequest.objects
        .filter(user=request.user)
        .order_by("-created_at")
    )

    return render(
        request,
        "printing/request_history.html",
        {
            "print_requests": print_requests,
        },
    )

@staff_member_required
def admin_dashboard(request):
    total_requests = PrintRequest.objects.count()
    confirmed_payments = PaymentTransaction.objects.filter(
        payment_status=PaymentTransaction.STATUS_CONFIRMED
    ).count()
    rejected_payments = PaymentTransaction.objects.filter(
        payment_status=PaymentTransaction.STATUS_REJECTED
    ).count()
    completed_jobs = PrintJob.objects.filter(
        job_status=PrintJob.STATUS_COMPLETED
    ).count()
    failed_jobs = PrintJob.objects.filter(
        job_status=PrintJob.STATUS_FAILED
    ).count()

    recent_requests = PrintRequest.objects.order_by("-created_at")[:5]
    recent_logs = AuditLog.objects.order_by("-event_timestamp")[:5]

    return render(
        request,
        "printing/admin_dashboard.html",
        {
            "total_requests": total_requests,
            "confirmed_payments": confirmed_payments,
            "rejected_payments": rejected_payments,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "recent_requests": recent_requests,
            "recent_logs": recent_logs,
        },
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_requests(request):
    print_requests = PrintRequest.objects.filter(user=request.user).order_by("-created_at")
    serializer = PrintRequestSerializer(print_requests, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_request_detail(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)
    serializer = PrintRequestSerializer(print_request)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_payments(request):
    payments = PaymentTransaction.objects.filter(
        print_request__user=request.user
    ).order_by("-payment_date")

    serializer = PaymentTransactionSerializer(payments, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_print_jobs(request):
    jobs = PrintJob.objects.filter(
        print_request__user=request.user
    ).order_by("-created_at")

    serializer = PrintJobSerializer(jobs, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_summary(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    data = {
        "total_requests": PrintRequest.objects.count(),
        "confirmed_payments": PaymentTransaction.objects.filter(
            payment_status=PaymentTransaction.STATUS_CONFIRMED
        ).count(),
        "rejected_payments": PaymentTransaction.objects.filter(
            payment_status=PaymentTransaction.STATUS_REJECTED
        ).count(),
        "completed_jobs": PrintJob.objects.filter(
            job_status=PrintJob.STATUS_COMPLETED
        ).count(),
        "failed_jobs": PrintJob.objects.filter(
            job_status=PrintJob.STATUS_FAILED
        ).count(),
    }

    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_requests(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    print_requests = PrintRequest.objects.all().order_by("-created_at")
    serializer = PrintRequestSerializer(print_requests, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_transactions(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    payments = PaymentTransaction.objects.all().order_by("-payment_date")
    serializer = PaymentTransactionSerializer(payments, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_print_jobs(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    jobs = PrintJob.objects.all().order_by("-created_at")
    serializer = PrintJobSerializer(jobs, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_printers(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    printers = Printer.objects.all().order_by("printer_name")
    serializer = PrinterSerializer(printers, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_admin_audit_logs(request):
    if not is_chapify_admin(request.user):
        return admin_required_response()

    logs = AuditLog.objects.all().order_by("-event_timestamp")[:100]
    serializer = AuditLogSerializer(logs, many=True)
    return Response(serializer.data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_create_print_request(request):
    serializer = CreatePrintRequestSerializer(data=request.data)

    if serializer.is_valid():
        uploaded_file = serializer.validated_data["file"]
        extension = os.path.splitext(uploaded_file.name)[1].lower().replace(".", "")

        document = Document.objects.create(
            user=request.user,
            file=uploaded_file,
            file_name=uploaded_file.name,
            file_type=extension,
            file_size=uploaded_file.size,
            validation_status=Document.STATUS_VALID,
            temporary_storage_path=f"documents/{uploaded_file.name}",
        )

        settings = PrintSettings.objects.create(
            copies=serializer.validated_data["copies"],
            color_mode=serializer.validated_data["color_mode"],
            paper_format=serializer.validated_data["paper_format"],
            duplex_mode=serializer.validated_data["duplex_mode"],
        )

        print_request = PrintRequest.objects.create(
            user=request.user,
            document=document,
            settings=settings,
            document_pages=serializer.validated_data["document_pages"],
            status=PrintRequest.STATUS_PRICE_CALCULATED,
        )

        print_request.calculate_price()
        print_request.status = PrintRequest.STATUS_AWAITING_PAYMENT
        print_request.save()
        AuditLog.objects.create(
            user=request.user,
            print_request=print_request,
            event_type=AuditLog.EVENT_PRINT_REQUEST_CREATED,
            description=(
                f"API print request #{print_request.id} created. "
                f"Pages: {print_request.document_pages}, "
                f"copies: {settings.copies}, "
                f"total price: {float(print_request.total_price):.2f} EUR."
            ),
        )

        AuditLog.objects.create(
            user=request.user,
            print_request=print_request,
            event_type=AuditLog.EVENT_DOCUMENT_UPLOADED,
            description=f"API document uploaded: {document.file_name}",
        )

        AuditLog.objects.create(
            user=request.user,
            print_request=print_request,
            event_type=AuditLog.EVENT_DOCUMENT_VALIDATED,
            description=f"API document validated successfully: {document.file_name}",
        )

        response_serializer = PrintRequestSerializer(print_request)

        return Response(
            {
                "message": "Print request created successfully.",
                "print_request": response_serializer.data,
            },
            status=201,
        )

    return Response(serializer.errors, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_confirm_payment(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    existing_payment = PaymentTransaction.objects.filter(print_request=print_request).first()

    if existing_payment:
        return Response(
            {
                "message": "Payment was already processed for this request.",
                "payment_status": existing_payment.payment_status,
            },
            status=400,
        )

    payment_transaction = PaymentTransaction.objects.create(
        print_request=print_request,
        amount=print_request.total_price,
        payment_status=PaymentTransaction.STATUS_CONFIRMED,
        gateway_reference=f"API-SIM-{print_request.id:05d}",
    )

    print_request.status = PrintRequest.STATUS_PAYMENT_CONFIRMED
    print_request.save()

    printer = Printer.objects.filter(printer_status=Printer.STATUS_AVAILABLE).first()

    if printer is None:
        printer = Printer.objects.create(
            printer_name="Default Printer",
            location="Library / Study Center",
            printer_status=Printer.STATUS_AVAILABLE,
        )

    print_job = PrintJob.objects.create(
        print_request=print_request,
        printer=printer,
        job_status=PrintJob.STATUS_COMPLETED,
        completed_at=timezone.now(),
    )

    AuditLog.objects.create(
        user=request.user,
        print_request=print_request,
        event_type=AuditLog.EVENT_PAYMENT_CONFIRMED,
        description=f"API payment confirmed. Transaction reference: {payment_transaction.gateway_reference}",
    )

    AuditLog.objects.create(
        user=request.user,
        print_request=print_request,
        event_type=AuditLog.EVENT_PRINT_JOB_CREATED,
        description=f"API print job created for request #{print_request.id}.",
    )

    file_deleted = print_request.document.delete_file_from_storage()

    if file_deleted:
        AuditLog.objects.create(
            user=request.user,
            print_request=print_request,
            event_type=AuditLog.EVENT_DOCUMENT_DELETED,
            description=(
                f"API uploaded document file for request #{print_request.id} "
                f"was deleted from storage after print job completion."
            ),
        )

    return Response(
        {
            "message": "Payment confirmed and print job created.",
            "payment_id": payment_transaction.id,
            "payment_status": payment_transaction.payment_status,
            "print_job_id": print_job.id,
            "print_job_status": print_job.job_status,
            "document_file_deleted": file_deleted,
        },
        status=201,
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_reject_payment(request, request_id):
    print_request = get_user_print_request_or_404(request, request_id)

    existing_payment = PaymentTransaction.objects.filter(print_request=print_request).first()

    if existing_payment:
        return Response(
            {
                "message": "Payment was already processed for this request.",
                "payment_status": existing_payment.payment_status,
            },
            status=400,
        )

    payment_transaction = PaymentTransaction.objects.create(
        print_request=print_request,
        amount=print_request.total_price,
        payment_status=PaymentTransaction.STATUS_REJECTED,
        gateway_reference=f"API-SIM-REJECT-{print_request.id:05d}",
    )

    print_request.status = PrintRequest.STATUS_PAYMENT_REJECTED
    print_request.save()

    AuditLog.objects.create(
        user=request.user,
        print_request=print_request,
        event_type=AuditLog.EVENT_PAYMENT_REJECTED,
        description=f"API payment rejected for request #{print_request.id}.",
    )

    file_deleted = print_request.document.delete_file_from_storage()

    if file_deleted:
        AuditLog.objects.create(
            user=request.user,
            print_request=print_request,
            event_type=AuditLog.EVENT_DOCUMENT_DELETED,
            description=(
                f"API uploaded document file for request #{print_request.id} "
                f"was deleted from storage after payment rejection."
            ),
        )

    return Response(
        {
            "message": "Payment rejected.",
            "payment_id": payment_transaction.id,
            "payment_status": payment_transaction.payment_status,
            "document_file_deleted": file_deleted,
        },
        status=201,
    )