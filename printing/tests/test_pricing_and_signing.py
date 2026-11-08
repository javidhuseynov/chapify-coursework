"""Pure-logic tests (no database): price formula and webhook signatures."""

from decimal import Decimal

from django.test import SimpleTestCase

from printing.payment_gateways import InvalidWebhook, signature_header, verify_signature
from printing.pricing import calculate_page_price, calculate_total_price


class PriceCalculationTests(SimpleTestCase):
    def test_thesis_example_section_4_5(self):
        # 10 pages, 2 copies, colour, A4, one-sided, base price 0.10 EUR -> 4.00 EUR
        self.assertEqual(calculate_total_price(10, 2, "COLOR", "A4", "ONE_SIDED"), Decimal("4.00"))

    def test_base_case(self):
        self.assertEqual(calculate_total_price(2, 2, "BW", "A4", "ONE_SIDED"), Decimal("0.40"))

    def test_all_coefficients_combined(self):
        # 0.10 x 2.00 x 1.80 x 0.90 = 0.324 per page
        self.assertEqual(calculate_page_price("COLOR", "A3", "DOUBLE_SIDED"), Decimal("0.324"))
        self.assertEqual(calculate_total_price(1, 1, "COLOR", "A3", "DOUBLE_SIDED"), Decimal("0.32"))

    def test_rounding_is_half_up_to_cents(self):
        # 3 x 0.162 = 0.486 -> 0.49
        self.assertEqual(calculate_total_price(3, 1, "BW", "A3", "DOUBLE_SIDED"), Decimal("0.49"))

    def test_result_is_exact_decimal(self):
        total = calculate_total_price(7, 3, "BW", "A4", "DOUBLE_SIDED")
        self.assertIsInstance(total, Decimal)
        self.assertEqual(total, Decimal("1.89"))

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_total_price(0, 1, "BW", "A4", "ONE_SIDED")
        with self.assertRaises(ValueError):
            calculate_total_price(1, 1, "SEPIA", "A4", "ONE_SIDED")


class WebhookSignatureTests(SimpleTestCase):
    SECRET = "whsec_test"
    BODY = b'{"type": "checkout.session.completed", "amount": "4.00"}'

    def verify(self, header, body=BODY, secret=SECRET, now=1_000_000):
        verify_signature(header, body, secret, tolerance=300, now=now)

    def test_valid_signature(self):
        self.verify(signature_header(self.SECRET, self.BODY, timestamp=1_000_000))

    def test_modified_body_is_rejected(self):
        header = signature_header(self.SECRET, self.BODY, timestamp=1_000_000)
        with self.assertRaises(InvalidWebhook):
            self.verify(header, body=self.BODY.replace(b"4.00", b"0.01"))

    def test_wrong_secret_is_rejected(self):
        with self.assertRaises(InvalidWebhook):
            self.verify(signature_header("attacker", self.BODY, timestamp=1_000_000))

    def test_old_or_future_timestamp_is_rejected(self):
        for timestamp in (1_000_000 - 301, 1_000_000 + 301):
            with self.assertRaises(InvalidWebhook):
                self.verify(signature_header(self.SECRET, self.BODY, timestamp=timestamp))

    def test_timestamp_cannot_be_changed(self):
        header = signature_header(self.SECRET, self.BODY, timestamp=900_000)
        forged = header.replace("t=900000", "t=1000000")
        with self.assertRaises(InvalidWebhook):
            self.verify(forged)

    def test_malformed_headers_are_rejected(self):
        for header in ("", None, "v1=abc", "t=1000000", "t=abc,v1=def", "garbage"):
            with self.assertRaises(InvalidWebhook):
                self.verify(header)
