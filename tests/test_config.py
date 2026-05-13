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
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.provider == "qwen"
    assert settings.stage_models == {
        "translate": "qwen-mt-plus",
        "review": "qwen-plus",
        "route": "qwen-plus",
        "final-check": "qwen-plus",
        "light-polish": "qwen-plus",
        "targeted-fix": "qwen-mt-plus",
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


def test_settings_constructor_values_override_dotenv_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "X2W_API_KEY=file-key",
                "X2W_MODEL_TRANSLATE=qwen-mt-plus",
                "X2W_MODEL_REVIEW=qwen-plus",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    settings = Settings(
        api_key="constructor-key",
        model_translate="translate-model",
        model_review="review-model",
    )

    assert settings.api_key == "constructor-key"
    assert settings.stage_models == {
        "translate": "translate-model",
        "review": "review-model",
        "route": "review-model",
        "final-check": "review-model",
        "light-polish": "review-model",
        "targeted-fix": "translate-model",
    }


def test_settings_load_values_from_primary_env_names(monkeypatch) -> None:
    for name in [
        "X2W_MODEL_PROVIDER",
        "X2W_TRANSLATE_MODEL",
        "X2W_REVIEW_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("X2W_PROVIDER", "openai")
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "gpt-4.1-mini")
    monkeypatch.setenv("X2W_MODEL_REVIEW", "gpt-4.1")

    settings = Settings()

    assert settings.provider == "openai"
    assert settings.stage_models == {
        "translate": "gpt-4.1-mini",
        "review": "gpt-4.1",
        "route": "gpt-4.1",
        "final-check": "gpt-4.1",
        "light-polish": "gpt-4.1",
        "targeted-fix": "gpt-4.1-mini",
    }


def test_settings_load_values_from_compatible_env_names(monkeypatch) -> None:
    for name in [
        "X2W_PROVIDER",
        "X2W_MODEL_TRANSLATE",
        "X2W_MODEL_REVIEW",
    ]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("X2W_MODEL_PROVIDER", "qwen")
    monkeypatch.setenv("X2W_TRANSLATE_MODEL", "qwen-mt-plus")
    monkeypatch.setenv("X2W_REVIEW_MODEL", "qwen-mt-plus")

    settings = Settings()

    assert settings.provider == "qwen"
    assert settings.stage_models == {
        "translate": "qwen-mt-plus",
        "review": "qwen-mt-plus",
        "route": "qwen-mt-plus",
        "final-check": "qwen-mt-plus",
        "light-polish": "qwen-mt-plus",
        "targeted-fix": "qwen-mt-plus",
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
