from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ProviderName = Literal["qwen", "openai-compatible", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="X2W_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    provider: ProviderName = "qwen"
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = Field(default="", repr=False)
    artifacts_dir: str = "artifacts"
    x_storage_state_path: str | None = None
    model_translate: str = Field(
        default="qwen-mt-plus",
    )
    model_review: str = Field(
        default="qwen-plus",
    )

    final_output_max_fix_rounds: int = Field(
        default=3,
    )

    # targeted-fix: rule-first, LLM fallback with hard timeout
    targeted_fix_timeout_seconds: float = Field(default=90.0)
    targeted_fix_max_attempts: int = Field(default=2)
    targeted_fix_enable_llm_fallback: bool = Field(default=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        def compat_env_settings() -> dict[str, Any]:
            """兼容旧的环境变量命名。

            - 主名字：`X2W_PROVIDER`, `X2W_MODEL_TRANSLATE`, `X2W_MODEL_REVIEW`
            - 兼容名字：`X2W_MODEL_PROVIDER`, `X2W_TRANSLATE_MODEL`, `X2W_REVIEW_MODEL`
            """

            mapped: dict[str, Any] = {}
            env = os.environ

            if env.get("X2W_MODEL_PROVIDER"):
                mapped["provider"] = env["X2W_MODEL_PROVIDER"]

            if env.get("X2W_TRANSLATE_MODEL"):
                mapped["model_translate"] = env["X2W_TRANSLATE_MODEL"]

            if env.get("X2W_REVIEW_MODEL"):
                mapped["model_review"] = env["X2W_REVIEW_MODEL"]

            return mapped

        return (
            init_settings,
            env_settings,
            compat_env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @field_validator("model_translate", "model_review")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model name must not be empty")

        return normalized

    @field_validator("x_storage_state_path")
    @classmethod
    def validate_x_storage_state_path(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None

        return normalized

    @field_validator("final_output_max_fix_rounds")
    @classmethod
    def validate_final_output_max_fix_rounds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("final_output_max_fix_rounds must be >= 1")
        if value > 5:
            # 防止无意间把重试拉太高导致 token 成本爆炸。
            return 5
        return value

    @field_validator("targeted_fix_timeout_seconds")
    @classmethod
    def validate_targeted_fix_timeout_seconds(cls, value: float) -> float:
        if value < 5:
            raise ValueError("targeted_fix_timeout_seconds must be >= 5")
        if value > 300:
            # 避免把“定点修复”又配置成长超时导致 pipeline 卡住。
            return 300.0
        return float(value)

    @field_validator("targeted_fix_max_attempts")
    @classmethod
    def validate_targeted_fix_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("targeted_fix_max_attempts must be >= 1")
        if value > 3:
            return 3
        return value

    @property
    def stage_models(self) -> dict[str, str]:
        return {
            "translate": self.model_translate,
            "review": self.model_review,
            "route": self.model_review,
            "final-check": self.model_review,
            "light-polish": self.model_review,
            # 定点修复阶段更适合使用更强的“严格遵循输入”的模型。
            # 默认复用翻译模型（qwen-mt-plus），避免模型在引用块/链接上做过度润色导致格式校验失败。
            "targeted-fix": self.model_translate,
        }
