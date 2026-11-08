"""Print stations: printer API, station keys, watchdog, and the real station program."""

import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import LiveServerTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from print_station.client import ChapifyClient
from print_station.device import SimulatedPrinter
from print_station.station import Station
from printing import api_tokens, services, stations
from printing.models import AuditLog, Printer, PrintJob, PrintRequest

from .base import PASSWORD, ChapifyTestCase


class StationTestMixin:
    def connect_station(self, printer=None, admin=None):
        printer = printer or self.printer
        admin = admin or self.admin
        key = stations.issue_station_key(printer, admin)
        return key

    def call(self, method, url, key, data=None):
        kwargs = {"HTTP_AUTHORIZATION": f"Printer {key}"}
        if data is not None:
            kwargs.update(data=json.dumps(data), content_type="application/json")
        return getattr(self.client, method)(url, **kwargs)

    def heartbeat(self, key, status="AVAILABLE", **extra):
        data = {"status": status, "paper_sheets": 480, "toner_percent": 90, "station": "test station"}
        data.update(extra)
        return self.call("post", "/api/printer/heartbeat/", key, data)

    def next_job(self, key):
        return self.call("post", "/api/printer/jobs/next/", key)


class PrinterApiTests(StationTestMixin, ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.user = self.make_user()
        Printer.objects.all().delete()  # remove the default printer from migration 0003
        self.printer = Printer.objects.create(printer_name="Library Printer", location="Library")
        self.key = self.connect_station()
        self.printer.refresh_from_db()
        self.print_request = self.make_paid_request(self.user)
        self.job = PrintJob.objects.get(print_request=self.print_request)

    def test_new_station_is_offline_until_first_heartbeat(self):
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.printer_status, Printer.STATUS_OFFLINE)
        self.assertNotIn(self.key, self.printer.station_key_hash)

        response = self.heartbeat(self.key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["printer"]["status"], "AVAILABLE")
        self.printer.refresh_from_db()
        self.assertEqual((self.printer.paper_sheets, self.printer.toner_percent), (480, 90))
        self.assertTrue(AuditLog.objects.filter(description__contains="connected").exists())

    def test_keys_are_checked(self):
        self.assertEqual(self.heartbeat("prn_wrong").status_code, 401)
        self.assertEqual(self.client.post("/api/printer/heartbeat/").status_code, 401)

        # A user's API token is not a printer key.
        _, user_token = api_tokens.issue_token(self.admin, "admin phone")
        response = self.client.post("/api/printer/jobs/next/", HTTP_AUTHORIZATION=f"Token {user_token}")
        self.assertIn(response.status_code, (401, 403))

        # A printer key is not a user token.
        response = self.client.get("/api/my/requests/", HTTP_AUTHORIZATION=f"Printer {self.key}")
        self.assertIn(response.status_code, (401, 403))

    def test_station_takes_downloads_and_completes_a_job(self):
        self.heartbeat(self.key)
        response = self.next_job(self.key)
        self.assertEqual(response.status_code, 200)
        job = response.json()

        self.assertEqual(job["id"], self.job.id)
        self.assertFalse(job["resumed"])
        self.assertEqual((job["pages"], job["copies"], job["color_mode"]), (10, 2, "COLOR"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_IN_PROGRESS)

        download = self.call("get", job["document_url"], self.key)
        self.assertEqual(download.status_code, 200)
        content = b"".join(download.streaming_content)
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertEqual(len(content), job["document_size"])

        response = self.call("post", f"/api/printer/jobs/{job['id']}/complete/", self.key)
        self.assertEqual(response.json()["job_status"], "COMPLETED")
        self.print_request.refresh_from_db()
        self.assertEqual(self.print_request.status, PrintRequest.STATUS_COMPLETED)
        self.assertFalse(self.print_request.document.has_file())
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.printer_status, Printer.STATUS_AVAILABLE)

    def test_failure_report_keeps_the_file_for_a_retry(self):
        self.heartbeat(self.key)
        job = self.next_job(self.key).json()
        response = self.call("post", f"/api/printer/jobs/{job['id']}/fail/", self.key, {"reason": "Paper jam on page 3"})

        self.assertEqual(response.json()["job_status"], "FAILED")
        self.job.refresh_from_db()
        self.assertEqual(self.job.failure_reason, "Print station: Paper jam on page 3")
        self.assertTrue(self.print_request.document.has_file())

    def test_no_job_and_unavailable_printer(self):
        self.assertEqual(self.next_job(self.key).status_code, 409)  # still offline
        self.heartbeat(self.key)
        self.next_job(self.key)
        self.call("post", f"/api/printer/jobs/{self.job.id}/complete/", self.key)
        self.assertEqual(self.next_job(self.key).status_code, 204)

    def test_station_cannot_touch_another_printers_job(self):
        other = Printer.objects.create(printer_name="Other", location="Lab")
        other_key = self.connect_station(other)
        self.heartbeat(self.key)
        job = self.next_job(self.key).json()

        self.assertEqual(self.call("get", job["document_url"], other_key).status_code, 404)
        self.assertEqual(self.call("post", f"/api/printer/jobs/{job['id']}/complete/", other_key).status_code, 404)
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_IN_PROGRESS)

    def test_restarted_station_gets_its_running_job_again(self):
        self.heartbeat(self.key)
        first = self.next_job(self.key).json()
        again = self.next_job(self.key).json()
        self.assertEqual(again["id"], first["id"])
        self.assertTrue(again["resumed"])

    def test_heartbeat_does_not_free_a_busy_printer(self):
        self.heartbeat(self.key)
        self.next_job(self.key)
        self.heartbeat(self.key, status="AVAILABLE")
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.printer_status, Printer.STATUS_BUSY)

    def test_watchdog_marks_silent_station_offline_and_fails_its_job(self):
        self.heartbeat(self.key)
        self.next_job(self.key)
        Printer.objects.filter(pk=self.printer.pk).update(
            station_last_seen_at=timezone.now() - timedelta(minutes=5)
        )

        self.assertEqual(stations.expire_silent_stations(), 1)
        self.printer.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.printer.printer_status, Printer.STATUS_OFFLINE)
        self.assertEqual(self.job.job_status, PrintJob.STATUS_FAILED)
        self.assertEqual(self.job.failure_reason, "Print station stopped responding.")
        # The administrator can print it again once a printer is available.
        services.retry_print_job(self.job, self.admin)

    def test_built_in_simulator_leaves_station_printers_alone(self):
        self.heartbeat(self.key)
        self.assertIsNone(services.process_next_print_job())
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, PrintJob.STATUS_QUEUED)

    def test_station_takes_jobs_waiting_for_an_unavailable_printer(self):
        Printer.objects.filter(pk=self.printer.pk).update(station_key_hash="", printer_status=Printer.STATUS_OFFLINE)
        second = Printer.objects.create(printer_name="Second", location="Lab")
        key = self.connect_station(second)
        self.heartbeat(key)
        self.assertEqual(self.next_job(key).json()["id"], self.job.id)

    def test_station_status_cannot_be_set_by_hand(self):
        with self.assertRaises(services.WorkflowError):
            services.set_printer_status(self.printer, Printer.STATUS_AVAILABLE, self.admin)

    def test_new_key_replaces_the_old_one(self):
        self.heartbeat(self.key)
        new_key = self.connect_station()
        self.assertEqual(self.heartbeat(self.key).status_code, 401)
        self.assertEqual(self.heartbeat(new_key).status_code, 200)

    def test_document_is_described_by_the_schema(self):
        self.client.force_login(self.admin)
        paths = self.client.get(reverse("api_schema"), {"format": "json"}).json()["paths"]
        self.assertIn("/api/printer/jobs/next/", paths)


