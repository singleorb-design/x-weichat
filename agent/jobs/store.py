import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import uuid
from typing import Any

from agent.models.schemas import JobRecord, JobStatus, StageError, StageModelInfo


class JobStore:
    RUN_CLAIM_TTL = timedelta(minutes=5)
    ALLOWED_ARTIFACTS = frozenset(
        {
            "01-source.md",
            "02-translation.md",
            "03-reviewed.md",
            "04-wechat.md",
            "05-wechat.html",
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
        stage: str,
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

    def claim_run(self, *, job_id: str) -> str:
        record = self.read_job(job_id)
        if record.status != "pending":
            raise ValueError(
                f"Job {job_id} must be pending before claim_run(); got status={record.status}"
            )

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
        finally:
            if temp_path.exists():
                temp_path.unlink()

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
