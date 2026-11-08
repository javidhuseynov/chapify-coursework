"""HTTP client for Chapify's printer API (standard library only)."""

import json
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from . import VERSION

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class ConnectionProblem(Exception):
    """Chapify could not be reached (network error, server down)."""


class ApiError(Exception):
    """Chapify answered with an error status."""

    def __init__(self, status, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def check_server_url(server):
    """Return a warning for unsafe server URLs, or raise ValueError for invalid ones."""
    parts = urlsplit(server)

    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The server address must start with http:// or https://")

    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        return (
            "Warning: the connection to Chapify is not encrypted (http). "
            "Use https:// outside a local demonstration, or the station key can be intercepted."
        )
    return None


class ChapifyClient:
    def __init__(self, server, key, timeout=15):
        check_server_url(server)
        self.server = server.rstrip("/") + "/"
        self.key = key
        self.timeout = timeout

    def _request(self, method, path, data=None, expect_json=True):
        body = None
        headers = {
            "Authorization": f"Printer {self.key}",
            "Accept": "application/json",
            "User-Agent": f"Chapify-Print-Station/{VERSION}",
        }

        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            urljoin(self.server, path.lstrip("/")), data=body, method=method, headers=headers
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                payload = response.read(MAX_DOCUMENT_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, self._detail(error.read(64 * 1024))) from None
        except (urllib.error.URLError, OSError) as error:
            raise ConnectionProblem(f"Cannot reach Chapify at {self.server}: {getattr(error, 'reason', error)}") from None

        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ApiError(status, "Response too large.")

        if not expect_json:
            return status, payload

        return status, (json.loads(payload) if payload else None)

    @staticmethod
    def _detail(raw):
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return raw[:200].decode("utf-8", errors="replace") or "no details"
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
        return str(data)[:200]

    def heartbeat(self, status, message="", paper_sheets=None, toner_percent=None):
        _, data = self._request(
            "POST",
            "api/printer/heartbeat/",
            {
                "status": status,
                "message": message,
                "paper_sheets": paper_sheets,
                "toner_percent": toner_percent,
                "station": f"Chapify Print Station {VERSION}",
            },
        )
        return data

    def next_job(self):
        """The next job to print, or None."""
        status, data = self._request("POST", "api/printer/jobs/next/")
        return data if status == 200 else None

    def download(self, document_url):
        _, payload = self._request("GET", document_url, expect_json=False)
        return payload

    def complete(self, job_id):
        return self._request("POST", f"api/printer/jobs/{job_id}/complete/")[1]

    def fail(self, job_id, reason):
        return self._request("POST", f"api/printer/jobs/{job_id}/fail/", {"reason": reason[:200]})[1]
