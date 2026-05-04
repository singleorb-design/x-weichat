from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.models.schemas import JobRecord, RetryMode, StageError, StageModelInfo, StageName
from agent.stages.base import StageContext
from agent.stages.final_check import run_final_check
from agent.stages.final_output import run_final_output
from agent.stages.light_polish import run_light_polish
from agent.stages.render_html import run_render_html
from agent.stages.review import run_review
from agent.stages.route import run_route
from agent.stages.targeted_fix import run_targeted_fix
from agent.stages.translate import run_translate
from agent.stages.wechat_rewrite import run_wechat_rewrite
from agent.stages.x_fetch import run_x_fetch


class PipelineRunner:
    STAGE_ORDER = JobRecord.ALLOWED_STAGES
    STAGE_LABELS = {
        "x-fetch": "原文抓取",
        "translate": "翻译",
        "review": "审阅",
        "route": "路由判断",
        "light-polish": "轻编辑",
        "wechat-rewrite": "强改写",
        "final-check": "终检",
        "targeted-fix": "定点修复",
        "final-output": "最终定稿",
        "render-html": "HTML 渲染",
    }
    STAGE_MODEL_MARKERS = {
        "x-fetch": {"provider": "builtin", "model": "local:x-fetch"},
        "final-output": {"provider": "builtin", "model": "local:final-output"},
        "render-html": {"provider": "builtin", "model": "local:render-html"},
    }
    STAGE_PROMPT_VERSIONS = {
        "translate": "translate_zh.txt",
        "review": "review_zh.txt",
        "route": "route_zh.txt",
        "light-polish": "light_polish_zh.txt",
        "wechat-rewrite": "wechat_rewrite_zh.txt",
        "final-check": "final_check_zh.txt",
        "targeted-fix": "targeted_fix_zh.txt",
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

        return self._execute_from_stage(
            job_id=job_id,
            start_stage=self.STAGE_ORDER[0],
            claim_token=claim_token,
        )

    def retry(
        self,
        job_id: str,
        *,
        stage: StageName,
        mode: RetryMode,
        claim_token: str | None = None,
    ) -> JobRecord:
        if claim_token is None:
            claim_token = self.store.claim_execution(job_id=job_id)

        self.store.verify_run_claim(job_id=job_id, claim_token=claim_token)
        job = self.store.read_job(job_id)

        try:
            self._validate_retry(job=job, stage=stage, mode=mode)
            self.store.reset_for_retry(
                job_id=job_id,
                stage=stage,
                claim_token=claim_token,
            )
        except Exception:
            self._discard_run_claim(job_id=job_id, claim_token=claim_token)
            raise

        return self._execute_from_stage(
            job_id=job_id,
            start_stage=stage,
            claim_token=claim_token,
        )

    def _validate_retry(self, *, job: JobRecord, stage: StageName, mode: RetryMode) -> None:
        if mode == "failed-stage":
            if job.status != "failed" or job.current_stage != stage:
                raise ValueError(
                    "failed-stage retry requires the requested stage to match the failed current_stage"
                )
            return

        if mode == "from-stage":
            if job.status == "pending":
                raise ValueError("from-stage retry job must not be pending")
            return

        raise ValueError(f"Unsupported retry mode: {mode}")

    def _discard_run_claim(self, *, job_id: str, claim_token: str) -> None:
        try:
            self.store.consume_run_claim(job_id=job_id, claim_token=claim_token)
        except Exception:
            pass

    def _execute_from_stage(
        self,
        *,
        job_id: str,
        start_stage: StageName,
        claim_token: str,
    ) -> JobRecord:
        first_stage = start_stage
        job = self.store.update_status(
            job_id=job_id,
            status="running",
            current_stage=first_stage,
        )

        try:
            self.store.consume_run_claim(job_id=job_id, claim_token=claim_token)
        except Exception as exc:
            self._discard_run_claim(job_id=job_id, claim_token=claim_token)
            try:
                self.store.update_status(
                    job_id=job_id,
                    status="failed",
                    current_stage=first_stage,
                )
            except Exception:
                pass
            raise RuntimeError(
                "consume_run_claim failed before starting "
                f"stage {first_stage} for job {job_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        context = StageContext(
            job_id=job.job_id,
            url=job.url,
            storage_state=getattr(self.settings, "x_storage_state_path", None),
        )

        start_index = self.STAGE_ORDER.index(start_stage)
        for index, stage in enumerate(self.STAGE_ORDER[start_index:]):
            if index > 0:
                self.store.update_status(
                    job_id=job_id,
                    status="running",
                    current_stage=stage,
                )

            started_at = perf_counter()
            try:
                self._probe_stage_model(job_id=job_id, stage=stage)
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
                error=self._build_stage_error(exc, stage=stage, model=stage_model.model),
            )
        except Exception:
            pass

        try:
            self.store.append_log(
                job_id=job_id,
                filename="pipeline.log",
                content=f"{stage}: {type(exc).__name__}: {self._describe_exception(exc)}\n",
            )
        except Exception:
            pass

    def _build_stage_error(
        self,
        exc: Exception,
        *,
        stage: str | None = None,
        model: str | None = None,
    ) -> StageError:
        """把底层异常归一成前端可展示的阶段错误。

        `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，
        也包含需要用户在排查网络/配置后手动重跑的错误；UI 会直接展示这一语义。
        """
        message = self._describe_exception(exc)
        error_type = type(exc).__name__

        if error_type in {"APIConnectionError", "APITimeoutError"}:
            return StageError(
                error_type=error_type,
                message=message,
                retryable=True,
                suggestion=self._connection_error_suggestion(stage=stage, model=model),
            )

        if error_type == "RateLimitError":
            if self._is_non_retryable_quota_error(message):
                return StageError(
                    error_type=error_type,
                    message=message,
                    retryable=False,
                    suggestion="模型额度已用尽或账户计费异常，请检查套餐、余额或 Billing 状态后再重试。",
                )
            if self._is_token_rate_quota_error(message):
                return StageError(
                    error_type=error_type,
                    message=message,
                    retryable=True,
                    suggestion="模型请求触发 Token 消耗限流；请等待约 1 分钟后重试，或缩短输入、拆分任务、降低并发，必要时在百炼控制台提升该模型的 TPM 限额。",
                )
            return StageError(
                error_type=error_type,
                message=message,
                retryable=True,
                suggestion="模型请求触发限流，请稍后重试或调整并发。",
            )

        if isinstance(exc, FileNotFoundError):
            return StageError(
                error_type=error_type,
                message=message,
                retryable=False,
                suggestion="Verify required input artifacts and local dependencies exist before rerunning.",
            )

        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return StageError(
                error_type=error_type,
                message=message,
                retryable=True,
                suggestion="Retry the job after checking local I/O, network connectivity, or dependent services.",
            )

        if isinstance(exc, ValueError):
            return StageError(
                error_type=error_type,
                message=message,
                retryable=False,
                suggestion="Check stage inputs and configuration before rerunning.",
            )

        return StageError(
            error_type=error_type,
            message=message,
            retryable=False,
            suggestion="Inspect pipeline.log and the stage inputs before rerunning.",
        )

    def _is_non_retryable_quota_error(self, message: str) -> bool:
        normalized = message.lower()
        quota_markers = (
            "commoditynotpurchased",
            "prepaidbilloverdue",
            "postpaidbilloverdue",
            "free allocated quota exceeded",
            "free quota",
            "欠费",
            "未订购",
            "未购买",
            "免费额度已到期",
            "免费额度已耗尽",
            "免费额度耗尽",
            "账单到期",
            "计费异常",
            "账户异常",
            "billing overdue",
        )
        return any(marker in normalized for marker in quota_markers)

    def _is_token_rate_quota_error(self, message: str) -> bool:
        normalized = message.lower()
        quota_markers = (
            "insufficient_quota",
            "allocated quota exceeded",
            "current quota",
            "token-limit",
            "tpm",
            "tps",
        )
        return any(marker in normalized for marker in quota_markers)

    def _connection_error_suggestion(self, *, stage: str | None, model: str | None) -> str:
        if (
            stage == "light-polish"
            and model is not None
            and model.strip()
            and not model.startswith("unconfigured:")
        ):
            stage_label = self.STAGE_LABELS.get(stage, stage)
            review_model = self._stage_model_metadata("review").model
            contrast_hint = (
                "翻译/审阅成功并不代表这一阶段的模型链路正常；"
                if review_model and review_model != model
                else ""
            )
            return (
                f"{stage_label}阶段当前使用模型 {model}。"
                f"{contrast_hint}请优先检查该模型的可用性、API Base、代理配置后重试。"
            )

        return "模型网关连接失败，可检查网络连通性、API Base、代理配置后重试。"

    def _probe_stage_model(self, *, job_id: str, stage: str) -> None:
        if stage not in self.STAGE_PROMPT_VERSIONS:
            return

        if self.gateway is None or not hasattr(self.gateway, "probe_model"):
            return

        stage_model = self._stage_model_metadata(stage)
        model = stage_model.model.strip()
        if not model or model.startswith("unconfigured:"):
            return

        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            probe_message = self.gateway.probe_model(model=model, stage=stage)
        except Exception as exc:
            self.store.update_stage_probe(
                job_id=job_id,
                stage=stage,
                status="failed",
                message=self._describe_exception(exc),
                checked_at=checked_at,
            )
            raise

        self.store.update_stage_probe(
            job_id=job_id,
            stage=stage,
            status="passed",
            message=probe_message.strip() or "OK",
            checked_at=checked_at,
        )

    def _describe_exception(self, exc: Exception) -> str:
        message = str(exc).strip() or type(exc).__name__
        cause = getattr(exc, "__cause__", None)
        if cause is None:
            return message

        cause_message = str(cause).strip() or type(cause).__name__
        cause_detail = f"{type(cause).__name__}: {cause_message}"
        if cause_detail in message:
            return message
        return f"{message} (caused by {cause_detail})"

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

        if stage == "route":
            return run_route(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "light-polish":
            return run_light_polish(
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

        if stage == "final-check":
            return run_final_check(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "targeted-fix":
            return run_targeted_fix(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "final-output":
            return run_final_output(
                context=context,
                store=self.store,
                gateway=self.gateway,
                settings=self.settings,
            )

        if stage == "render-html":
            return run_render_html(context=context, store=self.store)

        raise ValueError(f"Unsupported stage: {stage}")
