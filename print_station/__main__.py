"""Start a print station.

    python -m print_station --server http://127.0.0.1:8000 --key <station key>

The key can also be given in the environment variable CHAPIFY_STATION_KEY,
which keeps it out of the command history.
"""

import argparse
import os
import sys
from datetime import datetime

from . import VERSION
from .client import ChapifyClient, check_server_url
from .device import SimulatedPrinter
from .station import Station


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m print_station",
        description="Chapify Print Station: takes paid jobs from Chapify and prints them on a simulated printer.",
    )
    parser.add_argument("--server", default=os.environ.get("CHAPIFY_SERVER", "http://127.0.0.1:8000"),
                        help="Chapify address (default http://127.0.0.1:8000).")
    parser.add_argument("--key", default=os.environ.get("CHAPIFY_STATION_KEY"),
                        help="Station key from the Printers page (or set CHAPIFY_STATION_KEY).")
    parser.add_argument("--headless", action="store_true", help="No window; log to the console.")
    parser.add_argument("--once", action="store_true", help="Print what is waiting, then exit (implies --headless).")
    parser.add_argument("--seconds-per-page", type=float, default=0.5, help="Printing speed (default 0.5 s per side).")
    parser.add_argument("--jam-rate", type=float, default=0.0, help="Probability 0-1 that a job jams (default 0).")
    parser.add_argument("--paper", type=int, default=500, help="Sheets loaded at start (default 500, the tray capacity).")
    parser.add_argument("--toner", type=float, default=100.0, help="Toner level at start in percent (default 100).")
    parser.add_argument("--poll", type=float, default=3.0, help="Seconds between queue checks (default 3).")
    parser.add_argument("--receipts", default="print_station_receipts",
                        help="Folder for job receipts (JSON, no document content). Empty to disable.")
    parser.add_argument("--version", action="version", version=f"Chapify Print Station {VERSION}")
    args = parser.parse_args(argv)

    if not args.key:
        parser.error("a station key is required: --key <key> or the CHAPIFY_STATION_KEY variable")
    if not 0.0 <= args.jam_rate <= 1.0:
        parser.error("--jam-rate must be between 0 and 1")
    try:
        warning = check_server_url(args.server)
    except ValueError as error:
        parser.error(str(error))
    if warning:
        print(warning, file=sys.stderr)
    return args


def console_events(kind, data):
    stamp = datetime.now().strftime("%H:%M:%S")
    if kind == "log":
        print(f"[{stamp}] {data['message']}", flush=True)
    elif kind == "progress" and (data["side"] == data["total"] or data["side"] % 10 == 0):
        print(f"[{stamp}]   printed {data['side']} of {data['total']}", flush=True)


def build_station(args, on_event):
    device = SimulatedPrinter(
        paper_sheets=args.paper,
        toner_percent=args.toner,
        seconds_per_page=args.seconds_per_page,
        jam_rate=args.jam_rate,
    )
    client = ChapifyClient(args.server, args.key)
    return Station(client, device, poll_interval=args.poll, receipts_dir=args.receipts or None, on_event=on_event)


def main(argv=None):
    args = parse_args(argv)

    if args.once or args.headless:
        station = build_station(args, console_events)
        if args.once:
            processed = station.run_once()
            print(f"Processed {processed} job(s).")
            return 0 if station.connected else 1
        try:
            station.run_forever()
        except KeyboardInterrupt:
            pass
        return 0

    from .gui import run_window  # tkinter is only needed for the window

    return run_window(args, build_station)


if __name__ == "__main__":
    sys.exit(main())