class StationAdminTests(StationTestMixin, ChapifyTestCase):
    def setUp(self):
        self.admin = self.make_admin()
        self.printer = Printer.objects.create(printer_name="Library Printer", location="Library")
        self.client.login(username="admin", password=PASSWORD)

    def test_connect_shows_the_key_once_and_it_works(self):
        response = self.client.post(reverse("admin_printer_station", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        key = response.context["station_key"]
        self.assertIn(key, response.content.decode())

        page = self.client.get(reverse("admin_printers")).content.decode()
        self.assertNotIn(key, page)
        self.assertIn("Waiting for the station to connect", page)

        self.client.logout()
        self.assertEqual(self.heartbeat(key).status_code, 200)

    def test_printers_page_shows_connection_and_consumables(self):
        key = self.connect_station()
        self.heartbeat(key)
        page = self.client.get(reverse("admin_printers")).content.decode()
        self.assertIn("Connected", page)
        self.assertIn("Paper 480 sheets", page)

    def test_disconnect(self):
        key = self.connect_station()
        self.client.post(reverse("admin_printer_station", args=[self.printer.pk]), {"action": "disconnect"})
        self.printer.refresh_from_db()
        self.assertFalse(self.printer.has_station)
        self.assertEqual(self.heartbeat(key).status_code, 401)

    def test_students_cannot_connect_stations(self):
        self.client.logout()
        self.make_user()
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.post(reverse("admin_printer_station", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 403)

    def test_management_command_prints_a_working_key(self):
        out = StringIO()
        call_command("printer_station_key", "library printer", stdout=out)
        key = out.getvalue().strip().splitlines()[-1]
        self.assertTrue(key.startswith("prn_"))
        self.client.logout()
        self.assertEqual(self.heartbeat(key).status_code, 200)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PrintStationProgramTests(LiveServerTestCase):
    """The real print_station program against a running Chapify server."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="chapify-live-media-")
        self.receipts = Path(tempfile.mkdtemp(prefix="chapify-receipts-"))
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(shutil.rmtree, self.receipts, True)

        helper = ChapifyTestCase()
        self.user = helper.make_user()
        self.admin = helper.make_admin()
        Printer.objects.all().delete()
        self.printer = Printer.objects.create(printer_name="Library Printer", location="Library")
        self.key = stations.issue_station_key(self.printer, self.admin)
        self.requests = [helper.make_paid_request(self.user), helper.make_paid_request(self.user, duplex_mode="DOUBLE_SIDED")]

    def station(self, **device_options):
        device_options.setdefault("seconds_per_page", 0)
        device = SimulatedPrinter(**device_options)
        events = []
        station = Station(
            ChapifyClient(self.live_server_url, self.key),
            device,
            receipts_dir=self.receipts,
            on_event=lambda kind, data: events.append((kind, data)),
        )
        return station, device, events

    def test_station_prints_the_queue_and_writes_receipts(self):
        station, device, events = self.station()
        self.assertEqual(station.run_once(), 2)

        for print_request in self.requests:
            print_request.refresh_from_db()
            self.assertEqual(print_request.status, PrintRequest.STATUS_COMPLETED)
            self.assertFalse(print_request.document.has_file())

        self.assertEqual(device.paper_sheets, 500 - 20 - 10)  # one-sided 10x2, double-sided 5x2
        receipts = sorted(self.receipts.glob("job-*.json"))
        self.assertEqual(len(receipts), 2)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["result"], "printed")
        self.assertNotIn("%PDF", receipts[0].read_text())
        self.assertTrue(any(kind == "progress" for kind, _ in events))
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.station_info, "Chapify Print Station 1.0.0")

    def test_jam_is_reported_and_station_waits_for_the_operator(self):
        station, device, _ = self.station()
        device.jam_next_job = True

        self.assertEqual(station.run_once(), 1)
        job = PrintJob.objects.get(print_request=self.requests[0])
        self.assertEqual(job.job_status, PrintJob.STATUS_FAILED)
        self.assertIn("Paper jam", job.failure_reason)
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.printer_status, Printer.STATUS_ERROR)
        self.assertEqual(PrintJob.objects.get(print_request=self.requests[1]).job_status, PrintJob.STATUS_QUEUED)

        device.clear_jam()
        self.assertEqual(station.run_once(), 1)
        self.assertEqual(PrintJob.objects.get(print_request=self.requests[1]).job_status, PrintJob.STATUS_COMPLETED)

    def test_wrong_key_means_not_connected(self):
        station, _, _ = self.station()
        station.client.key = "prn_wrong"
        self.assertEqual(station.run_once(), 0)
        self.assertFalse(station.connected)
