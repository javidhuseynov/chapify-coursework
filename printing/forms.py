from django import forms

from .models import Document, PrintSettings

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["file"]

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")

        if not uploaded_file:
            raise forms.ValidationError("Document file is required.")

        allowed_extensions = [".pdf", ".docx", ".txt"]
        file_name = uploaded_file.name.lower()

        if not any(file_name.endswith(ext) for ext in allowed_extensions):
            raise forms.ValidationError("Only PDF, DOCX, and TXT files are allowed.")

        max_size = 5 * 1024 * 1024

        if uploaded_file.size > max_size:
            raise forms.ValidationError("File size must not exceed 5 MB.")

        return uploaded_file


class PrintSettingsForm(forms.ModelForm):
    document_pages = forms.IntegerField(
        min_value=1,
        initial=1,
        label="Number of pages"
    )

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