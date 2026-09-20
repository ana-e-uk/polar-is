"""Bounded in-memory job service for the Polar-is research prototype."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
from threading import RLock
from typing import Any
from uuid import uuid4

from polaris.config import Settings
from polaris.services.query_service import (
    OutputArtifact,
    QueryArtifacts,
    execute_job,
    validate_job_request,
)


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "expired"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


@dataclass
class Job:
    job_id: str
    owner: str
    query: dict[str, Any]
    requested_outputs: tuple[str, ...]
    status: str = "queued"
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    groups: tuple[dict[str, Any], ...] = ()
    result: dict[str, Any] | None = None
    artifacts: dict[tuple[str, str], OutputArtifact] = field(default_factory=dict)
    output_root: Path | None = None
    error: dict[str, str] | None = None
    cancellation_requested: bool = False
    future: Future | None = None


class JobNotFound(KeyError):
    pass


class JobAccessDenied(PermissionError):
    pass


class JobQueueFull(RuntimeError):
    pass


class JobService:
    """Run jobs in a small thread pool and keep metadata until expiry."""

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        max_queued_per_owner: int | None = None,
        max_active_jobs: int | None = None,
        result_ttl_seconds: int | None = None,
    ) -> None:
        self.max_workers = max_workers or int(os.getenv("POLARIS_JOB_WORKERS", "2"))
        self.max_queued_per_owner = max_queued_per_owner or int(
            os.getenv("POLARIS_MAX_QUEUED_PER_USER", "3")
        )
        self.max_active_jobs = max_active_jobs or int(
            os.getenv("POLARIS_MAX_ACTIVE_JOBS", "20")
        )
        self.result_ttl = timedelta(
            seconds=result_ttl_seconds
            or int(os.getenv("POLARIS_RESULT_TTL_SECONDS", "600"))
        )
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="polaris-job"
        )
        self._jobs: dict[str, Job] = {}
        self._lock = RLock()

    def submit(
        self,
        query: dict[str, Any],
        outputs: tuple[str, ...] | list[str],
        owner: str,
        settings: Settings,
        *,
        enforce_owner_limit: bool = True,
    ) -> Job:
        requested = validate_job_request(query, outputs, settings)
        self.cleanup_expired()
        with self._lock:
            total_active = sum(
                job.status in {"queued", "running"} for job in self._jobs.values()
            )
            if total_active >= self.max_active_jobs:
                raise JobQueueFull("Polar-is is busy; try again shortly")
            if enforce_owner_limit:
                active = sum(
                    job.owner == owner and job.status in {"queued", "running"}
                    for job in self._jobs.values()
                )
                if active >= self.max_queued_per_owner + 1:
                    raise JobQueueFull(
                        "Your Polar-is job limit has been reached; "
                        "wait for a job to finish and try again"
                    )
            job = Job(uuid4().hex, owner, dict(query), requested)
            self._jobs[job.job_id] = job
            job.future = self._executor.submit(self._run, job.job_id, settings)
            return job

    def _run(self, job_id: str, settings: Settings) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.cancellation_requested:
                job.status = "cancelled"
                job.completed_at = _now()
                job.expires_at = job.completed_at + self.result_ttl
                return
            job.status = "running"
            job.started_at = _now()
        output_root = settings._query_results / "jobs" / job_id
        output_root.mkdir(parents=True, exist_ok=True)
        active_marker = output_root / ".active"
        active_marker.touch()
        try:
            completed: QueryArtifacts = execute_job(
                job.job_id, job.query, job.requested_outputs, settings
            )
        except Exception as error:
            with self._lock:
                job.output_root = settings._query_results / "jobs" / job.job_id
                job.status = "cancelled" if job.cancellation_requested else "failed"
                job.completed_at = _now()
                job.expires_at = job.completed_at + self.result_ttl
                job.error = {
                    "code": "QUERY_EXECUTION_FAILED",
                    "message": str(error),
                }
            return
        finally:
            active_marker.unlink(missing_ok=True)
        with self._lock:
            job.output_root = completed.output_root
            job.groups = completed.groups
            job.result = completed.result
            job.artifacts = {
                (artifact.group_id, artifact.kind): artifact
                for artifact in completed.outputs
            }
            job.status = "cancelled" if job.cancellation_requested else "completed"
            job.completed_at = _now()
            job.expires_at = job.completed_at + self.result_ttl

    def get(self, job_id: str, owner: str) -> Job:
        self.cleanup_expired()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.owner != owner:
                raise JobAccessDenied(job_id)
            return job

    def cancel(self, job_id: str, owner: str) -> Job:
        job = self.get(job_id, owner)
        with self._lock:
            if job.status in TERMINAL_STATES:
                return job
            job.cancellation_requested = True
            if job.future is not None and job.future.cancel():
                job.status = "cancelled"
                job.completed_at = _now()
                job.expires_at = job.completed_at + self.result_ttl
            return job

    def artifact(
        self, job_id: str, group_id: str, kind: str, owner: str
    ) -> OutputArtifact:
        job = self.get(job_id, owner)
        if job.status != "completed":
            raise JobNotFound(job_id)
        try:
            return job.artifacts[(group_id, kind)]
        except KeyError as error:
            raise JobNotFound(f"{job_id}/{group_id}/{kind}") from error

    def response(self, job: Job) -> dict[str, Any]:
        body: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status,
            "status_url": f"/api/v1/jobs/{job.job_id}",
            "created_at": _iso(job.created_at),
            "started_at": _iso(job.started_at),
            "completed_at": _iso(job.completed_at),
            "expires_at": _iso(job.expires_at),
        }
        if job.groups:
            body["groups"] = list(job.groups)
        if job.result is not None:
            body["result"] = job.result
        if job.error is not None:
            body["error"] = job.error
        if job.status == "queued":
            body["jobs_ahead"] = self.jobs_ahead(job.job_id)
        return body

    def jobs_ahead(self, job_id: str) -> int:
        """Return running and earlier queued jobs ahead of one queued job."""
        with self._lock:
            count = 0
            for current_id, job in self._jobs.items():
                if current_id == job_id:
                    return count
                if job.status in {"queued", "running"}:
                    count += 1
        return 0

    def status(self) -> dict[str, int]:
        """Return a small public snapshot of queue utilization."""
        self.cleanup_expired()
        with self._lock:
            running = sum(job.status == "running" for job in self._jobs.values())
            queued = sum(job.status == "queued" for job in self._jobs.values())
        return {
            "running_jobs": running,
            "queued_jobs": queued,
            "queue_capacity": self.max_active_jobs,
        }

    def cleanup_expired(self) -> None:
        now = _now()
        expired: list[Job] = []
        with self._lock:
            for job in self._jobs.values():
                if job.expires_at is not None and job.expires_at <= now:
                    job.status = "expired"
                    expired.append(job)
            for job in expired:
                self._jobs.pop(job.job_id, None)
        for job in expired:
            if job.output_root is not None and job.output_root.is_dir():
                shutil.rmtree(job.output_root)

    def clear(self) -> None:
        """Clear completed metadata; intended for tests."""
        with self._lock:
            self._jobs.clear()


job_service = JobService()
