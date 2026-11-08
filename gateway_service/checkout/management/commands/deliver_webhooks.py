import time

from django.core.management.base import BaseCommand

from checkout import services


class Command(BaseCommand):
    help = "Send webhooks that are due for a retry (use --loop to keep running)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Keep running, checking every 5 seconds.")

    def handle(self, *args, **options):
        while True:
            delivered = services.deliver_due(limit=50)
            if delivered or not options["loop"]:
                self.stdout.write(f"Delivered {delivered} webhook(s).")
            if not options["loop"]:
                return
            time.sleep(5)
