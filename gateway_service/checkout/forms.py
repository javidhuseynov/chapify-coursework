import re
from datetime import date

from django import forms

from .cards import TEST_CARDS, luhn_valid


class NoEchoTextInput(forms.TextInput):
    """Never write a submitted value back into the page (card number, security code)."""

    def format_value(self, value):
        return None


class CardForm(forms.Form):
    name = forms.CharField(label="Name on card", max_length=100,
                           widget=forms.TextInput(attrs={"autocomplete": "cc-name"}))
    number = forms.CharField(
        label="Card number", max_length=23,
        widget=NoEchoTextInput(attrs={"autocomplete": "cc-number", "inputmode": "numeric", "placeholder": "4242 4242 4242 4242"}),
    )
    expiry = forms.CharField(label="Expiry (MM/YY)", max_length=5,
                             widget=forms.TextInput(attrs={"autocomplete": "cc-exp", "placeholder": "MM/YY"}))
    cvc = forms.CharField(label="Security code", max_length=4,
                          widget=NoEchoTextInput(attrs={"autocomplete": "cc-csc", "inputmode": "numeric", "placeholder": "123"}))

    def clean_number(self):
        number = re.sub(r"[\s-]", "", self.cleaned_data["number"])
        if not number.isdigit() or not 13 <= len(number) <= 19 or not luhn_valid(number):
            raise forms.ValidationError("This card number is not valid.")
        if number not in TEST_CARDS:
            raise forms.ValidationError("This is a test gateway: use one of the test card numbers below.")
        return number

    def clean_expiry(self):
        match = re.fullmatch(r"(\d{2})\s*/\s*(\d{2})", self.cleaned_data["expiry"].strip())
        if not match or not 1 <= int(match.group(1)) <= 12:
            raise forms.ValidationError("Enter the expiry date as MM/YY.")
        month, year = int(match.group(1)), 2000 + int(match.group(2))
        today = date.today()
        if (year, month) < (today.year, today.month):
            raise forms.ValidationError("This card has expired.")
        return f"{month:02d}/{year % 100:02d}"

    def clean_cvc(self):
        cvc = self.cleaned_data["cvc"].strip()
        if not re.fullmatch(r"\d{3,4}", cvc):
            raise forms.ValidationError("Enter the 3 or 4 digit security code.")
        return cvc

    def clean(self):
        cleaned = super().clean()
        if "number" in cleaned:
            cleaned["brand"], cleaned["decline_code"] = TEST_CARDS[cleaned["number"]]
        return cleaned
