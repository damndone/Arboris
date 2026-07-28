from __future__ import annotations

from pathlib import Path

from workbench.domain_memory.review_scheduler import ReviewJobStore, ReviewScheduler
from workbench.domain_memory.scope import MemoryScope


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def test_review_scheduler_is_idempotent_and_recovers_running_job(tmp_path: Path) -> None:
    scheduler = ReviewScheduler(ReviewJobStore(tmp_path, SCOPE))
    first = scheduler.enqueue(target_kind="candidate", target_ref="candidate-1", idempotency_key="a" * 64, scheduled_at="2026-07-27T00:00:00Z")
    assert scheduler.enqueue(target_kind="candidate", target_ref="candidate-1", idempotency_key="a" * 64, scheduled_at="2026-07-27T00:01:00Z") == first
    running = scheduler.claim(first.job_id, expected_revision=1, lease_until="2026-07-27T00:05:00Z")
    recovered = scheduler.recover(running.job_id, expected_revision=running.revision)
    assert recovered.state == "queued"
    assert recovered.revision == 3
    completed = scheduler.claim(recovered.job_id, expected_revision=recovered.revision, lease_until="2026-07-27T00:10:00Z")
    completed = scheduler.complete(completed.job_id, expected_revision=completed.revision)
    assert completed.state == "completed"


def test_scheduler_does_not_run_background_work(tmp_path: Path) -> None:
    store = ReviewJobStore(tmp_path, SCOPE)
    scheduler = ReviewScheduler(store)
    job = scheduler.enqueue(target_kind="candidate", target_ref="candidate-1", idempotency_key="b" * 64, scheduled_at="2026-07-27T00:00:00Z")
    assert job.state == "queued"
    assert store.latest(job.job_id).state == "queued"
