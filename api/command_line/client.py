"""Small standard-library HTTP client for the Polar-is job API."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class PolarIsClientError(RuntimeError):
    pass


class PolarIsClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _json_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = self._headers()
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                body = json.loads(error.read().decode("utf-8"))
                detail = body.get("detail", body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = error.reason
            raise PolarIsClientError(f"Polar-is returned {error.code}: {detail}") from error
        except URLError as error:
            raise PolarIsClientError(f"Could not reach Polar-is: {error.reason}") from error

    def create_job(
        self, query: dict[str, Any], outputs: list[str]
    ) -> dict[str, Any]:
        return self._json_request(
            "POST", "/api/v1/jobs", {"query": query, "outputs": outputs}
        )

    def catalog(self) -> dict[str, Any]:
        return self._json_request("GET", "/api/catalog")

    def status(self) -> dict[str, Any]:
        return self._json_request("GET", "/api/v1/status")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._json_request("GET", f"/api/v1/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._json_request("DELETE", f"/api/v1/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 0.5,
        timeout: float = 600,
        on_status: Callable[[str, int | None], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            status = str(job["status"])
            jobs_ahead = job.get("jobs_ahead")
            update = (status, jobs_ahead)
            if on_status is not None and update != previous:
                on_status(status, jobs_ahead)
            previous = update
            if status == "completed":
                return job
            if status in {"failed", "cancelled", "expired"}:
                message = (job.get("error") or {}).get("message", status)
                raise PolarIsClientError(f"Job {status}: {message}")
            time.sleep(poll_interval)
        raise PolarIsClientError(
            f"Job did not finish within {timeout:g} seconds; it may still be running"
        )

    def download(self, path: str, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            headers=self._headers(),
            method="GET",
        )
        temporary = destination.with_name(destination.name + ".partial")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                with temporary.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            temporary.replace(destination)
        except HTTPError as error:
            raise PolarIsClientError(
                f"Download failed with status {error.code}: {error.reason}"
            ) from error
        except URLError as error:
            raise PolarIsClientError(f"Download failed: {error.reason}") from error
        finally:
            temporary.unlink(missing_ok=True)
        return destination
