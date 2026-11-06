import time

from django.conf import settings
from django.core import signing
from django import forms

from .validators import DocumentValidationError, inspect_uploaded_document

from .models import Document, PrintSettings

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["file"]

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")

        try:
            # The page count is read from the PDF itself and used for pricing.
            self.page_count = inspect_uploaded_document(uploaded_file)
        except DocumentValidationError as error:
            raise forms.ValidationError(str(error))

        return uploaded_file


class PrintSettingsForm(forms.ModelForm):
    # The number of pages is not a form field: it is counted from the PDF.

    class Meta:
        model = PrintSettings
        fields = ["copies", "color_mode", "paper_format", "duplex_mode"]


REGISTRATION_FORM_SALT = "chapify.registration-form"
BOT_REFUSAL_MESSAGE = "Registration could not be completed. Please wait a moment and submit the form again."


def registration_form_token(started_at=None):
    """Signed timestamp of when the registration form was shown."""
    return signing.dumps(int(time.time() if started_at is None else started_at), salt=REGISTRATION_FORM_SALT)


class RegisterForm(UserCreationForm):
    """Registration with lightweight bot protection (no external CAPTCHA service).

    - Honeypot: the "website" field is hidden from people; simple bots fill
      every field they find.
    - Fill time: a signed timestamp shows when the form was displayed; forms
      submitted faster than REGISTRATION_MIN_FILL_SECONDS (or older than a day,
      or with a forged timestamp) are refused.
    Per-IP rate limiting is applied in the view.
    """

    email = forms.EmailField(required=True)
    website = forms.CharField(
        required=False,
        label="Leave this field empty",
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )
    form_started = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_suspected = False

        if not self.is_bound:
            self.initial["form_started"] = registration_form_token()

    def clean(self):
        cleaned_data = super().clean()

        if self.cleaned_data.get("website"):
            self._refuse_bot()

        try:
            started_at = signing.loads(
                self.cleaned_data.get("form_started") or "",
                salt=REGISTRATION_FORM_SALT,
                max_age=settings.REGISTRATION_FORM_MAX_AGE_SECONDS,
            )
        except signing.BadSignature:  # also covers expired timestamps
            self._refuse_bot()

        elapsed = time.time() - started_at

        if elapsed < settings.REGISTRATION_MIN_FILL_SECONDS or elapsed > settings.REGISTRATION_FORM_MAX_AGE_SECONDS:
            self._refuse_bot()

        return cleaned_data

    def _refuse_bot(self):
        self.bot_suspected = True
        raise forms.ValidationError(BOT_REFUSAL_MESSAGE, code="bot")

    def clean_email(self):
        email = self.cleaned_data.get("email")

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")

        return email