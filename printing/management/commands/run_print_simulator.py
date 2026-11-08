import random
import time

from django.core.management.base import BaseCommand, CommandError

from printing import services, stations
from printing.models import PrintJob


class Command(BaseCommand):
    help = (
        "Simulated print server: takes queued print jobs, 'prints' them and marks "
        "them COMPLETED or FAILED. Runs until Ctrl+C unless --once is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process the queue once and exit.")
        parser.add_argument(
            "--interval",
            type=float,
            default=3.0,
            help="Seconds to wait between queue checks (default 3).",
        )
        parser.add_argument(
            "--seconds-per-page",
            type=float,
            default=0.5,
            help="Simulated printing time per printed page (default 0.5).",
        )
        parser.add_argument(
            "--fail-rate",
            type=float,
            default=0.0,
            help="Probability (0-1) that a job fails with a simulated printer error (default 0).",
        )
        parser.add_argument("--seed", type=int, default=None, help="Random seed (reproducible failures).")

    def handle(self, *args, **options):
        fail_rate = options["fail_rate"]

        if not 0.0 <= fail_rate <= 1.0:
            raise CommandError("--fail-rate must be between 0 and 1.")

        rng = random.Random(options["seed"])
        self.stdout.write("Chapify print simulator started. Press Ctrl+C to stop.")

        try:
            while True:
                stations.expire_silent_stations()
                processed = self.process_queue(rng, fail_rate, options["seconds_per_page"])

                if options["once"]:
                    self.stdout.write(f"Processed {processed} job(s).")
                    return

                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Print simulator stopped.")

    def process_queue(self, rng, fail_rate, seconds_per_page):
        processed = 0

        while True:
            job = services.start_next_print_job()

            if job is None:
                if PrintJob.objects.filter(job_status=PrintJob.STATUS_QUEUED).exists():
                    self.stdout.write(self.style.WARNING(
                        "Jobs are queued but no simulator printer is AVAILABLE "
                        "(printers with a print station are served by their station)."
                    ))
                return processed

            print_request = job.print_request
            sheets = print_request.document_pages * print_request.settings.copies
            self.stdout.write(f"Printing job #{job.id} (request #{print_request.id}, {sheets} page(s)) on {job.printer}...")
            time.sleep(max(0.0, seconds_per_page) * sheets)

            if not print_request.document.has_file():
                job = services.finish_print_job(job, False, "Document file is missing.")
            elif fail_rate and rng.random() < fail_rate:
                job = services.finish_print_job(job, False, "Simulated printer error.")
            else:
                job = services.finish_print_job(job, True)

            style = self.style.SUCCESS if job.job_status == PrintJob.STATUS_COMPLETED else self.style.ERROR
            self.stdout.write(style(f"  job #{job.id}: {job.job_status} {job.failure_reason}".rstrip()))
            processed += 1
