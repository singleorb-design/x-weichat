from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ProviderName = Literal["qwen", "openai-compatible", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="X2W_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    provider: ProviderName = Field(
        default="qwen",
        validation_alias=AliasChoices("X2W_PROVIDER", "X2W_MODEL_PROVIDER"),
    )
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = Field(default="", repr=False)
    artifacts_dir: str = "artifacts"
    x_storage_state_path: str | None = None
    model_translate: str = Field(
        default="qwen-plus",
        validation_alias=AliasChoices("X2W_MODEL_TRANSLATE", "X2W_TRANSLATE_MODEL"),
    )
    model_review: str = Field(
        default="qwen-plus",
        validation_alias=AliasChoices("X2W_MODEL_REVIEW", "X2W_REVIEW_MODEL"),
    )
    model_wechat_rewrite: str = Field(
        default="qwen-max",
        validation_alias=AliasChoices("X2W_MODEL_WECHAT_REWRITE", "X2W_WECHAT_REWRITE_MODEL"),
    )

    @field_validator("model_translate", "model_review", "model_wechat_rewrite")
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

    @property
    def stage_models(self) -> dict[str, str]:
        return {
            "translate": self.model_translate,
            "review": self.model_review,
            "wechat-rewrite": self.model_wechat_rewrite,
        }
