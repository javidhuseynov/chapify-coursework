from django.conf import settings
from django.db import models
from django.utils import timezone

class Profile(models.Model):
    ROLE_USER = "USER"
    ROLE_ADMIN = "ADMIN"

    ROLE_CHOICES = [
        (ROLE_USER, "User"),
        (ROLE_ADMIN, "Administrator"),
    ]

    STATUS_ACTIVE = "ACTIVE"
    STATUS_BLOCKED = "BLOCKED"
    STATUS_DELETED = "DELETED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_DELETED, "Deleted"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
    account_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    
    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Document(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_VALID = "VALID"
    STATUS_INVALID = "INVALID"

    VALIDATION_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_VALID, "Valid"),
        (STATUS_INVALID, "Invalid"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    file = models.FileField(upload_to="documents/")
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=20)
    file_size = models.PositiveIntegerField()
    upload_time = models.DateTimeField(default=timezone.now)
    validation_status = models.CharField(
        max_length=10,
        choices=VALIDATION_CHOICES,
        default=STATUS_PENDING
    )
    temporary_storage_path = models.CharField(max_length=500, blank=True)

    def delete_file_from_storage(self):
        if self.file and self.file.storage.exists(self.file.name):
            self.file.delete(save=False)
            self.temporary_storage_path = ""
            self.save(update_fields=["temporary_storage_path"])
            return True

        return False

    def __str__(self):
        return self.file_name


class PrintSettings(models.Model):
    COLOR_BW = "BW"
    COLOR_COLOR = "COLOR"

    COLOR_CHOICES = [
        (COLOR_BW, "Black and white"),
        (COLOR_COLOR, "Color"),
    ]

    PAPER_A4 = "A4"
    PAPER_A3 = "A3"

    PAPER_CHOICES = [
        (PAPER_A4, "A4"),
        (PAPER_A3, "A3"),
    ]

    DUPLEX_ONE_SIDED = "ONE_SIDED"
    DUPLEX_DOUBLE_SIDED = "DOUBLE_SIDED"

    DUPLEX_CHOICES = [
        (DUPLEX_ONE_SIDED, "One-sided"),
        (DUPLEX_DOUBLE_SIDED, "Double-sided"),
    ]

    copies = models.PositiveIntegerField(default=1)
    color_mode = models.CharField(max_length=10, choices=COLOR_CHOICES, default=COLOR_BW)
    paper_format = models.CharField(max_length=5, choices=PAPER_CHOICES, default=PAPER_A4)
    duplex_mode = models.CharField(max_length=20, choices=DUPLEX_CHOICES, default=DUPLEX_ONE_SIDED)

    def __str__(self):
        return f"{self.copies} copies, {self.color_mode}, {self.paper_format}, {self.duplex_mode}"


