from typing import ClassVar, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


JobStatus = Literal["pending", "running", "succeeded", "failed", "canceled", "published"]
StageName = Literal[
    "x-fetch",
    "translate",
    "review",
    "route",
    "light-polish",
    "final-check",
    "targeted-fix",
    "final-output",
    "render-html",
]
RetryMode = Literal["failed-stage", "from-stage"]
RouteDecisionName = Literal["PASS", "LIGHT_POLISH"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
StageProbeStatus = Literal["passed", "failed"]


class StageResult(BaseModel):
    stage: str
    status: Literal["success", "failure"]
    artifact_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "StageResult":
        if self.status == "success" and (self.error_type is not None or self.error_message is not None):
            raise ValueError("StageResult success status must not include error details.")

        if self.status == "failure" and (not self.error_type or not self.error_message):
            raise ValueError("StageResult failure status requires error_type and error_message.")

        return self


class StageError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_type: str
    message: str
    retryable: bool = False
    suggestion: str

    @field_validator("error_type", "message", "suggestion")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("StageError text fields must not be empty.")
        return normalized


class StageModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str

    @field_validator("provider", "model")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("StageModelInfo text fields must not be empty.")
        return normalized


class StageProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StageProbeStatus
    message: str
    checked_at: str

    @field_validator("message", "checked_at")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("StageProbeResult text fields must not be empty.")
        return normalized


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RouteDecisionName
    reason: str
    risk: RiskLevel
    recommended_next_prompt: RouteDecisionName

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("RouteDecision reason must not be empty.")
        return normalized


class FinalCheckIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    severity: RiskLevel
    detail: str
    fix_suggestion: str

    @field_validator("type", "detail", "fix_suggestion")
    @classmethod
    def validate_issue_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("FinalCheckIssue text fields must not be empty.")
        return normalized


class FinalCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_: bool = Field(alias="pass")
    risk: RiskLevel
    fix_required: bool
    issues: list[FinalCheckIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_issue_consistency(self) -> "FinalCheckResult":
        if self.pass_ and self.fix_required:
            raise ValueError("FinalCheckResult pass=true must not require fixes.")
        if self.pass_ and self.issues:
            raise ValueError("FinalCheckResult pass=true must not include issues.")
        if not self.pass_ and self.fix_required and not self.issues:
            raise ValueError("FinalCheckResult fix_required=true requires at least one issue.")
        return self


class JobRecord(BaseModel):
    ALLOWED_STAGES: ClassVar[tuple[StageName, ...]] = get_args(StageName)

    job_id: str
    url: str
    source_title: str | None = None
    created_at: str
    status: JobStatus = "pending"
    current_stage: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stage_models: dict[str, StageModelInfo] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    stage_durations: dict[str, float] = Field(default_factory=dict)
    stage_errors: dict[str, StageError] = Field(default_factory=dict)
    stage_probes: dict[str, StageProbeResult] = Field(default_factory=dict)

    @classmethod
    def _validate_stage_keys(cls, field_name: str, value: dict[str, object]) -> dict[str, object]:
        invalid_keys = sorted(set(value) - set(cls.ALLOWED_STAGES))
        if invalid_keys:
            allowed = ", ".join(cls.ALLOWED_STAGES)
            invalid = ", ".join(invalid_keys)
            raise ValueError(
                f"{field_name} keys must be drawn from ALLOWED_STAGES: {allowed}. Invalid keys: {invalid}"
            )
        return value

    @field_validator("stage_models")
    @classmethod
    def validate_stage_models(cls, value: dict[str, StageModelInfo]) -> dict[str, StageModelInfo]:
        cls._validate_stage_keys("stage_models", value)
        return value

    @field_validator("prompt_versions")
    @classmethod
    def validate_prompt_versions(cls, value: dict[str, str]) -> dict[str, str]:
        cls._validate_stage_keys("prompt_versions", value)
        return value

    @field_validator("stage_durations")
    @classmethod
    def validate_stage_durations(cls, value: dict[str, float]) -> dict[str, float]:
        cls._validate_stage_keys("stage_durations", value)
        return value

    @field_validator("stage_errors")
    @classmethod
    def validate_stage_errors(cls, value: dict[str, StageError]) -> dict[str, StageError]:
        cls._validate_stage_keys("stage_errors", value)
        return value

    @field_validator("stage_probes")
    @classmethod
    def validate_stage_probes(cls, value: dict[str, StageProbeResult]) -> dict[str, StageProbeResult]:
        cls._validate_stage_keys("stage_probes", value)
        return value

    @field_validator("current_stage")
    @classmethod
    def validate_current_stage(cls, value: str | None) -> str | None:
        if value is None:
            return value

        if value not in cls.ALLOWED_STAGES:
            allowed = ", ".join(cls.ALLOWED_STAGES)
            raise ValueError(f"current_stage must be one of: {allowed}")

        return value

    @model_validator(mode="after")
    def validate_running_stage(self) -> "JobRecord":
        if self.status == "running" and self.current_stage is None:
            raise ValueError("running status requires a valid current_stage")

        if self.status == "running" and (
            self.started_at is None or self.finished_at is not None
        ):
            raise ValueError("running status requires started_at and no finished_at")

        if self.status in {"succeeded", "failed", "published"} and (
            self.started_at is None or self.finished_at is None
        ):
            raise ValueError("terminal status requires started_at and finished_at")

        # canceled 允许两种情况：
        # - 运行中被用户手动停止：started_at 与 finished_at 都会有
        # - pending 阶段被取消：started_at 可能为空，但仍应有 finished_at
        if self.status == "canceled" and self.finished_at is None:
            raise ValueError("canceled status requires finished_at")

        return self
