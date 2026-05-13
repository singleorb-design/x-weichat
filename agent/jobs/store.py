import json
import re
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
import uuid
from typing import Any

from agent.models.schemas import (
    JobRecord,
    JobStatus,
    StageError,
    StageModelInfo,
    StageName,
    StageProbeResult,
    StageProbeStatus,
)


class JobStore:
    RUN_CLAIM_TTL = timedelta(minutes=5)
    LEGACY_STAGE_ALIASES: dict[str, StageName] = {"wechat-rewrite": "light-polish"}
    LEGACY_STAGE_FIELDS = (
        "stage_models",
        "prompt_versions",
        "stage_durations",
        "stage_errors",
        "stage_probes",
    )

    # Trash design:
    # - Soft-delete in SQLite via `jobs.trashed_at` so list queries can exclude trashed jobs.
    # - Move the job workspace directory under `<artifacts_root>/.trash/<job_id>` for restore.
    # - Keep a tiny marker file (`.trashed_at`) inside the trashed directory so filesystem-only
    #   cleanup can still reason about age even if the DB entry becomes inconsistent.
    TRASH_RETENTION = timedelta(days=1)
    TRASH_DIRNAME = ".trash"
    TRASH_MARKER_FILENAME = ".trashed_at"
    STAGE_TO_ARTIFACTS: dict[StageName, tuple[str, ...]] = {
        "x-fetch": ("01-source.md", "metadata.json"),
        "translate": ("02-translation.md",),
        "review": ("03-reviewed.md",),
        "route": ("04-route.json",),
        "light-polish": ("05-polished.md",),
        "final-check": ("07-final-candidate.md", "08-final-check.json", "final_check_raw.txt"),
        "targeted-fix": ("09-final-fixed.md",),
        "final-output": (
            "final_check_after_fix.json",
            "10-final.md",
            "final_candidate_failed.md",
            "final_check_failed.json",
        ),
        "render-html": ("11-wechat.html",),
    }
    ALLOWED_ARTIFACTS = frozenset(
        {
            "01-source.md",
            "02-translation.md",
            "03-reviewed.md",
            "04-route.json",
            "05-polished.md",
            "07-final-candidate.md",
            "08-final-check.json",
            "09-final-fixed.md",
            "final_check_after_fix.json",
            "10-final.md",
            "11-wechat.html",
            "metadata.json",
            "final_candidate_failed.md",
            "final_check_failed.json",
            "final_check_raw.txt",
        }
    )
    DISCOVERY_ALLOWED_ARTIFACTS = frozenset(
        {
            "request.json",
            "response-summary.json",
            "debug.log",
        }
    )
    ALLOWED_STATUS_TRANSITIONS = {
        "pending": frozenset({"running", "canceled"}),
        "running": frozenset({"running", "succeeded", "failed", "canceled"}),
        # 用户可手动将已完成任务标记为 published。
        "succeeded": frozenset({"published"}),
        "failed": frozenset(),
        "canceled": frozenset(),
        # 允许撤销发布（保留为 succeeded），方便误操作恢复。
        "published": frozenset({"succeeded"}),
    }

    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root_dir / "jobs.sqlite3"
        self._initialize_index()
        self._bootstrap_index_from_filesystem()

    def create_job(self, *, url: str) -> JobRecord:
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / "logs").mkdir()

        record = JobRecord(
            job_id=job_id,
            url=url,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._write_job(record)
        return record

    def write_artifact(self, *, job_id: str, relative_path: str, content: str) -> Path:
        if relative_path not in self.ALLOWED_ARTIFACTS:
            raise ValueError(f"Unsupported artifact path: {relative_path}")

        job_dir = self._job_dir(job_id)
        if not job_dir.is_dir():
            raise FileNotFoundError(f"Job not found: {job_id}")

        artifact_path = job_dir / relative_path
        artifact_path.write_text(content, encoding="utf-8")
        return artifact_path

    def write_public_asset(self, *, job_id: str, relative_path: str, content: str) -> Path:
        """写入可通过 artifacts API 访问的资产文件。

        资产文件必须位于某个以 `.assets` 结尾的目录下，例如：
        - `trace.assets/final-check/attempt-1.request.json`
        - `diff.assets/review/02-translation_vs_03-reviewed.patch`

        这类文件名数量不受 allowlist 约束，但目录名受限，且必须在 job 目录内。
        """

        job_dir = self.get_job_dir(job_id).resolve()
        requested_path = Path(relative_path)

        if requested_path.is_absolute() or any(part in {"", ".", ".."} for part in requested_path.parts):
            raise ValueError(f"Unsupported asset path: {relative_path}")

        if not requested_path.parts or not requested_path.parts[0].endswith(".assets"):
            raise ValueError(f"Unsupported asset path: {relative_path}")

        asset_path = (job_dir / requested_path).resolve()
        asset_path.relative_to(job_dir)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_text(content, encoding="utf-8")
        return asset_path

    def list_public_artifacts(self, *, job_id: str) -> list[str]:
        """列出当前 job 下可通过 `/artifacts/{path}` 访问的文件路径。"""

        job_dir = self.get_job_dir(job_id)
        results: list[str] = []

        for name in sorted(self.ALLOWED_ARTIFACTS):
            path = job_dir / name
            if path.is_file():
                results.append(name)

        for entry in sorted(job_dir.iterdir()):
            if not entry.is_dir() or not entry.name.endswith(".assets"):
                continue
            for file_path in sorted(entry.rglob("*")):
                if file_path.is_file():
                    results.append(str(file_path.relative_to(job_dir)).replace("\\", "/"))

        return results

    def get_job_dir(self, job_id: str) -> Path:
        job_dir = self._job_dir(job_id)
        if not job_dir.is_dir():
            raise FileNotFoundError(f"Job not found: {job_id}")
        return job_dir

    def resolve_public_artifact_path(self, *, job_id: str, relative_path: str) -> Path:
        job_dir = self.get_job_dir(job_id).resolve()
        requested_path = Path(relative_path)

        if requested_path.is_absolute() or any(part in {"", ".", ".."} for part in requested_path.parts):
            raise ValueError(f"Unsupported artifact path: {relative_path}")

        if len(requested_path.parts) == 1:
            if relative_path not in self.ALLOWED_ARTIFACTS:
                raise ValueError(f"Unsupported artifact path: {relative_path}")
        else:
            if not requested_path.parts[0].endswith(".assets"):
                raise ValueError(f"Unsupported artifact path: {relative_path}")

        artifact_path = (job_dir / requested_path).resolve()
        artifact_path.relative_to(job_dir)

        if not artifact_path.is_file():
            raise FileNotFoundError(
                f"Artifact not found for job {job_id}: {relative_path}"
            )

        return artifact_path

    def read_artifact(self, *, job_id: str, relative_path: str) -> str:
        if relative_path not in self.ALLOWED_ARTIFACTS:
            raise ValueError(f"Unsupported artifact path: {relative_path}")

        job_dir = self._job_dir(job_id)
        if not job_dir.is_dir():
            raise FileNotFoundError(f"Job not found: {job_id}")

        artifact_path = job_dir / relative_path
        if not artifact_path.is_file():
            raise FileNotFoundError(
                f"Artifact not found for job {job_id}: {relative_path}"
            )

        return artifact_path.read_text(encoding="utf-8")

    def append_log(self, *, job_id: str, filename: str, content: str) -> Path:
        if Path(filename).name != filename:
            raise ValueError("Log filename must not contain path separators")

        logs_dir = self._job_dir(job_id) / "logs"
        if not logs_dir.is_dir():
            raise FileNotFoundError(f"Job not found: {job_id}")

        log_path = logs_dir / filename
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return log_path

    def update_status(
        self,
        *,
        job_id: str,
        status: JobStatus,
        current_stage: str | None = None,
    ) -> JobRecord:
        record = self.read_job(job_id)
        allowed_next_statuses = self.ALLOWED_STATUS_TRANSITIONS[record.status]
        if status not in allowed_next_statuses:
            raise ValueError(
                f"Invalid status transition: {record.status} -> {status}"
            )

        updates: dict[str, JobStatus | str | None] = {
            "status": status,
        }

        if current_stage is not None or status == "running":
            updates["current_stage"] = current_stage

        if status == "running" and record.started_at is None:
            updates["started_at"] = datetime.now(timezone.utc).isoformat()

        if status in {"succeeded", "failed", "canceled", "published"} and record.finished_at is None:
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()

        updated = JobRecord.model_validate(
            record.model_dump(mode="python") | updates
        )
        self._write_job(updated)
        return updated

    def update_source_title(self, *, job_id: str, source_title: str | None) -> JobRecord:
        record = self.read_job(job_id)
        normalized = (source_title or "").strip() or None
        updated = JobRecord.model_validate(
            record.model_dump(mode="python") | {"source_title": normalized}
        )
        self._write_job(updated)
        return updated

    def update_stage_metadata(
        self,
        *,
        job_id: str,
        stage: StageName,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        duration: float | None = None,
        error: StageError | dict[str, Any] | None = None,
    ) -> JobRecord:
        if stage not in JobRecord.ALLOWED_STAGES:
            allowed = ", ".join(JobRecord.ALLOWED_STAGES)
            raise ValueError(f"stage must be one of: {allowed}")

        record = self.read_job(job_id)

        stage_models = dict(record.stage_models)
        prompt_versions = dict(record.prompt_versions)
        stage_durations = dict(record.stage_durations)
        stage_errors = dict(record.stage_errors)

        if provider is not None or model is not None:
            existing_stage_model = stage_models.get(stage)
            stage_models[stage] = StageModelInfo(
                provider=(
                    provider
                    if provider is not None
                    else existing_stage_model.provider if existing_stage_model is not None else ""
                ),
                model=(
                    model
                    if model is not None
                    else existing_stage_model.model if existing_stage_model is not None else ""
                ),
            )

        if prompt_version is not None:
            prompt_versions[stage] = prompt_version

        if duration is not None:
            stage_durations[stage] = duration

        if error is not None:
            existing_error = stage_errors.get(stage)
            existing_payload = (
                existing_error.model_dump(mode="python") if existing_error is not None else {}
            )
            incoming_payload = (
                error.model_dump(mode="python")
                if isinstance(error, StageError)
                else {key: value for key, value in error.items() if value is not None}
            )
            stage_errors[stage] = StageError.model_validate(
                existing_payload | incoming_payload
            )

        updated = JobRecord.model_validate(
            record.model_dump(mode="python")
            | {
                "stage_models": stage_models,
                "prompt_versions": prompt_versions,
                "stage_durations": stage_durations,
                "stage_errors": stage_errors,
            }
        )
        self._write_job(updated)
        return updated

    def update_stage_probe(
        self,
        *,
        job_id: str,
        stage: StageName,
        status: StageProbeStatus,
        message: str,
        checked_at: str | None = None,
    ) -> JobRecord:
        if stage not in JobRecord.ALLOWED_STAGES:
            allowed = ", ".join(JobRecord.ALLOWED_STAGES)
            raise ValueError(f"stage must be one of: {allowed}")

        record = self.read_job(job_id)
        stage_probes = dict(record.stage_probes)
        stage_probes[stage] = StageProbeResult(
            status=status,
            message=message,
            checked_at=checked_at or self._now().isoformat(),
        )

        updated = JobRecord.model_validate(
            record.model_dump(mode="python")
            | {
                "stage_probes": stage_probes,
            }
        )
        self._write_job(updated)
        return updated

    def reset_for_retry(
        self,
        *,
        job_id: str,
        stage: StageName,
        claim_token: str | None = None,
    ) -> JobRecord:
        if stage not in JobRecord.ALLOWED_STAGES:
            allowed = ", ".join(JobRecord.ALLOWED_STAGES)
            raise ValueError(f"stage must be one of: {allowed}")

        record = self.read_job(job_id)
        claim_path = self._run_claim_file(job_id)
        if claim_path.exists():
            claim = self._read_run_claim(claim_path)
            if self._run_claim_is_stale(claim_path=claim_path, claim=claim):
                claim_path.unlink(missing_ok=True)
            elif claim_token is not None and claim.get("token") == claim_token:
                pass
            else:
                raise ValueError(f"Job {job_id} is scheduled or running and cannot be retried")

        if record.status == "running":
            raise ValueError(f"Job {job_id} is scheduled or running and cannot be retried")

        stage_index = JobRecord.ALLOWED_STAGES.index(stage)
        stages_to_clear = set(JobRecord.ALLOWED_STAGES[stage_index:])
        job_dir = self._job_dir(job_id)
        for retry_stage in stages_to_clear:
            for artifact_name in self.STAGE_TO_ARTIFACTS[retry_stage]:
                (job_dir / artifact_name).unlink(missing_ok=True)

        updated = JobRecord.model_validate(
            record.model_dump(mode="python")
            | {
                "status": "pending",
                "current_stage": stage,
                "started_at": None,
                "finished_at": None,
                "stage_models": {
                    name: value
                    for name, value in record.stage_models.items()
                    if name not in stages_to_clear
                },
                "stage_probes": {
                    name: value
                    for name, value in record.stage_probes.items()
                    if name not in stages_to_clear
                },
                "prompt_versions": {
                    name: value
                    for name, value in record.prompt_versions.items()
                    if name not in stages_to_clear
                },
                "stage_durations": {
                    name: value
                    for name, value in record.stage_durations.items()
                    if name not in stages_to_clear
                },
                "stage_errors": {
                    name: value
                    for name, value in record.stage_errors.items()
                    if name not in stages_to_clear
                },
            }
        )
        self._write_job(updated)
        return updated

    def claim_execution(self, *, job_id: str) -> str:
        record = self.read_job(job_id)
        if record.status == "running":
            raise ValueError(f"Job {job_id} is scheduled or running and cannot be claimed")

        return self._create_run_claim(job_id=job_id)

    def claim_run(self, *, job_id: str) -> str:
        record = self.read_job(job_id)
        if record.status != "pending":
            raise ValueError(
                f"Job {job_id} must be pending before claim_run(); got status={record.status}"
            )

        return self._create_run_claim(job_id=job_id)

    def _create_run_claim(self, *, job_id: str) -> str:
        claim_path = self._run_claim_file(job_id)
        if claim_path.exists():
            existing_claim = self._read_run_claim(claim_path)
            if not self._run_claim_is_stale(claim_path=claim_path, claim=existing_claim):
                raise FileExistsError(f"Run claim already exists for job: {job_id}")
            try:
                claim_path.unlink()
            except FileNotFoundError as exc:
                raise FileExistsError(f"Run claim already exists for job: {job_id}") from exc

        claim_token = uuid.uuid4().hex
        claim_payload = {
            "token": claim_token,
            "claimed_at": self._now().isoformat(),
        }
        fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(claim_payload, handle)
        except Exception:
            if claim_path.exists():
                claim_path.unlink()
            raise

        return claim_token

    def verify_run_claim(self, *, job_id: str, claim_token: str) -> None:
        claim_path = self._run_claim_file(job_id)
        if not claim_path.is_file():
            raise FileNotFoundError(f"Run claim not found for job: {job_id}")

        saved_claim_token = self._read_run_claim(claim_path)["token"]
        if saved_claim_token != claim_token:
            raise ValueError(f"Run claim token does not match job: {job_id}")

    def consume_run_claim(self, *, job_id: str, claim_token: str) -> None:
        claim_path = self._run_claim_file(job_id)
        self.verify_run_claim(job_id=job_id, claim_token=claim_token)
        claim_path.unlink()

    def read_job(self, job_id: str) -> JobRecord:
        payload = json.loads(self._job_file(job_id).read_text(encoding="utf-8"))
        return self._parse_job_record(payload)

    def list_jobs(self, *, limit: int | None = None) -> list[JobRecord]:
        self._cleanup_expired_trash_best_effort()

        query = "SELECT payload FROM jobs WHERE trashed_at IS NULL ORDER BY created_at DESC"
        params: tuple[int, ...] | tuple[()] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self._connect_db() as conn:
            rows = conn.execute(query, params).fetchall()

        records: list[JobRecord] = []
        for row in rows:
            record = self._parse_job_record(json.loads(row["payload"]))
            if not (record.source_title or "").strip():
                # Backfill priority:
                # 1) final output title (10-final.md)
                # 2) x-fetch metadata.json title
                # 3) source markdown (01-source.md)
                title = self._extract_title_from_markdown_file(job_id=record.job_id, relative_path="10-final.md")

                # Legacy/partial jobs may have title stored only in `metadata.json`.
                try:
                    metadata_raw = self.read_artifact(job_id=record.job_id, relative_path="metadata.json")
                    metadata = json.loads(metadata_raw)
                    metadata_title = metadata.get("title") if isinstance(metadata, dict) else None
                except Exception:
                    metadata_title = None

                if not (isinstance(title, str) and title.strip()) and isinstance(metadata_title, str) and metadata_title.strip():
                    title = metadata_title

                if not (isinstance(title, str) and title.strip()):
                    title = self._extract_title_from_markdown_file(job_id=record.job_id, relative_path="01-source.md")

                if isinstance(title, str) and title.strip():
                    try:
                        record = self.update_source_title(job_id=record.job_id, source_title=title)
                    except Exception:
                        record = JobRecord.model_validate(
                            record.model_dump(mode="python")
                            | {"source_title": title.strip()}
                        )
            records.append(record)
        return records

    def _extract_title_from_markdown_file(self, *, job_id: str, relative_path: str) -> str | None:
        """Best-effort extract H1 from a markdown artifact.

        Notes:
        - Avoids reading large files in full.
        - Strips YAML frontmatter if present.
        """

        source_path = self._job_dir(job_id) / relative_path
        try:
            if not source_path.is_file():
                return None

            # Guard: very large sources are not worth scanning during list_jobs.
            if source_path.stat().st_size > 900_000:
                return None

            lines: list[str] = []
            with source_path.open("r", encoding="utf-8") as handle:
                for _ in range(300):
                    line = handle.readline()
                    if not line:
                        break
                    lines.append(line)
        except Exception:
            return None

        if not lines:
            return None

        # Strip YAML frontmatter.
        idx = 0
        if lines[0].lstrip().startswith("---"):
            idx = 1
            while idx < len(lines):
                if lines[idx].lstrip().startswith("---"):
                    idx += 1
                    break
                idx += 1

        body = "".join(lines[idx:])
        # Final output may demote H1 to H2; accept any heading level.
        match = re.search(r"^#{1,6}\s+(.+)$", body, re.MULTILINE)
        if not match:
            return None
        title = match.group(1).strip()
        return title or None

    def delete_job(self, job_id: str) -> None:
        """Move a job into trash (recoverable within `TRASH_RETENTION`)."""
        record = self.read_job(job_id)

        # Safety: a running/scheduled job may still be writing artifacts.
        claim_path = self._run_claim_file(job_id)
        if claim_path.exists():
            claim = self._read_run_claim(claim_path)
            if self._run_claim_is_stale(claim_path=claim_path, claim=claim):
                claim_path.unlink(missing_ok=True)
            else:
                raise ValueError(f"Job {job_id} is scheduled or running and cannot be deleted")

        if record.status == "running":
            raise ValueError(f"Job {job_id} is scheduled or running and cannot be deleted")

        trashed_at = self._now().isoformat()
        src_dir = self._job_dir(job_id)
        dst_dir = self._trashed_job_dir(job_id)
        self._trash_root_dir().mkdir(parents=True, exist_ok=True)
        if dst_dir.exists():
            raise FileExistsError(f"Trash directory already exists for job: {job_id}")

        src_dir.replace(dst_dir)
        (dst_dir / self.TRASH_MARKER_FILENAME).write_text(trashed_at + "\n", encoding="utf-8")

        with self._connect_db() as conn:
            conn.execute(
                "UPDATE jobs SET trashed_at = ? WHERE job_id = ?",
                (trashed_at, job_id),
            )

    def list_trashed_jobs(self, *, limit: int | None = None) -> list[JobRecord]:
        self._cleanup_expired_trash_best_effort()

        query = "SELECT payload FROM jobs WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC"
        params: tuple[int, ...] | tuple[()] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self._connect_db() as conn:
            rows = conn.execute(query, params).fetchall()

        records: list[JobRecord] = []
        for row in rows:
            record = self._parse_job_record(json.loads(row["payload"]))
            # If filesystem entry is missing, leave it out of the response and let cleanup handle it.
            if not self._trashed_job_dir(record.job_id).is_dir():
                continue
            records.append(record)
        return records

    def restore_job(self, job_id: str) -> JobRecord:
        """Restore a trashed job back to the active workspace."""
        self._cleanup_expired_trash_best_effort()

        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT payload, trashed_at FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()

        if not row:
            raise FileNotFoundError(f"Job not found: {job_id}")

        trashed_at = row["trashed_at"]
        if not isinstance(trashed_at, str) or not trashed_at:
            raise ValueError(f"Job {job_id} is not in trash")

        src_dir = self._trashed_job_dir(job_id)
        if not src_dir.is_dir():
            raise FileNotFoundError(f"Trashed job directory not found: {job_id}")

        dst_dir = self._job_dir(job_id)
        if dst_dir.exists():
            raise FileExistsError(f"Job directory already exists for job: {job_id}")

        src_dir.replace(dst_dir)
        (dst_dir / self.TRASH_MARKER_FILENAME).unlink(missing_ok=True)

        with self._connect_db() as conn:
            conn.execute(
                "UPDATE jobs SET trashed_at = NULL WHERE job_id = ?",
                (job_id,),
            )

        return self._parse_job_record(json.loads(row["payload"]))

    def cleanup_expired_trash(self) -> int:
        """Hard-delete jobs that have been in trash longer than `TRASH_RETENTION`.

        Returns:
            Number of deleted jobs.
        """
        now = self._now()
        removed = 0
        with self._connect_db() as conn:
            rows = conn.execute(
                "SELECT job_id, trashed_at FROM jobs WHERE trashed_at IS NOT NULL"
            ).fetchall()

            expired_job_ids: list[str] = []
            for row in rows:
                job_id = str(row["job_id"])
                trashed_at_raw = row["trashed_at"]
                if not isinstance(trashed_at_raw, str) or not trashed_at_raw:
                    continue
                try:
                    parsed = datetime.fromisoformat(trashed_at_raw)
                except ValueError:
                    parsed = None
                if parsed and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed and now - parsed > self.TRASH_RETENTION:
                    expired_job_ids.append(job_id)

            for job_id in expired_job_ids:
                try:
                    shutil.rmtree(self._trashed_job_dir(job_id), ignore_errors=True)
                finally:
                    conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                    removed += 1

        return removed

    def _cleanup_expired_trash_best_effort(self) -> None:
        try:
            self.cleanup_expired_trash()
        except Exception:
            # Best-effort cleanup: never fail the foreground request.
            return

    def _parse_job_record(self, payload: dict[str, Any]) -> JobRecord:
        return JobRecord.model_validate(self._sanitize_legacy_job_payload(payload))

    def _sanitize_legacy_job_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(payload)

        current_stage = sanitized.get("current_stage")
        if isinstance(current_stage, str) and current_stage in self.LEGACY_STAGE_ALIASES:
            sanitized["current_stage"] = self.LEGACY_STAGE_ALIASES[current_stage]

        for field_name in self.LEGACY_STAGE_FIELDS:
            value = sanitized.get(field_name)
            if not isinstance(value, dict):
                continue

            cleaned = {
                key: field_value
                for key, field_value in value.items()
                if key not in self.LEGACY_STAGE_ALIASES
            }
            if cleaned != value:
                sanitized[field_name] = cleaned

        return sanitized

    def _write_job(self, record: JobRecord) -> None:
        job_file = self._job_file(record.job_id)
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        fd, temp_path_raw = tempfile.mkstemp(
            dir=job_file.parent,
            prefix=f"{job_file.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_path_raw)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            temp_path.replace(job_file)
            self._upsert_job_index(record)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _connect_db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_index(self) -> None:
        with self._connect_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    trashed_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)"
            )
            self._ensure_job_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_trashed_at ON jobs(trashed_at)"
            )

            # --- X Discovery tables (auto discover high-quality X articles) ---
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x_discovery_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    trigger TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_x_discovery_runs_created_at ON x_discovery_runs(created_at DESC)"
            )
            self._ensure_x_discovery_run_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x_discovery_items (
                    run_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    likes INTEGER,
                    tweet_text TEXT NOT NULL DEFAULT '',
                    score REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    already_seen INTEGER NOT NULL DEFAULT 0,
                    already_enqueued INTEGER NOT NULL DEFAULT 0,
                    job_id TEXT,
                    PRIMARY KEY (run_id, canonical_url)
                )
                """
            )
            self._ensure_x_discovery_item_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_x_discovery_items_canonical_url ON x_discovery_items(canonical_url)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x_discovery_seen (
                    canonical_url TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x_discovery_enqueued (
                    canonical_url TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_x_discovery_enqueued_job_id ON x_discovery_enqueued(job_id)"
            )

    def _ensure_x_discovery_run_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"]): str(row["type"] or "")
            for row in conn.execute("PRAGMA table_info(x_discovery_runs)").fetchall()
        }
        required_columns = {
            "status": "TEXT NOT NULL DEFAULT 'pending'",
            "current_phase": "TEXT",
            "progress_message": "TEXT",
            "progress_json": "TEXT NOT NULL DEFAULT '{}'",
            "error_message": "TEXT",
        }
        for column_name, definition in required_columns.items():
            if column_name in columns:
                continue
            conn.execute(
                f"ALTER TABLE x_discovery_runs ADD COLUMN {column_name} {definition}"
            )

    def _ensure_x_discovery_item_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"]): str(row["type"] or "")
            for row in conn.execute("PRAGMA table_info(x_discovery_items)").fetchall()
        }
        required_columns = {
            "already_seen": "INTEGER NOT NULL DEFAULT 0",
            "already_enqueued": "INTEGER NOT NULL DEFAULT 0",
            "job_id": "TEXT",
        }
        for column_name, definition in required_columns.items():
            if column_name in columns:
                continue
            conn.execute(
                f"ALTER TABLE x_discovery_items ADD COLUMN {column_name} {definition}"
            )

    # --- X Discovery public methods ---

    def create_x_discovery_run(self, *, trigger: str, request_payload: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        now = self._now().isoformat()
        self._discovery_dir(run_id).mkdir(parents=True, exist_ok=False)
        with self._connect_db() as conn:
            conn.execute(
                """
                INSERT INTO x_discovery_runs (
                    run_id,
                    created_at,
                    finished_at,
                    trigger,
                    request_json,
                    result_json,
                    status,
                    current_phase,
                    progress_message,
                    progress_json,
                    error_message
                )
                VALUES (?, ?, NULL, ?, ?, '{}', 'pending', NULL, NULL, '{}', NULL)
                """,
                (run_id, now, trigger, json.dumps(request_payload, ensure_ascii=False)),
            )
        return run_id

    def get_x_discovery_run(self, *, run_id: str) -> dict[str, Any] | None:
        with self._connect_db() as conn:
            row = conn.execute(
                """
                SELECT
                    run_id,
                    created_at,
                    finished_at,
                    trigger,
                    request_json,
                    result_json,
                    status,
                    current_phase,
                    progress_message,
                    progress_json,
                    error_message
                FROM x_discovery_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
            "trigger": row["trigger"],
            "request_json": json.loads(row["request_json"] or "{}"),
            "result_json": json.loads(row["result_json"] or "{}"),
            "status": row["status"] or "pending",
            "current_phase": row["current_phase"],
            "progress_message": row["progress_message"],
            "progress_json": json.loads(row["progress_json"] or "{}"),
            "error_message": row["error_message"],
        }

    def update_x_discovery_run(
        self,
        *,
        run_id: str,
        status: str,
        current_phase: str | None = None,
        progress_message: str | None = None,
        progress_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        with self._connect_db() as conn:
            conn.execute(
                """
                UPDATE x_discovery_runs
                SET status = ?,
                    current_phase = ?,
                    progress_message = ?,
                    progress_json = ?,
                    error_message = ?,
                    result_json = COALESCE(?, result_json)
                WHERE run_id = ?
                """,
                (
                    status,
                    current_phase,
                    progress_message,
                    json.dumps(progress_payload or {}, ensure_ascii=False),
                    error_message,
                    json.dumps(result_payload, ensure_ascii=False)
                    if result_payload is not None
                    else None,
                    run_id,
                ),
            )

    def finish_x_discovery_run(
        self,
        *,
        run_id: str,
        result_payload: dict[str, Any],
        status: str = "succeeded",
        current_phase: str | None = "completed",
        progress_message: str | None = None,
        progress_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        now = self._now().isoformat()
        with self._connect_db() as conn:
            conn.execute(
                """
                UPDATE x_discovery_runs
                SET finished_at = ?,
                    result_json = ?,
                    status = ?,
                    current_phase = ?,
                    progress_message = ?,
                    progress_json = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    json.dumps(result_payload, ensure_ascii=False),
                    status,
                    current_phase,
                    progress_message,
                    json.dumps(progress_payload or {}, ensure_ascii=False),
                    error_message,
                    run_id,
                ),
            )

    def write_x_discovery_artifact(self, *, run_id: str, relative_path: str, content: str) -> Path:
        if relative_path not in self.DISCOVERY_ALLOWED_ARTIFACTS:
            raise ValueError(f"Unsupported discovery artifact path: {relative_path}")
        artifact_path = self.get_x_discovery_dir(run_id) / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")
        return artifact_path

    def list_x_discovery_artifacts(self, *, run_id: str) -> list[str]:
        discovery_dir = self.get_x_discovery_dir(run_id)
        results: list[str] = []
        for name in sorted(self.DISCOVERY_ALLOWED_ARTIFACTS):
            path = discovery_dir / name
            if path.is_file():
                results.append(name)
        return results

    def resolve_x_discovery_artifact_path(self, *, run_id: str, relative_path: str) -> Path:
        if relative_path not in self.DISCOVERY_ALLOWED_ARTIFACTS:
            raise ValueError(f"Unsupported discovery artifact path: {relative_path}")
        file_path = self.get_x_discovery_dir(run_id) / relative_path
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Artifact not found for discovery run {run_id}: {relative_path}"
            )
        return file_path

    def get_x_discovery_dir(self, run_id: str) -> Path:
        discovery_dir = self._discovery_dir(run_id)
        if not discovery_dir.is_dir():
            raise FileNotFoundError(f"Discovery run not found: {run_id}")
        return discovery_dir

    def save_x_discovery_items(self, *, run_id: str, items: list[dict[str, Any]]) -> None:
        """保存一次 discovery 运行发现到的候选项。

        每个 item 至少包含：canonical_url、original_url、source_kind、source_value。
        likes/tweet_text/score/reason 为可选字段。
        """

        now = self._now().isoformat()
        with self._connect_db() as conn:
            for item in items:
                canonical_url = str(item.get("canonical_url") or "").strip()
                original_url = str(item.get("original_url") or canonical_url).strip()
                if not canonical_url or not original_url:
                    continue
                conn.execute(
                    """
                    INSERT INTO x_discovery_items (
                        run_id,
                        canonical_url,
                        original_url,
                        discovered_at,
                        source_kind,
                        source_value,
                        likes,
                        tweet_text,
                        score,
                        reason,
                        already_seen,
                        already_enqueued,
                        job_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, canonical_url) DO UPDATE SET
                        original_url = excluded.original_url,
                        discovered_at = excluded.discovered_at,
                        source_kind = excluded.source_kind,
                        source_value = excluded.source_value,
                        likes = excluded.likes,
                        tweet_text = excluded.tweet_text,
                        score = excluded.score,
                        reason = excluded.reason,
                        already_seen = excluded.already_seen,
                        already_enqueued = excluded.already_enqueued,
                        job_id = excluded.job_id
                    """,
                    (
                        run_id,
                        canonical_url,
                        original_url,
                        str(item.get("discovered_at") or now),
                        str(item.get("source_kind") or ""),
                        str(item.get("source_value") or ""),
                        item.get("likes"),
                        str(item.get("tweet_text") or ""),
                        float(item.get("score") or 0),
                        str(item.get("reason") or ""),
                        1 if item.get("already_seen") else 0,
                        1 if item.get("already_enqueued") else 0,
                        str(item.get("job_id")) if item.get("job_id") else None,
                    ),
                )

    def upsert_x_discovery_seen(self, *, canonical_url: str) -> dict[str, Any]:
        url = canonical_url.strip()
        now = self._now().isoformat()
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT canonical_url, first_seen_at, last_seen_at, seen_count FROM x_discovery_seen WHERE canonical_url = ?",
                (url,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO x_discovery_seen (canonical_url, first_seen_at, last_seen_at, seen_count)
                    VALUES (?, ?, ?, 1)
                    """,
                    (url, now, now),
                )
                return {"canonical_url": url, "first_seen_at": now, "last_seen_at": now, "seen_count": 1}

            seen_count = int(row["seen_count"] or 0) + 1
            conn.execute(
                """
                UPDATE x_discovery_seen
                SET last_seen_at = ?, seen_count = ?
                WHERE canonical_url = ?
                """,
                (now, seen_count, url),
            )
            return {
                "canonical_url": url,
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": now,
                "seen_count": seen_count,
            }

    def get_x_discovery_seen(self, *, canonical_url: str) -> dict[str, Any] | None:
        url = canonical_url.strip()
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT canonical_url, first_seen_at, last_seen_at, seen_count FROM x_discovery_seen WHERE canonical_url = ?",
                (url,),
            ).fetchone()
            if row is None:
                return None
            return {
                "canonical_url": row["canonical_url"],
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "seen_count": int(row["seen_count"]),
            }

    def get_x_discovery_enqueued_job(self, *, canonical_url: str) -> str | None:
        url = canonical_url.strip()
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT job_id FROM x_discovery_enqueued WHERE canonical_url = ?",
                (url,),
            ).fetchone()
            return str(row["job_id"]) if row is not None else None

    def record_x_discovery_enqueued(self, *, canonical_url: str, job_id: str) -> None:
        url = canonical_url.strip()
        now = self._now().isoformat()
        with self._connect_db() as conn:
            conn.execute(
                """
                INSERT INTO x_discovery_enqueued (canonical_url, job_id, enqueued_at)
                VALUES (?, ?, ?)
                ON CONFLICT(canonical_url) DO NOTHING
                """,
                (url, job_id, now),
            )

    def list_x_discovery_items(self, *, run_id: str) -> list[dict[str, Any]]:
        with self._connect_db() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    canonical_url,
                    original_url,
                    discovered_at,
                    source_kind,
                    source_value,
                    likes,
                    tweet_text,
                    score,
                    reason,
                    already_seen,
                    already_enqueued,
                    job_id
                FROM x_discovery_items
                WHERE run_id = ?
                ORDER BY score DESC, discovered_at DESC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "canonical_url": row["canonical_url"],
                "original_url": row["original_url"],
                "discovered_at": row["discovered_at"],
                "source_kind": row["source_kind"],
                "source_value": row["source_value"],
                "likes": row["likes"],
                "tweet_text": row["tweet_text"],
                "score": float(row["score"]),
                "reason": row["reason"],
                "already_seen": bool(row["already_seen"]),
                "already_enqueued": bool(row["already_enqueued"]),
                "job_id": row["job_id"],
            }
            for row in rows
        ]

    def _bootstrap_index_from_filesystem(self) -> None:
        for job_dir in sorted(self._root_dir.iterdir()):
            if not job_dir.is_dir():
                continue

            if job_dir.name == self.TRASH_DIRNAME:
                continue

            job_file = job_dir / "job.json"
            if not job_file.is_file():
                continue

            try:
                payload = json.loads(job_file.read_text(encoding="utf-8"))
                record = self._parse_job_record(payload)
            except (json.JSONDecodeError, ValueError):
                continue

            self._upsert_job_index(record)

        trash_root = self._trash_root_dir()
        if trash_root.is_dir():
            for job_dir in sorted(trash_root.iterdir()):
                if not job_dir.is_dir():
                    continue

                job_file = job_dir / "job.json"
                if not job_file.is_file():
                    continue

                try:
                    payload = json.loads(job_file.read_text(encoding="utf-8"))
                    record = self._parse_job_record(payload)
                except (json.JSONDecodeError, ValueError):
                    continue

                marker_path = job_dir / self.TRASH_MARKER_FILENAME
                if marker_path.is_file():
                    trashed_at = marker_path.read_text(encoding="utf-8").strip()
                else:
                    trashed_at = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc).isoformat()

                self._upsert_job_index(record)
                with self._connect_db() as conn:
                    conn.execute(
                        "UPDATE jobs SET trashed_at = ? WHERE job_id = ?",
                        (trashed_at, record.job_id),
                    )


    def _upsert_job_index(self, record: JobRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with self._connect_db() as conn:
            conn.execute(
                """
                INSERT INTO jobs (job_id, created_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    payload = excluded.payload
                """,
                (record.job_id, record.created_at, payload),
            )

    def _job_dir(self, job_id: str) -> Path:
        return self._root_dir / job_id

    def _trash_root_dir(self) -> Path:
        return self._root_dir / self.TRASH_DIRNAME

    def _trashed_job_dir(self, job_id: str) -> Path:
        return self._trash_root_dir() / job_id

    def _discovery_dir(self, run_id: str) -> Path:
        return self._root_dir / "discovery" / run_id

    def _ensure_job_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"]): str(row["type"] or "")
            for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        required_columns = {
            "trashed_at": "TEXT",
        }
        for column_name, definition in required_columns.items():
            if column_name in columns:
                continue
            conn.execute(
                f"ALTER TABLE jobs ADD COLUMN {column_name} {definition}"
            )

    def _job_file(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _run_claim_file(self, job_id: str) -> Path:
        return self._job_dir(job_id) / ".run-claim"

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _read_run_claim(self, claim_path: Path) -> dict[str, str]:
        raw = claim_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"token": raw, "claimed_at": ""}

        if isinstance(payload, dict) and isinstance(payload.get("token"), str):
            claimed_at = payload.get("claimed_at")
            return {
                "token": payload["token"],
                "claimed_at": claimed_at if isinstance(claimed_at, str) else "",
            }

        raise ValueError(f"Run claim file is invalid: {claim_path}")

    def _run_claim_is_stale(self, *, claim_path: Path, claim: dict[str, str]) -> bool:
        claimed_at_raw = claim.get("claimed_at")
        if claimed_at_raw:
            try:
                claimed_at = datetime.fromisoformat(claimed_at_raw)
            except ValueError:
                claimed_at = datetime.fromtimestamp(claim_path.stat().st_mtime, tz=timezone.utc)
        else:
            claimed_at = datetime.fromtimestamp(claim_path.stat().st_mtime, tz=timezone.utc)

        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)

        return self._now() - claimed_at > self.RUN_CLAIM_TTL
