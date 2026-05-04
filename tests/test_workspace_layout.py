from pathlib import Path
import os
import subprocess


def test_workspace_layout_exists() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    required_files = [
        Path("Makefile"),
        Path(".env.example"),
        Path("pyproject.toml"),
        Path("agent/__init__.py"),
        Path("agent/api/__init__.py"),
        Path("agent/core/__init__.py"),
        Path("agent/jobs/__init__.py"),
        Path("agent/models/__init__.py"),
        Path("agent/prompts/__init__.py"),
        Path("agent/stages/__init__.py"),
        Path("packages/x_fetch/__init__.py"),
        Path("apps/web/package.json"),
        Path("packages/renderer/package.json"),
    ]

    missing = [
        str(path) for path in required_files if not (repo_root / path).is_file()
    ]

    assert not missing, (
        "Missing required workspace skeleton files:\n"
        + "\n".join(f"- {path}" for path in missing)
    )


def test_makefile_exposes_one_command_workflow_targets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")

    for target in [
        "help:",
        "setup:",
        "check-api:",
        "backend:",
        "frontend:",
        "start:",
        "dev:",
        "test:",
        "build:",
        "install-playwright:",
    ]:
        assert target in makefile

    assert "uv sync --extra dev" in makefile
    assert "ENV_FILE ?= .env" in makefile
    assert "include $(ENV_FILE)" in makefile
    assert 'npm --prefix "$(RENDERER_DIR)" install' in makefile
    assert 'npm --prefix "$(WEB_DIR)" install' in makefile
    assert 'uv run --directory "$(ROOT_DIR)" playwright install chromium' in makefile
    assert 'PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" python -c' in makefile
    assert 'from agent.config import Settings' in makefile
    assert 'from agent.models.gateway import ModelGateway' in makefile
    assert 'PYTHONPATH="$(ROOT_DIR)" uv run --directory "$(ROOT_DIR)" --python 3.11 uvicorn agent.api.main:app' in makefile
    assert 'npm --prefix "$(WEB_DIR)" run dev' in makefile


def test_env_example_contains_required_configuration_keys() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert "X2W_API_KEY=" in env_example
    assert "X2W_PROVIDER=qwen" in env_example
    assert "X2W_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1" in env_example
    assert "X2W_MODEL_TRANSLATE=" in env_example
    assert "X2W_MODEL_REVIEW=" in env_example
    assert "X2W_MODEL_WECHAT_REWRITE=" in env_example


def test_backend_dev_script_restarts_existing_8000_listener(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_marker = tmp_path / "uv-called"
    kill_marker = tmp_path / "kill-called"

    (bin_dir / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -f {kill_marker} ]; then exit 0; fi\n"
        "printf '3279\\n'\n",
        encoding="utf-8",
    )
    (bin_dir / "kill").write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' \"$*\" > {kill_marker}\n",
        encoding="utf-8",
    )
    (bin_dir / "uv").write_text(
        "#!/usr/bin/env bash\n"
        f"touch {uv_marker}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(bin_dir / "lsof", 0o755)
    os.chmod(bin_dir / "kill", 0o755)
    os.chmod(bin_dir / "uv", 0o755)

    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "dev.sh")],
        cwd=repo_root,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert uv_marker.exists()
    assert kill_marker.read_text(encoding="utf-8") == "3279"
    assert "127.0.0.1:8000 已被占用，正在重启后端服务。" in result.stdout


def test_make_backend_starts_uvicorn_when_8000_is_free(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_marker = tmp_path / "uv-called"

    (bin_dir / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "uv").write_text(
        "#!/usr/bin/env bash\n"
        f"touch {uv_marker}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(bin_dir / "lsof", 0o755)
    os.chmod(bin_dir / "uv", 0o755)

    result = subprocess.run(
        ["make", "backend"],
        cwd=repo_root,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert uv_marker.exists()
