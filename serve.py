"""Run Chapify with a production-grade server (waitress) instead of runserver.

    python serve.py                 Chapify on 127.0.0.1:8000
    python serve.py --threads 16

Used for load tests: Django's runserver is for development and would make
the measurements meaningless. Static files are still served by Django only
when CHAPIFY_DEBUG=True.
"""

import argparse
import os

from waitress import serve

from chapify.wsgi import application

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chapify.settings")
    print(f"Chapify (waitress, {args.threads} threads) on http://{args.host}:{args.port}/")
    serve(application, host=args.host, port=args.port, threads=args.threads)
