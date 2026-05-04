import json
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
    STAGE_TO_ARTIFACTS: dict[StageName, tuple[str, ...]] = {
        "x-fetch": ("01-source.md", "metadata.json"),
        "translate": ("02-translation.md",),
        "review": ("03-reviewed.md",),
        "route": ("04-route.json",),
        "light-polish": ("05-polished.md",),
        "wechat-rewrite": ("06-rewritten.md",),
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
            "06-rewritten.md",
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
    ALLOWED_STATUS_TRANSITIONS = {
        "pending": frozenset({"running"}),
        "running": frozenset({"running", "succeeded", "failed"}),
        "succeeded": frozenset(),
        "failed": frozenset(),
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

        if status in {"succeeded", "failed"} and record.finished_at is None:
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()

        updated = JobRecord.model_validate(
            record.model_dump(mode="python") | updates
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
        return JobRecord.model_validate(payload)

    def list_jobs(self, *, limit: int | None = None) -> list[JobRecord]:
        query = "SELECT payload FROM jobs ORDER BY created_at DESC"
        params: tuple[int, ...] | tuple[()] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self._connect_db() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            JobRecord.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def delete_job(self, job_id: str) -> None:
        record = self.read_job(job_id)
        claim_path = self._run_claim_file(job_id)
        if claim_path.exists():
            claim = self._read_run_claim(claim_path)
            if self._run_claim_is_stale(claim_path=claim_path, claim=claim):
                claim_path.unlink(missing_ok=True)
            else:
                raise ValueError(f"Job {job_id} is scheduled or running and cannot be deleted")

        if record.status == "running":
            raise ValueError(f"Job {job_id} is scheduled or running and cannot be deleted")

        shutil.rmtree(self._job_dir(job_id))
        with self._connect_db() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

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
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)"
            )

    def _bootstrap_index_from_filesystem(self) -> None:
        for job_dir in sorted(self._root_dir.iterdir()):
            if not job_dir.is_dir():
                continue

            job_file = job_dir / "job.json"
            if not job_file.is_file():
                continue

            try:
                payload = json.loads(job_file.read_text(encoding="utf-8"))
                record = JobRecord.model_validate(payload)
            except (json.JSONDecodeError, ValueError):
                continue

            self._upsert_job_index(record)

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
