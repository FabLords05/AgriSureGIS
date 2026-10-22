"""
In-memory registry for assessment calculation runs (2026-10-22): real,
stage-by-stage progress for the Assessment & Reporting progress bar and the
Main Dashboard's Assessment Progress strip, instead of one blocking request.

Same single-process assumption as upload_jobs.py (one uvicorn worker, the
APScheduler job in the same process). A backend restart loses running jobs,
and the thread doing the work with them, so the two stay consistent: the
frontend then sees "unknown job" and the DB-derived progress strip.

Stages run strictly one after another; exactly one is "processing" at a
time, a failed stage stops the run and leaves every later stage "pending",
and percent only reaches 100 once the final commit has succeeded.
"""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

JobStatus = Literal["processing", "done", "error"]
StageStatus = Literal["pending", "processing", "completed", "failed"]

# (key, label, share of the overall percentage). Order is execution order:
# exposure must exist before the farms in exposed municipalities can be
# matched, and both before any payout is calculated.
STAGES: tuple[tuple[str, str, int], ...] = (
    ("data_preparation", "Data Preparation", 5),
    ("exposure_calculation", "Exposure Calculation", 20),
    ("spatial_analysis", "Spatial Analysis", 15),
    ("indemnity_calculation", "Indemnity Calculation", 55),
    ("completion", "Completion", 5),
)
_STAGE_INDEX = {key: i for i, (key, _, _) in enumerate(STAGES)}


@dataclass
class AssessmentJob:
    job_id: str
    typhoon_id: int
    bulletin_id: int
    source: str  # "manual" | "final-bulletin"
    started_at: datetime
    status: JobStatus = "processing"
    stage_statuses: list[StageStatus] = field(default_factory=lambda: ["pending"] * len(STAGES))
    stage_processed: int = 0
    stage_total: int = 0
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def current_stage_index(self) -> int | None:
        for i, status in enumerate(self.stage_statuses):
            if status in ("processing", "failed"):
                return i
        return None

    def percent(self) -> int:
        if self.status == "done":
            return 100
        done = sum(weight for (_, _, weight), status in zip(STAGES, self.stage_statuses) if status == "completed")
        current = self.current_stage_index()
        if current is not None and self.stage_statuses[current] == "processing" and self.stage_total > 0:
            done += STAGES[current][2] * min(self.stage_processed, self.stage_total) / self.stage_total
        # 100 is reserved for a committed, finished run.
        return min(int(done), 99)

    def to_dict(self) -> dict[str, Any]:
        current = self.current_stage_index()
        return {
            "job_id": self.job_id,
            "typhoon_id": self.typhoon_id,
            "bulletin_id": self.bulletin_id,
            "source": self.source,
            "status": self.status,
            "percent": self.percent(),
            "current_stage": STAGES[current][0] if current is not None else None,
            "current_stage_label": STAGES[current][1] if current is not None else None,
            "stage_processed": self.stage_processed,
            "stage_total": self.stage_total,
            "stages": [
                {"key": key, "label": label, "status": status}
                for (key, label, _), status in zip(STAGES, self.stage_statuses)
            ],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


_jobs: dict[str, AssessmentJob] = {}
_lock = threading.Lock()


def start_job(typhoon_id: int, bulletin_id: int, source: str) -> tuple[AssessmentJob, bool]:
    """Registers a run, or returns the one already running for this typhoon
    (created=False) -- two concurrent runs would race on the same rows."""
    with _lock:
        for job in _jobs.values():
            if job.typhoon_id == typhoon_id and job.status == "processing":
                return job, False
        job = AssessmentJob(
            job_id=str(uuid.uuid4()), typhoon_id=typhoon_id, bulletin_id=bulletin_id,
            source=source, started_at=datetime.now(timezone.utc),
        )
        _jobs[job.job_id] = job
        return job, True


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.to_dict() if job else None


def latest_job_for_typhoon(typhoon_id: int) -> dict[str, Any] | None:
    """The running job for this typhoon, else its most recent finished one."""
    with _lock:
        jobs = [j for j in _jobs.values() if j.typhoon_id == typhoon_id]
        if not jobs:
            return None
        running = [j for j in jobs if j.status == "processing"]
        job = running[0] if running else max(jobs, key=lambda j: j.started_at)
        return job.to_dict()


class JobProgress:
    """The progress callback AssessmentService reports into. Stages may only
    move forward; starting one closes the previous stage as completed."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def stage(self, key: str, total: int = 0) -> None:
        index = _STAGE_INDEX[key]
        with _lock:
            job = _jobs[self.job_id]
            current = job.current_stage_index()
            if current is not None and current > index:
                raise RuntimeError(f"Assessment stage {key} started after a later stage")
            for i in range(index):
                if job.stage_statuses[i] != "completed":
                    job.stage_statuses[i] = "completed"
            job.stage_statuses[index] = "processing"
            job.stage_processed = 0
            job.stage_total = total

    def advance(self, processed: int, total: int | None = None) -> None:
        with _lock:
            job = _jobs[self.job_id]
            if total is not None:
                job.stage_total = total
            job.stage_processed = processed

    def done(self, result: dict[str, Any]) -> None:
        with _lock:
            job = _jobs[self.job_id]
            job.stage_statuses = ["completed"] * len(STAGES)
            job.stage_processed = job.stage_total
            job.status = "done"
            job.result = result
            job.finished_at = datetime.now(timezone.utc)

    def fail(self, error: str) -> None:
        with _lock:
            job = _jobs[self.job_id]
            current = job.current_stage_index()
            job.stage_statuses[current if current is not None else 0] = "failed"
            job.status = "error"
            job.error = error
            job.finished_at = datetime.now(timezone.utc)


class NullProgress:
    """For callers that don't track progress (tests, scripts)."""

    def stage(self, key: str, total: int = 0) -> None:
        pass

    def advance(self, processed: int, total: int | None = None) -> None:
        pass
