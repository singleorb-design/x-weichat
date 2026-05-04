from __future__ import annotations

from time import perf_counter

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.models.schemas import JobRecord, StageError, StageModelInfo
from agent.stages.base import StageContext
from agent.stages.render_html import run_render_html
from agent.stages.review import run_review
from agent.stages.translate import run_translate
from agent.stages.wechat_rewrite import run_wechat_rewrite
from agent.stages.x_fetch import run_x_fetch


class PipelineRunner:
    STAGE_ORDER = JobRecord.ALLOWED_STAGES
    STAGE_MODEL_MARKERS = {
        "x-fetch": {"provider": "builtin", "model": "local:x-fetch"},
        "render-html": {"provider": "builtin", "model": "local:render-html"},
    }
    STAGE_PROMPT_VERSIONS = {
        "translate": "translate_zh.txt",
        "review": "review_zh.txt",
        "wechat-rewrite": "wechat_rewrite_zh.txt",
    }

    def __init__(
        self,
        *,
        store: JobStore,
        gateway: ModelGateway | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.settings = settings

    def create_job(self, url: str) -> JobRecord:
        return self.store.create_job(url=url)

    def run(self, job_id: str, claim_token: str | None = None) -> JobRecord:
        if claim_token is None:
            claim_token = self.store.claim_run(job_id=job_id)

        self.store.verify_run_claim(job_id=job_id, claim_token=claim_token)
        job = self.store.read_job(job_id)
        if job.status != "pending":
            raise ValueError(
                f"Job {job_id} must be pending before run(); got status={job.status}"
            )

        first_stage = self.STAGE_ORDER[0]
        try:
            self.store.consume_run_claim(job_id=job_id, claim_token=claim_token)
        except Exception as exc:
            raise RuntimeError(
                "consume_run_claim failed before starting "
                f"stage {first_stage} for job {job_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self.store.update_status(
            job_id=job_id,
            status="running",
            current_stage=first_stage,
        )

        context = StageContext(
            job_id=job.job_id,
            url=job.url,
            storage_state=getattr(self.settings, "x_storage_state_path", None),
        )

        for index, stage in enumerate(self.STAGE_ORDER):
            if index > 0:
                self.store.update_status(
                    job_id=job_id,
                    status="running",
                    current_stage=stage,
                )

            started_at = perf_counter()
            try:
                self._run_stage(stage=stage, context=context)
                self._record_stage_success(
                    job_id=job_id,
                    stage=stage,
                    duration=perf_counter() - started_at,
                )
            except Exception as exc:
                return self._fail_job(
                    job_id=job_id,
                    stage=stage,
                    exc=exc,
                    duration=perf_counter() - started_at,
                )

        return self.store.update_status(
            job_id=job_id,
            status="succeeded",
            current_stage=self.STAGE_ORDER[-1],
        )

    def _fail_job(
        self,
        *,
        job_id: str,
        stage: str,
        exc: Exception,
        duration: float | None = None,
    ) -> JobRecord:
        self._record_stage_failure(job_id=job_id, stage=stage, exc=exc, duration=duration)
        return self.store.update_status(
            job_id=job_id,
            status="failed",
            current_stage=stage,
        )

    def _record_stage_success(self, *, job_id: str, stage: str, duration: float) -> None:
        stage_model = self._stage_model_metadata(stage)
        self.store.update_stage_metadata(
            job_id=job_id,
            stage=stage,
            provider=stage_model.provider,
            model=stage_model.model,
            prompt_version=self.STAGE_PROMPT_VERSIONS.get(stage),
            duration=duration,
        )

    def _record_stage_failure(
        self,
        *,
        job_id: str,
        stage: str,
        exc: Exception,
        duration: float | None = None,
    ) -> None:
        stage_model = self._stage_model_metadata(stage)
        try:
            self.store.update_stage_metadata(
                job_id=job_id,
                stage=stage,
                provider=stage_model.provider,
                model=stage_model.model,
                prompt_version=self.STAGE_PROMPT_VERSIONS.get(stage),
                duration=duration,
                error=self._build_stage_error(exc),
            )
        except Exception:
            pass

        try:
            self.store.append_log(
                job_id=job_id,
                filename="pipeline.log",
                content=f"{stage}: {type(exc).__name__}: {exc}\n",
            )
        except Exception:
            pass

    def _build_stage_error(self, exc: Exception) -> StageError:
        message = str(exc).strip() or type(exc).__name__

        if isinstance(exc, FileNotFoundError):
            return StageError(
                error_type=type(exc).__name__,
                message=message,
                retryable=False,
                suggestion="Verify required input artifacts and local dependencies exist before rerunning.",
            )

        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return StageError(
                error_type=type(exc).__name__,
                message=message,
                retryable=True,
                suggestion="Retry the job after checking local I/O, network connectivity, or dependent services.",
            )

        if isinstance(exc, ValueError):
            return StageError(
                error_type=type(exc).__name__,
                message=message,
                retryable=False,
                suggestion="Check stage inputs and configuration before rerunning.",
            )

        return StageError(
            error_type=type(exc).__name__,
            message=message,
            retryable=False,
            suggestion="Inspect pipeline.log and the stage inputs before rerunning.",
        )

    def _stage_model_metadata(self, stage: str) -> StageModelInfo:
        builtin_marker = self.STAGE_MODEL_MARKERS.get(stage)
        if builtin_marker is not None:
            return StageModelInfo.model_validate(builtin_marker)

        provider = getattr(self.settings, "provider", None) or "unknown"
        configured_models = getattr(self.settings, "stage_models", {})
        model = configured_models.get(stage) if isinstance(configured_models, dict) else None
        if model is None:
            model = f"unconfigured:{stage}"
        return StageModelInfo(provider=provider, model=model)

    def _run_stage(self, *, stage: str, context: StageContext) -> str:
        if stage == "x-fetch":
            return run_x_fetch(context, self.store)

        if stage == "translate":
            return run_translate(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "review":
            return run_review(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "wechat-rewrite":
            return run_wechat_rewrite(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "render-html":
            return run_render_html(context=context, store=self.store)

        raise ValueError(f"Unsupported stage: {stage}")
