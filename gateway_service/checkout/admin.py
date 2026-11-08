"""Merchant dashboard (/dashboard/): sessions, payments and webhook deliveries."""

from django.contrib import admin, messages

from . import services
from .models import CheckoutSession, Payment, WebhookEvent


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = ("id", "outcome", "decline_code", "card_brand", "card_last4", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CheckoutSession)
class CheckoutSessionAdmin(ReadOnly):
    list_display = ("id", "merchant_reference", "amount", "currency", "status", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("id", "merchant_reference", "description")
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(ReadOnly):
    list_display = ("id", "session", "outcome", "decline_code", "card_brand", "card_last4", "created_at")
    list_filter = ("outcome", "card_brand")


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnly):
    list_display = ("id", "type", "session", "attempts", "last_response_code", "delivered_at", "next_attempt_at")
    list_filter = ("type",)
    actions = ["resend"]

    @admin.action(description="Send the selected webhooks again")
    def resend(self, request, queryset):
        delivered = sum(1 for event in queryset if services.deliver(event))
        messages.info(request, f"{delivered} of {queryset.count()} webhook(s) accepted by the merchant.")
