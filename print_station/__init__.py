"""Chapify Print Station: the program that runs next to a printer.

It is a separate application from the Chapify web server. It uses only the
Python standard library and talks to Chapify over HTTP(S) with the printer's
station key (see printing/printer_api.py on the server side):

    client.py   HTTP client for the printer API
    device.py   the simulated printer hardware (paper, toner, speed, jams)
    station.py  the work loop: heartbeat -> take job -> download -> print -> report
    gui.py      the operator window (tkinter)
    __main__.py command line: python -m print_station --help
"""

VERSION = "1.0.0"
