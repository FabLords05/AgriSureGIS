"""
In-memory job registry backing real progress tracking for CSV ingestion
(2026-08-16 -- per Fabio's explicit request for a real percentage progress
bar, not just a spinner). CSV ingestion runs row-by-row already (see
app/api/upload.py's upload_csv loop) and is genuinely slow for a large real
PABS export -- previously a single synchronous request the frontend had zero
visibility into until it finally returned.

Deliberately plain in-process memory, not Redis/a DB table -- same
single-worker assumption already documented for the APScheduler job in
app/core/scheduler.py (this repo's dev setup is one uvicorn process). A job
started on one worker wouldn't be visible from another, but there's only
ever one. Jobs are never explicitly deleted -- they're small and this
process doesn't run indefinitely between restarts; not worth the complexity
of a cleanup sweep for a capstone-scale deployment.
"""
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["processing", "done", "error"]


@dataclass
class UploadJob:
    total: int
    processed: int = 0
    status: JobStatus = "processing"
    result: dict[str, Any] | None = None
    error: str | None = None


_jobs: dict[str, UploadJob] = {}
_lock = threading.Lock()


def create_job(total: int) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = UploadJob(total=total)
    return job_id


def update_progress(job_id: str, processed: int) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.processed = processed


def mark_done(job_id: str, result: dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.processed = job.total
            job.status = "done"
            job.result = result


def mark_error(job_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "error"
            job.error = error


def get_job(job_id: str) -> UploadJob | None:
    with _lock:
        return _jobs.get(job_id)
