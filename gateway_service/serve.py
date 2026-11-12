"""Run Chapify Pay with waitress (for load tests): python serve.py"""

import argparse
import os

from waitress import serve

from gateway_project.wsgi import application

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gateway_project.settings")
    print(f"Chapify Pay (waitress, {args.threads} threads) on http://127.0.0.1:{args.port}/")
    serve(application, host="127.0.0.1", port=args.port, threads=args.threads)
