from django.core.management.base import BaseCommand, CommandError

from printing import stations
from printing.models import Printer


class Command(BaseCommand):
    help = (
        "Generate a print station key for a printer (same as 'Connect a print station' "
        "on the Printers page). The key is printed once; any previous key stops working."
    )

    def add_arguments(self, parser):
        parser.add_argument("printer", help="Printer name or id.")

    def handle(self, *args, **options):
        value = options["printer"]
        printer = (
            Printer.objects.filter(pk=int(value)).first()
            if value.isdigit()
            else Printer.objects.filter(printer_name__iexact=value).first()
        )

        if printer is None:
            raise CommandError(f"No printer '{value}'. Printers: "
                               + ", ".join(Printer.objects.values_list("printer_name", flat=True)))

        raw_key = stations.issue_station_key(printer, actor=None)
        self.stdout.write(f"Print station key for {printer.printer_name}:")
        self.stdout.write(raw_key)
