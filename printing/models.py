import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .pricing import calculate_total_price

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

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN
    
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
    # Counted from the PDF at upload time; empty for documents uploaded before
    # page counting existed (those cannot be used for new requests).
    page_count = models.PositiveIntegerField(null=True, blank=True)
    upload_time = models.DateTimeField(default=timezone.now)
    validation_status = models.CharField(
        max_length=10,
        choices=VALIDATION_CHOICES,
        default=STATUS_PENDING
    )
    temporary_storage_path = models.CharField(max_length=500, blank=True)

    def has_file(self):
        return bool(self.file) and self.file.storage.exists(self.file.name)

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

    # Requests in these states can still be edited, paid or cancelled.
    OPEN_STATUSES = (STATUS_AWAITING_PAYMENT, STATUS_PAYMENT_REJECTED)
    # Final states: the uploaded file is deleted when one of them is reached.
    TERMINAL_STATUSES = (STATUS_CANCELLED, STATUS_COMPLETED, STATUS_FAILED)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    def calculate_price(self):
        self.total_price = calculate_total_price(
            document_pages=self.document_pages,
            copies=self.settings.copies,
            color_mode=self.settings.color_mode,
            paper_format=self.settings.paper_format,
            duplex_mode=self.settings.duplex_mode,
        )
        return self.total_price

    def latest_payment(self):
        return self.payments.order_by("-payment_date", "-id").first()

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

    # A request may have several payment attempts (e.g. a declined card followed
    # by a successful retry), but at most one CONFIRMED payment (constraint below).
    print_request = models.ForeignKey(
        PrintRequest,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    # Chapify's own identifier of this attempt, sent to the gateway.
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INITIATED)
    payment_date = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # Transaction identifier returned by the gateway (never card data).
    gateway_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["print_request"],
                condition=models.Q(payment_status="CONFIRMED"),
                name="unique_confirmed_payment_per_request",
            ),
        ]

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
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"Print job for request #{self.print_request.id}: {self.job_status}"


class AuditLog(models.Model):
    EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
    EVENT_LOGIN_FAILED = "LOGIN_FAILED"
    EVENT_LOGOUT = "LOGOUT"
    EVENT_ACCOUNT_REGISTERED = "ACCOUNT_REGISTERED"
    EVENT_REGISTRATION_REFUSED = "REGISTRATION_REFUSED"
    EVENT_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    EVENT_DOCUMENT_VALIDATED = "DOCUMENT_VALIDATED"
    EVENT_DOCUMENT_DELETED = "DOCUMENT_DELETED"
    EVENT_PRINT_REQUEST_CREATED = "PRINT_REQUEST_CREATED"
    EVENT_PRINT_REQUEST_UPDATED = "PRINT_REQUEST_UPDATED"
    EVENT_PRINT_REQUEST_CANCELLED = "PRINT_REQUEST_CANCELLED"
    EVENT_PAYMENT_INITIATED = "PAYMENT_INITIATED"
    EVENT_PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    EVENT_PAYMENT_REJECTED = "PAYMENT_REJECTED"
    EVENT_PAYMENT_NOTIFICATION_REFUSED = "PAYMENT_NOTIFICATION_REFUSED"
    EVENT_PRINT_JOB_CREATED = "PRINT_JOB_CREATED"
    EVENT_PRINT_JOB_STATUS_CHANGED = "PRINT_JOB_STATUS_CHANGED"
    EVENT_USER_MANAGED = "USER_MANAGED"
    EVENT_ADMIN_ACTION = "ADMIN_ACTION"
    EVENT_API_TOKEN_CREATED = "API_TOKEN_CREATED"
    EVENT_API_TOKEN_REVOKED = "API_TOKEN_REVOKED"

    EVENT_CHOICES = [
        (EVENT_LOGIN_SUCCESS, "Login success"),
        (EVENT_LOGIN_FAILED, "Login failed"),
        (EVENT_LOGOUT, "Logout"),
        (EVENT_ACCOUNT_REGISTERED, "Account registered"),
        (EVENT_REGISTRATION_REFUSED, "Registration refused (bot protection)"),
        (EVENT_DOCUMENT_UPLOADED, "Document uploaded"),
        (EVENT_DOCUMENT_VALIDATED, "Document validated"),
        (EVENT_DOCUMENT_DELETED, "Document deleted from storage"),
        (EVENT_PRINT_REQUEST_CREATED, "Print request created"),
        (EVENT_PRINT_REQUEST_UPDATED, "Print request updated"),
        (EVENT_PRINT_REQUEST_CANCELLED, "Print request cancelled"),
        (EVENT_PAYMENT_INITIATED, "Payment initiated"),
        (EVENT_PAYMENT_CONFIRMED, "Payment confirmed"),
        (EVENT_PAYMENT_REJECTED, "Payment rejected"),
        (EVENT_PAYMENT_NOTIFICATION_REFUSED, "Payment notification refused"),
        (EVENT_PRINT_JOB_CREATED, "Print job created"),
        (EVENT_PRINT_JOB_STATUS_CHANGED, "Print job status changed"),
        (EVENT_USER_MANAGED, "User managed"),
        (EVENT_ADMIN_ACTION, "Admin action"),
        (EVENT_API_TOKEN_CREATED, "API token created"),
        (EVENT_API_TOKEN_REVOKED, "API token revoked"),
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

class ApiToken(models.Model):
    """A credential for an API client such as the mobile app.

    Unlike Django REST Framework's built-in token, an ApiToken
    - expires (settings.API_TOKEN_TTL_HOURS),
    - can be revoked by the user (log out a device) or by the system
      (password change, blocked account),
    - is never stored in readable form: only its SHA-256 hash is kept, so a
      copy of the database does not reveal usable tokens.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    # Client-chosen label, e.g. "Chapify mobile" or "curl".
    name = models.CharField(max_length=100)
    # First characters of the token, shown so the user can recognise it.
    key_prefix = models.CharField(max_length=12)
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...) for {self.user}"
