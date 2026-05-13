import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.jobs.store import JobStore
from agent.models.schemas import JobRecord, StageError, StageModelInfo


def test_create_job_creates_run_directory_and_files(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)

    job = store.create_job(url="https://example.com/post")

    job_dir = tmp_path / job.job_id
    assert job_dir.is_dir()
    assert (job_dir / "logs").is_dir()
    assert (job_dir / "job.json").is_file()
    assert job.job_id
    assert job.url == "https://example.com/post"
    assert job.created_at
    assert job.status == "pending"
    assert job.current_stage is None
    assert job.started_at is None
    assert job.finished_at is None
    assert job.stage_models == {}
    assert job.prompt_versions == {}
    assert job.stage_durations == {}
    assert job.stage_errors == {}

    saved = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert saved["job_id"] == job.job_id
    assert saved["url"] == "https://example.com/post"
    assert saved["created_at"] == job.created_at
    assert saved["status"] == "pending"
    assert saved["current_stage"] is None
    assert saved["started_at"] is None
    assert saved["finished_at"] is None
    assert saved["stage_models"] == {}
    assert saved["prompt_versions"] == {}
    assert saved["stage_durations"] == {}
    assert saved["stage_errors"] == {}


def test_write_artifact_persists_content(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    artifact_path = store.write_artifact(
        job_id=job.job_id,
        relative_path="02-translation.md",
        content="# translated markdown\n",
    )

    expected_path = tmp_path / job.job_id / "02-translation.md"
    assert artifact_path == expected_path
    assert expected_path.is_file()
    assert expected_path.read_text(encoding="utf-8") == "# translated markdown\n"


def test_write_artifact_rejects_unsupported_name(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    with pytest.raises(ValueError, match="Unsupported artifact path"):
        store.write_artifact(
            job_id=job.job_id,
            relative_path="translate/output.md",
            content="# translated markdown\n",
        )


def test_write_artifact_requires_existing_job(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)

    with pytest.raises(FileNotFoundError):
        store.write_artifact(
            job_id="missing-job",
            relative_path="02-translation.md",
            content="# translated markdown\n",
        )


def test_write_artifact_rejects_job_json(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")
    original = (tmp_path / job.job_id / "job.json").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported artifact path"):
        store.write_artifact(
            job_id=job.job_id,
            relative_path="job.json",
            content='{"status": "failed"}\n',
        )

    assert (tmp_path / job.job_id / "job.json").read_text(encoding="utf-8") == original


def test_update_status_changes_status_and_current_stage(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    running = store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="translate",
    )

    assert running.status == "running"
    assert running.current_stage == "translate"
    assert running.started_at is not None
    assert running.finished_at is None

    updated = store.update_status(
        job_id=job.job_id,
        status="succeeded",
        current_stage="translate",
    )

    assert updated.status == "succeeded"
    assert updated.current_stage == "translate"
    assert updated.started_at == running.started_at
    assert updated.finished_at is not None

    reloaded = store.read_job(job.job_id)
    assert reloaded.status == "succeeded"
    assert reloaded.current_stage == "translate"
    assert reloaded.started_at == running.started_at
    assert reloaded.finished_at == updated.finished_at


def test_list_jobs_returns_recent_jobs_from_sqlite_index(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    older = store.create_job(url="https://x.com/alice/status/1")
    newer = store.create_job(url="https://x.com/hooeem/article/2050332284675362853")
    store.update_status(
        job_id=newer.job_id,
        status="running",
        current_stage="x-fetch",
    )

    jobs = store.list_jobs()

    assert [job.job_id for job in jobs] == [newer.job_id, older.job_id]
    assert jobs[0].status == "running"
    assert jobs[0].current_stage == "x-fetch"
    assert (tmp_path / "jobs.sqlite3").is_file()


def test_delete_job_moves_job_to_trash_and_hides_from_list(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="01-source.md",
        content="# source\n",
    )

    store.delete_job(job.job_id)

    assert not (tmp_path / job.job_id).exists()
    assert [item.job_id for item in store.list_jobs()] == []
    assert (tmp_path / ".trash" / job.job_id).is_dir()
    assert [item.job_id for item in store.list_trashed_jobs()] == [job.job_id]
    with pytest.raises(FileNotFoundError):
        store.read_job(job.job_id)


def test_delete_job_rejects_claimed_or_running_jobs(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    claimed_job = store.create_job(url="https://x.com/alice/status/1")
    running_job = store.create_job(url="https://x.com/bob/status/2")

    store.claim_run(job_id=claimed_job.job_id)
    store.update_status(
        job_id=running_job.job_id,
        status="running",
        current_stage="translate",
    )

    with pytest.raises(ValueError, match="scheduled or running"):
        store.delete_job(claimed_job.job_id)

    with pytest.raises(ValueError, match="scheduled or running"):
        store.delete_job(running_job.job_id)


def test_delete_job_allows_stale_claimed_pending_job(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/alice/status/1")
    claim_path = store._run_claim_file(job.job_id)
    claim_path.write_text(
        json.dumps(
            {
                "token": "stale-token",
                "claimed_at": (datetime.now(timezone.utc) - JobStore.RUN_CLAIM_TTL - timedelta(seconds=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    store.delete_job(job.job_id)

    assert not (tmp_path / job.job_id).exists()
    assert (tmp_path / ".trash" / job.job_id).is_dir()


def test_restore_job_moves_job_back_from_trash(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="01-source.md", content="# source\n")

    store.delete_job(job.job_id)

    restored = store.restore_job(job.job_id)

    assert restored.job_id == job.job_id
    assert (tmp_path / job.job_id).is_dir()
    assert not (tmp_path / ".trash" / job.job_id).exists()
    assert [item.job_id for item in store.list_jobs()] == [job.job_id]
    assert store.list_trashed_jobs() == []


def test_cleanup_expired_trash_removes_items_after_retention(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.delete_job(job.job_id)

    expired_at = (datetime.now(timezone.utc) - JobStore.TRASH_RETENTION - timedelta(seconds=1)).isoformat()
    with store._connect_db() as conn:
        conn.execute(
            "UPDATE jobs SET trashed_at = ? WHERE job_id = ?",
            (expired_at, job.job_id),
        )

    removed = store.cleanup_expired_trash()

    assert removed == 1
    assert not (tmp_path / ".trash" / job.job_id).exists()
    assert store.list_jobs() == []
    assert store.list_trashed_jobs() == []


def test_reset_for_retry_from_review_clears_tail_artifacts_and_metadata(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")

    for name in [
        "01-source.md",
        "02-translation.md",
        "03-reviewed.md",
        "10-final.md",
        "11-wechat.html",
    ]:
        store.write_artifact(job_id=job.job_id, relative_path=name, content=f"{name}\n")

    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_stage_metadata(
        job_id=job.job_id,
        stage="review",
        provider="qwen",
        model="qwen-mt-plus",
        prompt_version="review_zh.txt",
        duration=1.2,
        error={
            "error_type": "ValueError",
            "message": "review failed",
            "retryable": True,
            "suggestion": "retry review",
        },
    )
    store.update_stage_probe(
        job_id=job.job_id,
        stage="review",
        status="passed",
        message="OK",
        checked_at="2026-05-04T00:00:00Z",
    )
    store.update_stage_metadata(
        job_id=job.job_id,
        stage="render-html",
        provider="builtin",
        model="local:render-html",
        duration=2.3,
        error={
            "error_type": "RuntimeError",
            "message": "render failed",
            "retryable": True,
            "suggestion": "retry render-html",
        },
    )
    failed = store.update_status(
        job_id=job.job_id,
        status="failed",
        current_stage="render-html",
    )

    reset = store.reset_for_retry(job_id=job.job_id, stage="review")

    assert failed.started_at is not None
    assert failed.finished_at is not None
    assert reset.status == "pending"
    assert reset.current_stage == "review"
    assert reset.started_at is None
    assert reset.finished_at is None
    assert (tmp_path / job.job_id / "01-source.md").is_file()
    assert (tmp_path / job.job_id / "02-translation.md").is_file()
    assert not (tmp_path / job.job_id / "03-reviewed.md").exists()
    assert not (tmp_path / job.job_id / "10-final.md").exists()
    assert not (tmp_path / job.job_id / "11-wechat.html").exists()
    assert "review" not in reset.stage_models
    assert "review" not in reset.stage_probes
    assert "render-html" not in reset.stage_models
    assert "review" not in reset.prompt_versions
    assert "review" not in reset.stage_durations
    assert "render-html" not in reset.stage_durations
    assert "review" not in reset.stage_errors
    assert "render-html" not in reset.stage_errors


def test_update_stage_probe_persists_probe_result(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")

    updated = store.update_stage_probe(
        job_id=job.job_id,
        stage="review",
        status="passed",
        message="OK",
        checked_at="2026-05-04T12:00:00Z",
    )

    assert updated.stage_probes["review"].status == "passed"
    assert updated.stage_probes["review"].message == "OK"
    assert updated.stage_probes["review"].checked_at == "2026-05-04T12:00:00Z"

    reloaded = store.read_job(job.job_id)
    assert reloaded.stage_probes["review"].status == "passed"


def test_reset_for_retry_from_render_html_only_removes_html(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")

    for name in [
        "01-source.md",
        "02-translation.md",
        "03-reviewed.md",
        "10-final.md",
        "11-wechat.html",
    ]:
        store.write_artifact(job_id=job.job_id, relative_path=name, content=f"{name}\n")

    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="succeeded", current_stage="render-html")

    reset = store.reset_for_retry(job_id=job.job_id, stage="render-html")

    assert reset.status == "pending"
    assert reset.current_stage == "render-html"
    assert (tmp_path / job.job_id / "10-final.md").is_file()
    assert not (tmp_path / job.job_id / "11-wechat.html").exists()


def test_reset_for_retry_rejects_unknown_stage(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")

    with pytest.raises(ValueError, match="stage must be one of"):
        store.reset_for_retry(job_id=job.job_id, stage="invalid-stage")


def test_reset_for_retry_rejects_running_job(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")

    with pytest.raises(ValueError, match="scheduled or running"):
        store.reset_for_retry(job_id=job.job_id, stage="review")


def test_reset_for_retry_rejects_active_run_claim(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.claim_run(job_id=job.job_id)

    with pytest.raises(ValueError, match="scheduled or running"):
        store.reset_for_retry(job_id=job.job_id, stage="review")


def test_reset_for_retry_ignores_stale_run_claim(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    claim_path = store._run_claim_file(job.job_id)
    claim_path.write_text(
        json.dumps(
            {
                "token": "stale-token",
                "claimed_at": (datetime.now(timezone.utc) - JobStore.RUN_CLAIM_TTL - timedelta(seconds=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    reset = store.reset_for_retry(job_id=job.job_id, stage="review")

    assert reset.status == "pending"
    assert not claim_path.exists()


def test_update_status_sets_started_at_only_once_and_finished_at_on_failure(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    first_running = store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="x-fetch",
    )
    second_running = store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="translate",
    )
    failed = store.update_status(
        job_id=job.job_id,
        status="failed",
        current_stage="translate",
    )

    assert first_running.started_at is not None
    assert second_running.started_at == first_running.started_at
    assert second_running.finished_at is None
    assert failed.started_at == first_running.started_at
    assert failed.finished_at is not None


@pytest.mark.parametrize("terminal_status", ["succeeded", "failed"])
def test_terminal_status_update_preserves_current_stage_when_omitted(
    tmp_path: Path, terminal_status: str
) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    running = store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )

    terminal = store.update_status(
        job_id=job.job_id,
        status=terminal_status,
    )

    assert running.current_stage == "review"
    assert terminal.status == terminal_status
    assert terminal.current_stage == "review"

    reloaded = store.read_job(job.job_id)
    assert reloaded.current_stage == "review"


def test_update_stage_metadata_persists_and_round_trips(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    updated = store.update_stage_metadata(
        job_id=job.job_id,
        stage="review",
        provider="openai",
        model="gpt-4.1",
        prompt_version="review-v3",
        duration=12.5,
        error=StageError(
            error_type="ValueError",
            message="validation failed",
            retryable=False,
            suggestion="Check the review prompt input.",
        ),
    )

    assert updated.stage_models == {
        "review": StageModelInfo(provider="openai", model="gpt-4.1")
    }
    assert updated.prompt_versions == {"review": "review-v3"}
    assert updated.stage_durations == {"review": 12.5}
    assert updated.stage_errors == {
        "review": StageError(
            error_type="ValueError",
            message="validation failed",
            retryable=False,
            suggestion="Check the review prompt input.",
        )
    }

    reloaded = store.read_job(job.job_id)
    assert reloaded.stage_models == {
        "review": StageModelInfo(provider="openai", model="gpt-4.1")
    }
    assert reloaded.prompt_versions == {"review": "review-v3"}
    assert reloaded.stage_durations == {"review": 12.5}
    assert reloaded.stage_errors == {
        "review": StageError(
            error_type="ValueError",
            message="validation failed",
            retryable=False,
            suggestion="Check the review prompt input.",
        )
    }

    saved = json.loads((tmp_path / job.job_id / "job.json").read_text(encoding="utf-8"))
    assert saved["stage_models"] == {
        "review": {"provider": "openai", "model": "gpt-4.1"}
    }
    assert saved["prompt_versions"] == {"review": "review-v3"}
    assert saved["stage_durations"] == {"review": 12.5}
    assert saved["stage_errors"] == {
        "review": {
            "error_type": "ValueError",
            "message": "validation failed",
            "retryable": False,
            "suggestion": "Check the review prompt input.",
        }
    }


def test_update_stage_metadata_merges_structured_error_updates(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    store.update_stage_metadata(
        job_id=job.job_id,
        stage="translate",
        error={
            "error_type": "RuntimeError",
            "message": "initial failure",
            "retryable": True,
            "suggestion": "Retry later.",
        },
    )

    updated = store.update_stage_metadata(
        job_id=job.job_id,
        stage="translate",
        error={
            "suggestion": "Retry after checking upstream service health.",
        },
    )

    assert updated.stage_errors == {
        "translate": StageError(
            error_type="RuntimeError",
            message="initial failure",
            retryable=True,
            suggestion="Retry after checking upstream service health.",
        )
    }

    saved = json.loads((tmp_path / job.job_id / "job.json").read_text(encoding="utf-8"))
    assert saved["stage_errors"] == {
        "translate": {
            "error_type": "RuntimeError",
            "message": "initial failure",
            "retryable": True,
            "suggestion": "Retry after checking upstream service health.",
        }
    }


def test_update_stage_metadata_preserves_existing_model_on_partial_update(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    store.update_stage_metadata(
        job_id=job.job_id,
        stage="review",
        provider="openai",
        model="gpt-4.1",
    )

    updated = store.update_stage_metadata(
        job_id=job.job_id,
        stage="review",
        provider="azure-openai",
    )

    assert updated.stage_models == {
        "review": StageModelInfo(provider="azure-openai", model="gpt-4.1")
    }

    reloaded = store.read_job(job.job_id)
    assert reloaded.stage_models == {
        "review": StageModelInfo(provider="azure-openai", model="gpt-4.1")
    }

    saved = json.loads((tmp_path / job.job_id / "job.json").read_text(encoding="utf-8"))
    assert saved["stage_models"] == {
        "review": {"provider": "azure-openai", "model": "gpt-4.1"}
    }


def test_write_job_replaces_target_atomically_and_cleans_up_temp_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")
    job_dir = tmp_path / job.job_id
    job_file = job_dir / "job.json"
    original_replace = Path.replace
    replace_calls: list[tuple[Path, Path, bool]] = []

    def tracking_replace(self: Path, target: Path) -> Path:
        replace_calls.append((self, target, self.exists()))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)

    updated = store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="translate",
    )

    assert updated.status == "running"
    assert replace_calls
    temp_path, replaced_target, temp_existed_before_replace = replace_calls[-1]
    assert replaced_target == job_file
    assert temp_path != job_file
    assert temp_existed_before_replace is True
    assert not temp_path.exists()
    assert sorted(path.name for path in job_dir.iterdir()) == ["job.json", "logs"]
    assert store.read_job(job.job_id).status == "running"


def test_update_status_requires_running_stage(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    with pytest.raises(ValueError, match="running status requires a valid current_stage"):
        store.update_status(job_id=job.job_id, status="running", current_stage=None)


def test_update_status_rejects_unknown_stage(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    with pytest.raises(ValueError, match="current_stage must be one of"):
        store.update_status(job_id=job.job_id, status="running", current_stage="invalid-stage")


def test_update_status_rejects_pending_to_succeeded(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    with pytest.raises(ValueError, match="Invalid status transition"):
        store.update_status(job_id=job.job_id, status="succeeded", current_stage="translate")


def test_update_status_rejects_terminal_state_transition(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="translate",
    )
    store.update_status(
        job_id=job.job_id,
        status="failed",
        current_stage="translate",
    )

    with pytest.raises(ValueError, match="Invalid status transition"):
        store.update_status(
            job_id=job.job_id,
            status="running",
            current_stage="review",
        )


def test_verify_run_claim_accepts_matching_token_and_consume_clears_it(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")

    claim_token = store.claim_run(job_id=job.job_id)

    store.verify_run_claim(job_id=job.job_id, claim_token=claim_token)
    store.consume_run_claim(job_id=job.job_id, claim_token=claim_token)

    with pytest.raises(FileNotFoundError, match="Run claim not found"):
        store.verify_run_claim(job_id=job.job_id, claim_token=claim_token)


def test_claim_run_reclaims_stale_claim(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")
    stale_token = "stale-token"
    stale_timestamp = datetime.now(timezone.utc) - store.RUN_CLAIM_TTL - timedelta(seconds=1)

    store._run_claim_file(job.job_id).write_text(
        json.dumps(
            {
                "token": stale_token,
                "claimed_at": stale_timestamp.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    reclaimed_token = store.claim_run(job_id=job.job_id)

    assert reclaimed_token != stale_token
    store.verify_run_claim(job_id=job.job_id, claim_token=reclaimed_token)
    with pytest.raises(ValueError, match="Run claim token does not match"):
        store.verify_run_claim(job_id=job.job_id, claim_token=stale_token)


def test_claim_run_reclaim_race_surfaces_claim_conflict_not_missing_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://example.com/post")
    claim_path = store._run_claim_file(job.job_id)
    stale_timestamp = datetime.now(timezone.utc) - store.RUN_CLAIM_TTL - timedelta(seconds=1)

    claim_path.write_text(
        json.dumps(
            {
                "token": "stale-token",
                "claimed_at": stale_timestamp.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    original_unlink = Path.unlink

    def racing_unlink(self: Path, *args, **kwargs) -> None:
        if self == claim_path:
            original_unlink(self, *args, **kwargs)
            self.write_text(
                json.dumps(
                    {
                        "token": "winning-token",
                        "claimed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            raise FileNotFoundError("stale claim already unlinked by another claimant")

        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    with pytest.raises(FileExistsError, match="Run claim already exists"):
        store.claim_run(job_id=job.job_id)


def test_job_record_rejects_running_without_started_at() -> None:
    with pytest.raises(ValidationError, match="running status requires started_at and no finished_at"):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "running",
                "current_stage": "translate",
                "started_at": None,
                "finished_at": None,
            }
        )


def test_job_record_rejects_running_with_finished_at() -> None:
    with pytest.raises(ValidationError, match="running status requires started_at and no finished_at"):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "running",
                "current_stage": "translate",
                "started_at": "2026-01-01T00:01:00+00:00",
                "finished_at": "2026-01-01T00:02:00+00:00",
            }
        )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("stage_models", {"invalid-stage": {"provider": "openai", "model": "gpt-4.1"}}),
        ("prompt_versions", {"invalid-stage": "review-v1"}),
        ("stage_durations", {"invalid-stage": 1.5}),
        (
            "stage_errors",
            {
                "invalid-stage": {
                    "error_type": "RuntimeError",
                    "message": "boom",
                    "retryable": False,
                    "suggestion": "Inspect the failing stage.",
                }
            },
        ),
    ],
)
def test_job_record_rejects_invalid_stage_keys_in_metadata_maps(
    field_name: str, field_value: object
) -> None:
    payload = {
        "job_id": "job-1",
        "url": "https://example.com/post",
        "created_at": "2026-01-01T00:00:00+00:00",
        field_name: field_value,
    }

    with pytest.raises(ValidationError, match=rf"{field_name} keys must be drawn from ALLOWED_STAGES"):
        JobRecord.model_validate(payload)


def test_job_record_rejects_invalid_stage_models_inner_shape() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "stage_models": {
                    "review": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "temperature": "0.2",
                    }
                },
            }
        )


@pytest.mark.parametrize(
    "stage_models",
    [
        {"review": {"provider": "openai"}},
        {"review": {"model": "gpt-4.1"}},
        {"review": {"provider": "   ", "model": "gpt-4.1"}},
        {"review": {"provider": "openai", "model": "   "}},
    ],
)
def test_job_record_requires_complete_non_empty_stage_model_metadata(
    stage_models: dict[str, dict[str, str]]
) -> None:
    with pytest.raises(ValidationError):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "stage_models": stage_models,
            }
        )


def test_job_record_rejects_invalid_stage_errors_inner_shape() -> None:
    with pytest.raises(ValidationError, match="StageError text fields must not be empty"):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "stage_errors": {
                    "review": {
                        "error_type": "RuntimeError",
                        "message": "boom",
                        "retryable": False,
                        "suggestion": "   ",
                    }
                },
            }
        )


@pytest.mark.parametrize("status", ["succeeded", "failed", "published"])
def test_job_record_requires_started_and_finished_at_for_terminal_states(status: str) -> None:
    with pytest.raises(ValidationError, match="terminal status requires started_at and finished_at"):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "url": "https://example.com/post",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": status,
                "current_stage": "translate",
                "started_at": "2026-01-01T00:01:00+00:00",
                "finished_at": None,
            }
        )
