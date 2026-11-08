"""Unit tests for the simulated printer (no server needed)."""

import random
import unittest

from print_station.client import check_server_url
from print_station.device import SimulatedPrinter, sides_and_sheets

PDF = b"%PDF-1.7\n..."


def job(**overrides):
    values = {"pages": 5, "copies": 2, "color_mode": "BW", "paper_format": "A4", "duplex_mode": "ONE_SIDED"}
    values.update(overrides)
    return values


def printer(**kwargs):
    kwargs.setdefault("seconds_per_page", 0)
    kwargs.setdefault("sleep", lambda seconds: None)
    return SimulatedPrinter(**kwargs)


class SheetCountTests(unittest.TestCase):
    def test_one_sided_uses_one_sheet_per_page(self):
        self.assertEqual(sides_and_sheets(job()), (10, 10))

    def test_double_sided_halves_paper_per_copy(self):
        self.assertEqual(sides_and_sheets(job(duplex_mode="DOUBLE_SIDED")), (10, 6))  # 3 sheets x 2 copies


class PrintingTests(unittest.TestCase):
    def test_successful_job_uses_paper_and_toner(self):
        device = printer()
        progress = []
        outcome = device.print_job(job(duplex_mode="DOUBLE_SIDED"), PDF, lambda side, total: progress.append(side))

        self.assertTrue(outcome.success)
        self.assertEqual((outcome.sides_printed, outcome.sheets_used), (10, 6))
        self.assertEqual(device.paper_sheets, 494)
        self.assertLess(device.toner_percent, 100)
        self.assertEqual(progress, list(range(1, 11)))

    def test_colour_uses_more_toner(self):
        bw, colour = printer(), printer()
        bw.print_job(job(), PDF)
        colour.print_job(job(color_mode="COLOR"), PDF)
        self.assertLess(colour.toner_percent, bw.toner_percent)

    def test_not_enough_paper_fails_before_printing(self):
        device = printer(paper_sheets=4)
        outcome = device.print_job(job(), PDF)

        self.assertFalse(outcome.success)
        self.assertIn("Not enough paper", outcome.reason)
        self.assertEqual(device.paper_sheets, 4)

    def test_out_of_paper_is_an_error_until_loaded(self):
        device = printer(paper_sheets=0)
        self.assertEqual(device.status()[0], "ERROR")
        device.load_paper()
        self.assertEqual(device.status()[0], "AVAILABLE")

    def test_jam_stops_the_job_and_needs_the_operator(self):
        device = printer(rng=random.Random(1))
        device.jam_next_job = True
        outcome = device.print_job(job(), PDF)

        self.assertFalse(outcome.success)
        self.assertIn("Paper jam", outcome.reason)
        self.assertEqual(device.status()[0], "ERROR")
        self.assertFalse(device.jam_next_job)
        device.clear_jam()
        self.assertEqual(device.status()[0], "AVAILABLE")

    def test_non_pdf_is_refused(self):
        outcome = printer().print_job(job(), b"MZ\x90 not a pdf")
        self.assertFalse(outcome.success)
        self.assertIn("not a PDF", outcome.reason)

    def test_switched_off_printer_is_offline(self):
        device = printer()
        device.set_online(False)
        self.assertEqual(device.status()[0], "OFFLINE")


class ServerAddressTests(unittest.TestCase):
    def test_plain_http_is_allowed_only_locally_without_warning(self):
        self.assertIsNone(check_server_url("http://127.0.0.1:8000"))
        self.assertIsNone(check_server_url("https://print.example.org"))
        self.assertIn("not encrypted", check_server_url("http://print.example.org"))

    def test_invalid_address_is_refused(self):
        with self.assertRaises(ValueError):
            check_server_url("ftp://example.org")
