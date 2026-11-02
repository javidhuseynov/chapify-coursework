"""Pure-logic tests (no database): price formula and signed messages."""

from decimal import Decimal

from django.test import SimpleTestCase

from mockgateway import signing
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


class SigningTests(SimpleTestCase):
    SECRET = "test-secret"

    def test_round_trip(self):
        token = signing.sign({"reference": "abc", "amount": "4.00"}, self.SECRET)
        data = signing.unsign(token, self.SECRET)
        self.assertEqual(data["reference"], "abc")
        self.assertEqual(data["amount"], "4.00")
        self.assertIn("issued_at", data)

    def test_modified_body_is_rejected(self):
        token = signing.sign({"amount": "4.00"}, self.SECRET)
        body, signature = token.split(".")
        forged_body = signing.sign({"amount": "0.01"}, "other").split(".")[0]
        with self.assertRaises(signing.BadSignature):
            signing.unsign(f"{forged_body}.{signature}", self.SECRET)

    def test_wrong_secret_is_rejected(self):
        token = signing.sign({"amount": "4.00"}, "attacker-secret")
        with self.assertRaises(signing.BadSignature):
            signing.unsign(token, self.SECRET)

    def test_malformed_tokens_are_rejected(self):
        for token in ["", "no-dot", ".", "abc.def", None, "ä.ö"]:
            with self.assertRaises(signing.BadSignature):
                signing.unsign(token, self.SECRET)

    def test_expired_token_is_rejected(self):
        token = signing.sign({"amount": "4.00"}, self.SECRET, issued_at=1_000)
        with self.assertRaises(signing.ExpiredSignature):
            signing.unsign(token, self.SECRET, max_age=60, now=2_000)
        self.assertEqual(signing.unsign(token, self.SECRET, max_age=60, now=1_030)["amount"], "4.00")
