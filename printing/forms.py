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


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data.get("email")

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")

        return email