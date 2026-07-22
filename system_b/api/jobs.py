"""In-memory background jobs for the quota generate run (H2).

quota_run does live research + LLM calls, so it can take minutes — too long for
one HTTP request. `start_generate` runs it on a daemon thread and exposes a
status the UI polls for a progress indicator. Single-user, so a small in-memory
registry is enough (a restart loses history, which is fine — the cards persist
in Airtable regardless).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any


class Job:
    def __init__(self, emails: int, linkedin: int, pack: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "running"          # running | done | error
        self.emails = emails
        self.linkedin = linkedin
        self.pack = pack
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.summary: dict[str, Any] | None = None
        self.error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "emails_requested": self.emails,
            "linkedin_requested": self.linkedin,
            "pack": self.pack,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "error": self.error,
        }


JOBS: dict[str, Job] = {}


def start_generate(at: Any, *, emails: int, linkedin: int, pack: str) -> Job:
    """Kick off a quota run on a daemon thread; return the Job immediately."""
    job = Job(emails, linkedin, pack)
    JOBS[job.id] = job

    def _run() -> None:
        try:
            from datetime import date

            from system_b.sequence import quota_run

            # quota_run builds each row's per-niche inventory on demand.
            job.summary = quota_run(
                at, email_quota=emails, linkedin_quota=linkedin,
                pack_default=pack, today=date.today(),
            )
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — record, don't crash the server
            job.error = repr(exc)
            job.status = "error"
        finally:
            job.finished_at = time.time()

    threading.Thread(target=_run, daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def latest_job() -> Job | None:
    return max(JOBS.values(), key=lambda j: j.started_at, default=None)
