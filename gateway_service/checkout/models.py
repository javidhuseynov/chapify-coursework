"""Gateway data: checkout sessions, card payments and webhook events.

Card data is never stored: a payment keeps only the card brand and the last
four digits, as real gateways show them to merchants.
"""

import json
import secrets

from django.db import models
from django.utils import timezone


def new_id(prefix):
    return f"{prefix}_test_{secrets.token_urlsafe(18)}"


class CheckoutSession(models.Model):
    STATUS_OPEN = "open"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_COMPLETE, "Complete (paid)"),
        (STATUS_FAILED, "Failed (declined)"),
        (STATUS_CANCELED, "Canceled by the payer"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.CharField(primary_key=True, max_length=40, editable=False)
    merchant = models.CharField(max_length=30)
    merchant_reference = models.CharField(max_length=100, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    description = models.CharField(max_length=200, blank=True)
    success_url = models.URLField(max_length=500)
    cancel_url = models.URLField(max_length=500)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = new_id("cs")
        super().save(*args, **kwargs)

    @property
    def payment_status(self):
        return {"complete": "paid", "failed": "declined"}.get(self.status, "unpaid")

    def latest_payment(self):
        return self.payments.order_by("-created_at").first()

    def __str__(self):
        return f"{self.id} {self.amount} {self.currency} ({self.status})"


class Payment(models.Model):
    OUTCOME_SUCCEEDED = "succeeded"
    OUTCOME_DECLINED = "declined"
    OUTCOME_CHOICES = [(OUTCOME_SUCCEEDED, "Succeeded"), (OUTCOME_DECLINED, "Declined")]

    id = models.CharField(primary_key=True, max_length=40, editable=False)
    session = models.ForeignKey(CheckoutSession, on_delete=models.CASCADE, related_name="payments")
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES)
    decline_code = models.CharField(max_length=40, blank=True)
    card_brand = models.CharField(max_length=20)
    card_last4 = models.CharField(max_length=4)
    created_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = new_id("pay")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.id} {self.card_brand} ****{self.card_last4} {self.outcome}"


class WebhookEvent(models.Model):
    id = models.CharField(primary_key=True, max_length=40, editable=False)
    type = models.CharField(max_length=60)
    session = models.ForeignKey(CheckoutSession, on_delete=models.CASCADE, related_name="events")
    payload = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_response_code = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = new_id("evt")
        super().save(*args, **kwargs)

    @property
    def data(self):
        return json.loads(self.payload)

    def __str__(self):
        return f"{self.id} {self.type}"