class PrintRequest(models.Model):
    STATUS_CREATED = "CREATED"
    STATUS_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    STATUS_DOCUMENT_VALIDATED = "DOCUMENT_VALIDATED"
    STATUS_PRICE_CALCULATED = "PRICE_CALCULATED"
    STATUS_AWAITING_PAYMENT = "AWAITING_PAYMENT"
    STATUS_PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    STATUS_PAYMENT_REJECTED = "PAYMENT_REJECTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_DOCUMENT_UPLOADED, "Document uploaded"),
        (STATUS_DOCUMENT_VALIDATED, "Document validated"),
        (STATUS_PRICE_CALCULATED, "Price calculated"),
        (STATUS_AWAITING_PAYMENT, "Awaiting payment"),
        (STATUS_PAYMENT_CONFIRMED, "Payment confirmed"),
        (STATUS_PAYMENT_REJECTED, "Payment rejected"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    settings = models.ForeignKey(PrintSettings, on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_CREATED)
    document_pages = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_price(self):
        base_page_price = 0.10

        color_coefficient = 2.00 if self.settings.color_mode == PrintSettings.COLOR_COLOR else 1.00
        paper_coefficient = 1.80 if self.settings.paper_format == PrintSettings.PAPER_A3 else 1.00
        duplex_coefficient = 0.90 if self.settings.duplex_mode == PrintSettings.DUPLEX_DOUBLE_SIDED else 1.00

        page_price = base_page_price * color_coefficient * paper_coefficient * duplex_coefficient
        total = self.document_pages * self.settings.copies * page_price

        self.total_price = round(total, 2)
        return self.total_price

    def __str__(self):
        return f"Request #{self.id} - {self.user.username} - {self.status}"


class PaymentTransaction(models.Model):
    STATUS_INITIATED = "INITIATED"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_INITIATED, "Initiated"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    print_request = models.OneToOneField(PrintRequest, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INITIATED)
    payment_date = models.DateTimeField(default=timezone.now)
    gateway_reference = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Payment for request #{self.print_request.id}: {self.payment_status}"


class Printer(models.Model):
    STATUS_AVAILABLE = "AVAILABLE"
    STATUS_BUSY = "BUSY"
    STATUS_OFFLINE = "OFFLINE"
    STATUS_ERROR = "ERROR"

    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_BUSY, "Busy"),
        (STATUS_OFFLINE, "Offline"),
        (STATUS_ERROR, "Error"),
    ]

    printer_name = models.CharField(max_length=100)
    location = models.CharField(max_length=150)
    printer_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)

    def __str__(self):
        return f"{self.printer_name} ({self.location})"


class PrintJob(models.Model):
    STATUS_CREATED = "CREATED"
    STATUS_QUEUED = "QUEUED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    print_request = models.OneToOneField(PrintRequest, on_delete=models.CASCADE)
    printer = models.ForeignKey(Printer, on_delete=models.SET_NULL, null=True, blank=True)
    job_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Print job for request #{self.print_request.id}: {self.job_status}"


class AuditLog(models.Model):
    EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
    EVENT_LOGIN_FAILED = "LOGIN_FAILED"
    EVENT_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    EVENT_DOCUMENT_VALIDATED = "DOCUMENT_VALIDATED"
    EVENT_DOCUMENT_DELETED = "DOCUMENT_DELETED"
    EVENT_PRINT_REQUEST_CREATED = "PRINT_REQUEST_CREATED"
    EVENT_PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    EVENT_PAYMENT_REJECTED = "PAYMENT_REJECTED"
    EVENT_PRINT_JOB_CREATED = "PRINT_JOB_CREATED"
    EVENT_PRINT_JOB_STATUS_CHANGED = "PRINT_JOB_STATUS_CHANGED"
    EVENT_USER_MANAGED = "USER_MANAGED"
    EVENT_ADMIN_ACTION = "ADMIN_ACTION"

    EVENT_CHOICES = [
        (EVENT_LOGIN_SUCCESS, "Login success"),
        (EVENT_LOGIN_FAILED, "Login failed"),
        (EVENT_DOCUMENT_UPLOADED, "Document uploaded"),
        (EVENT_DOCUMENT_VALIDATED, "Document validated"),
        (EVENT_DOCUMENT_DELETED, "Document deleted from storage"),
        (EVENT_PRINT_REQUEST_CREATED, "Print request created"),
        (EVENT_PAYMENT_CONFIRMED, "Payment confirmed"),
        (EVENT_PAYMENT_REJECTED, "Payment rejected"),
        (EVENT_PRINT_JOB_CREATED, "Print job created"),
        (EVENT_PRINT_JOB_STATUS_CHANGED, "Print job status changed"),
        (EVENT_USER_MANAGED, "User managed"),
        (EVENT_ADMIN_ACTION, "Admin action"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    print_request = models.ForeignKey(
        PrintRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES)
    event_timestamp = models.DateTimeField(default=timezone.now)
    description = models.TextField()

    def __str__(self):
        return f"{self.event_type} at {self.event_timestamp}"