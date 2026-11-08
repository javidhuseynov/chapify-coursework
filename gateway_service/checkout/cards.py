"""Test cards. This gateway accepts ONLY these numbers (like Stripe's test mode),
so no real card number is ever processed."""

TEST_CARDS = {
    "4242424242424242": ("visa", None),
    "5555555555554444": ("mastercard", None),
    "4000000000000002": ("visa", "card_declined"),
    "4000000000009995": ("visa", "insufficient_funds"),
    "4000000000000069": ("visa", "expired_card"),
    "4000000000000127": ("visa", "incorrect_cvc"),
}

DECLINE_MESSAGES = {
    "card_declined": "Your card was declined.",
    "insufficient_funds": "Your card has insufficient funds.",
    "expired_card": "Your card has expired.",
    "incorrect_cvc": "Your card's security code is incorrect.",
}

CARD_LIST = [
    ("4242 4242 4242 4242", "Visa", "Payment succeeds"),
    ("5555 5555 5555 4444", "Mastercard", "Payment succeeds"),
    ("4000 0000 0000 0002", "Visa", "Declined: card declined"),
    ("4000 0000 0000 9995", "Visa", "Declined: insufficient funds"),
    ("4000 0000 0000 0069", "Visa", "Declined: expired card"),
    ("4000 0000 0000 0127", "Visa", "Declined: incorrect security code"),
]


def luhn_valid(number):
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
