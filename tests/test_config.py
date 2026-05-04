import pytest
from pydantic import ValidationError

from agent.config import Settings
from agent.models.schemas import StageResult


def test_settings_defaults_include_all_stage_models(monkeypatch) -> None:
    for name in [
        "X2W_PROVIDER",
        "X2W_MODEL_PROVIDER",
        "X2W_MODEL_TRANSLATE",
        "X2W_TRANSLATE_MODEL",
        "X2W_MODEL_REVIEW",
        "X2W_REVIEW_MODEL",
        "X2W_MODEL_WECHAT_REWRITE",
        "X2W_WECHAT_REWRITE_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.provider == "qwen"
    assert settings.stage_models == {
        "translate": "qwen-plus",
        "review": "qwen-plus",
        "wechat-rewrite": "qwen-max",
    }
    assert settings.x_storage_state_path is None


def test_settings_loads_x_storage_state_path_from_env(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "x-state.json"
    monkeypatch.setenv("X2W_X_STORAGE_STATE_PATH", str(state_path))

    settings = Settings()

    assert settings.x_storage_state_path == str(state_path)


def test_settings_loads_api_key_from_dotenv_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("X2W_API_KEY", raising=False)
    (tmp_path / ".env").write_text("X2W_API_KEY=file-key\n", encoding="utf-8")

    settings = Settings()

    assert settings.api_key == "file-key"


def test_settings_env_api_key_overrides_dotenv_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("X2W_API_KEY", "env-key")
    (tmp_path / ".env").write_text("X2W_API_KEY=file-key\n", encoding="utf-8")

    settings = Settings()

    assert settings.api_key == "env-key"


def test_settings_load_values_from_primary_env_names(monkeypatch) -> None:
    monkeypatch.setenv("X2W_PROVIDER", "openai")
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "gpt-4.1-mini")
    monkeypatch.setenv("X2W_MODEL_REVIEW", "gpt-4.1")
    monkeypatch.setenv("X2W_MODEL_WECHAT_REWRITE", "gpt-4.1-nano")

    settings = Settings()

    assert settings.provider == "openai"
    assert settings.stage_models == {
        "translate": "gpt-4.1-mini",
        "review": "gpt-4.1",
        "wechat-rewrite": "gpt-4.1-nano",
    }


def test_settings_load_values_from_compatible_env_names(monkeypatch) -> None:
    monkeypatch.setenv("X2W_MODEL_PROVIDER", "qwen")
    monkeypatch.setenv("X2W_TRANSLATE_MODEL", "qwen-plus-2025-04-28")
    monkeypatch.setenv("X2W_REVIEW_MODEL", "qwen-plus-2025-04-28")
    monkeypatch.setenv("X2W_WECHAT_REWRITE_MODEL", "qwen-max-2025-01-25")

    settings = Settings()

    assert settings.provider == "qwen"
    assert settings.stage_models == {
        "translate": "qwen-plus-2025-04-28",
        "review": "qwen-plus-2025-04-28",
        "wechat-rewrite": "qwen-max-2025-01-25",
    }


def test_settings_reject_invalid_provider(monkeypatch) -> None:
    monkeypatch.setenv("X2W_PROVIDER", "anthropic")

    with pytest.raises(ValidationError, match="X2W_PROVIDER|provider"):
        Settings()


def test_settings_reject_empty_model(monkeypatch) -> None:
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "   ")

    with pytest.raises(ValidationError, match="X2W_MODEL_TRANSLATE|model_translate"):
        Settings()


def test_stage_result_success_rejects_error_fields() -> None:
    with pytest.raises(ValidationError, match="success"):
        StageResult(
            stage="translate",
            status="success",
            error_type="GatewayError",
            error_message="unexpected",
        )


def test_stage_result_failure_requires_error_details() -> None:
    with pytest.raises(ValidationError, match="failure"):
        StageResult(stage="translate", status="failure")
