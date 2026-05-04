from pathlib import Path
import subprocess

import pytest

from agent.config import Settings
from agent.core.pipeline import PipelineRunner
from agent.jobs.store import JobStore
from agent.models.schemas import StageError, StageModelInfo
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext
from agent.stages.review import build_review_input, run_review
from agent.stages.translate import build_translate_input, run_translate
from agent.stages.wechat_rewrite import (
    build_wechat_rewrite_input,
    run_wechat_rewrite,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeGateway:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, str]] = []

    def generate_markdown(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        return self._outputs[len(self.calls) - 1]


def test_prompts_are_chinese_text_files() -> None:
    translate_prompt = load_prompt("translate_zh.txt")
    review_prompt = load_prompt("review_zh.txt")
    rewrite_prompt = load_prompt("wechat_rewrite_zh.txt")

    assert "你是一名专业技术翻译" in translate_prompt
    assert "你是一名资深中文编辑" in review_prompt
    assert "你是一名顶级中文内容创作者" in rewrite_prompt


def test_stage_context_keeps_job_identity() -> None:
    context = StageContext(job_id="job-1", url="https://x.com/a/status/1")

    assert context.job_id == "job-1"
    assert context.url == "https://x.com/a/status/1"
    assert context.storage_state is None


def test_pipeline_runner_passes_storage_state_from_settings_into_x_fetch_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(
        api_key="test-key",
        artifacts_dir=str(tmp_path),
        x_storage_state_path=str(tmp_path / "x-state.json"),
    )
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)
    captured: dict[str, str | None] = {}

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        assert stage_store is store
        captured["job_id"] = context.job_id
        captured["url"] = context.url
        captured["storage_state"] = context.storage_state
        raise RuntimeError("stop after x-fetch context capture")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)

    assert result.status == "failed"
    assert captured == {
        "job_id": job.job_id,
        "url": "https://x.com/a/status/1",
        "storage_state": str(tmp_path / "x-state.json"),
    }


def test_translate_stage_builds_markdown_input() -> None:
    source = (FIXTURES_DIR / "source.md").read_text(encoding="utf-8")

    text = build_translate_input(source)

    assert "请把下面内容翻译成中文" in text
    assert "# Building Reliable Agents" in text
    assert source in text


def test_review_and_rewrite_inputs_include_instruction_and_markdown() -> None:
    markdown = "# 中文标题\n\n这里是一段中文内容。"

    review_text = build_review_input(markdown)
    rewrite_text = build_wechat_rewrite_input(markdown)

    assert "请审校下面中文 Markdown" in review_text
    assert markdown in review_text
    assert "请把下面内容改写成公众号文章" in rewrite_text
    assert markdown in rewrite_text


def test_translate_review_wechat_rewrite_render_html_chain_uses_fixed_sample_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.stages.render_html import run_render_html

    source = (FIXTURES_DIR / "source.md").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="01-source.md",
        content=source,
    )
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "translate-model")
    monkeypatch.setenv("X2W_MODEL_REVIEW", "review-model")
    monkeypatch.setenv("X2W_MODEL_WECHAT_REWRITE", "wechat-model")
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    renderer_calls: list[list[str]] = []

    translated_markdown = """# 构建可靠的 Agent

大型语言模型很有用，但它们通常需要更清晰的结构。

- 从一个明确的小任务开始。
- 增加验证步骤。
- 保持 Markdown 输出。
"""
    reviewed_markdown = """# 构建可靠的 Agent

大型语言模型很有价值，但往往需要更清晰的流程约束。

- 从明确且范围可控的任务开始。
- 补充验证步骤。
- 始终保持 Markdown 输出。
"""
    rewritten_markdown = """# 构建可靠的 Agent：把大模型工作流做稳

如果想让大模型稳定产出，关键不是一次性给出更长的提示词，而是先收窄任务，再逐步增加校验。

## 可执行做法

- 先定义一个小而清晰的目标。
- 在关键节点加入审校与验收。
- 让每一步都输出 Markdown，方便继续加工。
"""
    gateway = FakeGateway(
        outputs=[
            translated_markdown,
            reviewed_markdown,
            rewritten_markdown,
        ]
    )
    context = StageContext(job_id=job.job_id, url=job.url)

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        renderer_calls.append(command)
        input_path = Path(command[2])
        output_path = Path(command[3])
        markdown = input_path.read_text(encoding="utf-8")
        output_path.write_text(
            (
                "<html><body>"
                "<article><h1>构建可靠的 Agent：把大模型工作流做稳</h1>"
                f"<section>{markdown}</section>"
                "</article></body></html>"
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("agent.stages.render_html.subprocess.run", fake_run)

    translated = run_translate(context=context, store=store, gateway=gateway, settings=settings)
    reviewed = run_review(context=context, store=store, gateway=gateway, settings=settings)
    rewritten = run_wechat_rewrite(
        context=context,
        store=store,
        gateway=gateway,
        settings=settings,
    )
    html = run_render_html(context=context, store=store)

    translation_path = tmp_path / job.job_id / "02-translation.md"
    reviewed_path = tmp_path / job.job_id / "03-reviewed.md"
    wechat_path = tmp_path / job.job_id / "04-wechat.md"
    html_path = tmp_path / job.job_id / "05-wechat.html"

    assert translated == translated_markdown
    assert reviewed == reviewed_markdown
    assert rewritten == rewritten_markdown
    assert translation_path.is_file()
    assert reviewed_path.is_file()
    assert wechat_path.is_file()
    assert html_path.is_file()
    assert translation_path.read_text(encoding="utf-8") == translated
    assert reviewed_path.read_text(encoding="utf-8") == reviewed
    assert wechat_path.read_text(encoding="utf-8") == rewritten
    assert translation_path.read_text(encoding="utf-8").startswith("# 构建可靠的 Agent")
    assert "- 从一个明确的小任务开始。" in translation_path.read_text(encoding="utf-8")
    assert reviewed_path.read_text(encoding="utf-8").count("\n- ") == 3
    assert "## 可执行做法" in wechat_path.read_text(encoding="utf-8")
    assert wechat_path.read_text(encoding="utf-8").count("\n- ") == 3
    assert html == html_path.read_text(encoding="utf-8")
    assert html.lstrip().startswith("<html>")
    assert "<article>" in html
    assert "<h1>构建可靠的 Agent：把大模型工作流做稳</h1>" in html
    assert "<section># 构建可靠的 Agent：把大模型工作流做稳" in html
    assert gateway.calls == [
        {
            "model": "translate-model",
            "system_prompt": load_prompt("translate_zh.txt"),
            "user_prompt": build_translate_input(source),
        },
        {
            "model": "review-model",
            "system_prompt": load_prompt("review_zh.txt"),
            "user_prompt": build_review_input(translated),
        },
        {
            "model": "wechat-model",
            "system_prompt": load_prompt("wechat_rewrite_zh.txt"),
            "user_prompt": build_wechat_rewrite_input(reviewed),
        },
    ]
    assert renderer_calls == [
        [
            "node",
            str(
                Path(__file__).resolve().parents[1]
                / "packages"
                / "renderer"
                / "dist"
                / "index.js"
            ),
            renderer_calls[0][2],
            renderer_calls[0][3],
        ]
    ]


def test_stage_runners_ignore_settings_artifacts_dir_for_input_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = (FIXTURES_DIR / "source.md").read_text(encoding="utf-8")
    store_root = tmp_path / "job-store"
    mismatched_artifacts_dir = tmp_path / "different-artifacts-dir"
    store = JobStore(root_dir=store_root)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="01-source.md",
        content=source,
    )
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "translate-model")
    settings = Settings(
        api_key="test-key",
        artifacts_dir=str(mismatched_artifacts_dir),
    )
    gateway = FakeGateway(outputs=["# 中文翻译\n\n第一稿"])
    context = StageContext(job_id=job.job_id, url=job.url)

    translated = run_translate(context=context, store=store, gateway=gateway, settings=settings)

    assert translated == "# 中文翻译\n\n第一稿"
    assert (
        store_root / job.job_id / "02-translation.md"
    ).read_text(encoding="utf-8") == translated
    assert gateway.calls == [
        {
            "model": "translate-model",
            "system_prompt": load_prompt("translate_zh.txt"),
            "user_prompt": build_translate_input(source),
        }
    ]


def test_load_prompt_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Prompt path traversal is not allowed"):
        load_prompt("../tests/fixtures/source.md")


def test_load_prompt_missing_file_raises_clear_exception() -> None:
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        load_prompt("does-not-exist.txt")


def test_render_html_stage_shells_out_and_writes_html_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.stages.render_html import run_render_html

    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="04-wechat.md",
        content="# 标题\n\n正文",
    )
    context = StageContext(job_id=job.job_id, url=job.url)
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        input_path = Path(command[2])
        output_path = Path(command[3])
        markdown = input_path.read_text(encoding="utf-8")
        output_path.write_text(f"<html><body>{markdown}</body></html>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("agent.stages.render_html.subprocess.run", fake_run)

    html = run_render_html(context=context, store=store)

    assert html == "<html><body># 标题\n\n正文</body></html>"
    assert (tmp_path / job.job_id / "05-wechat.html").read_text(encoding="utf-8") == html
    assert calls == [
        [
            "node",
            str(
                Path(__file__).resolve().parents[1]
                / "packages"
                / "renderer"
                / "dist"
                / "index.js"
            ),
            calls[0][2],
            calls[0][3],
        ]
    ]


def test_render_html_raises_clear_error_when_renderer_cli_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.stages import render_html as render_html_stage

    input_path = tmp_path / "04-wechat.md"
    output_path = tmp_path / "05-wechat.html"
    missing_cli_path = tmp_path / "missing-renderer-cli.js"
    calls: list[list[str]] = []

    input_path.write_text("# 标题\n\n正文", encoding="utf-8")

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(render_html_stage, "renderer_cli_path", lambda: missing_cli_path)
    monkeypatch.setattr(render_html_stage.subprocess, "run", fake_run)

    with pytest.raises(FileNotFoundError, match="Renderer CLI not found"):
        render_html_stage.render_html(input_path, output_path)

    assert calls == []


def test_pipeline_runner_executes_stages_sequentially_and_marks_job_succeeded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    gateway = object()
    settings = type(
        "SettingsStub",
        (),
        {
            "provider": "openai",
            "stage_models": {
                "translate": "gpt-4.1-mini",
                "review": "gpt-4.1",
                "wechat-rewrite": "gpt-4.1-nano",
            },
            "x_storage_state_path": None,
        },
    )()
    runner = PipelineRunner(store=store, gateway=gateway, settings=settings)
    calls: list[str] = []
    perf_values = iter([10.0, 10.5, 20.0, 21.25, 30.0, 30.75, 40.0, 41.0, 50.0, 50.2])

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        assert stage_store is store
        calls.append("x-fetch")
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        assert gateway is runner.gateway
        assert settings is runner.settings
        calls.append("translate")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="02-translation.md",
            content="# translation",
        )
        return "# translation"

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("review")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="03-reviewed.md",
            content="# reviewed",
        )
        return "# reviewed"

    def fake_wechat_rewrite(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("wechat-rewrite")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="04-wechat.md",
            content="# wechat",
        )
        return "# wechat"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        calls.append("render-html")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="05-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", fake_wechat_rewrite)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)
    monkeypatch.setattr("agent.core.pipeline.perf_counter", lambda: next(perf_values))

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "succeeded"
    assert result.job_id == job.job_id
    assert calls == [
        "x-fetch",
        "translate",
        "review",
        "wechat-rewrite",
        "render-html",
    ]
    assert saved.status == "succeeded"
    assert saved.current_stage == "render-html"
    assert saved.started_at is not None
    assert saved.finished_at is not None
    assert saved.stage_errors == {}
    assert saved.stage_models == {
        "x-fetch": StageModelInfo(provider="builtin", model="local:x-fetch"),
        "translate": StageModelInfo(provider="openai", model="gpt-4.1-mini"),
        "review": StageModelInfo(provider="openai", model="gpt-4.1"),
        "wechat-rewrite": StageModelInfo(provider="openai", model="gpt-4.1-nano"),
        "render-html": StageModelInfo(provider="builtin", model="local:render-html"),
    }
    assert saved.prompt_versions == {
        "translate": "translate_zh.txt",
        "review": "review_zh.txt",
        "wechat-rewrite": "wechat_rewrite_zh.txt",
    }
    assert saved.stage_durations == pytest.approx(
        {
            "x-fetch": 0.5,
            "translate": 1.25,
            "review": 0.75,
            "wechat-rewrite": 1.0,
            "render-html": 0.2,
        }
    )
    assert store.read_artifact(job_id=job.job_id, relative_path="01-source.md") == "# source"
    assert store.read_artifact(job_id=job.job_id, relative_path="02-translation.md") == "# translation"
    assert store.read_artifact(job_id=job.job_id, relative_path="03-reviewed.md") == "# reviewed"
    assert store.read_artifact(job_id=job.job_id, relative_path="04-wechat.md") == "# wechat"
    assert store.read_artifact(job_id=job.job_id, relative_path="05-wechat.html") == "<html></html>"


def test_pipeline_runner_marks_job_failed_and_logs_error_when_stage_crashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)
    calls: list[str] = []
    perf_values = iter([100.0, 100.4, 200.0, 200.9])

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        calls.append("x-fetch")
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("translate")
        raise RuntimeError("translate exploded")

    def fail_if_called(**_: object) -> str:
        raise AssertionError("later stages must not run after failure")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.perf_counter", lambda: next(perf_values))

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)
    log_path = tmp_path / job.job_id / "logs" / "pipeline.log"

    assert result.status == "failed"
    assert calls == ["x-fetch", "translate"]
    assert saved.status == "failed"
    assert saved.current_stage == "translate"
    assert saved.started_at is not None
    assert saved.finished_at is not None
    assert saved.stage_models == {
        "x-fetch": StageModelInfo(provider="builtin", model="local:x-fetch"),
        "translate": StageModelInfo(provider="unknown", model="unconfigured:translate"),
    }
    assert saved.prompt_versions == {"translate": "translate_zh.txt"}
    assert saved.stage_durations == pytest.approx({"x-fetch": 0.4, "translate": 0.9})
    assert saved.stage_errors == {
        "translate": StageError(
            error_type="RuntimeError",
            message="translate exploded",
            retryable=False,
            suggestion="Inspect pipeline.log and the stage inputs before rerunning.",
        )
    }
    assert log_path.read_text(encoding="utf-8")
    assert "translate" in log_path.read_text(encoding="utf-8")
    assert "translate exploded" in log_path.read_text(encoding="utf-8")
    assert store.read_artifact(job_id=job.job_id, relative_path="01-source.md") == "# source"
    with pytest.raises(FileNotFoundError):
        store.read_artifact(job_id=job.job_id, relative_path="02-translation.md")


def test_pipeline_runner_rejects_non_pending_jobs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)
    job = runner.create_job("https://x.com/a/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="x-fetch",
    )

    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("stages must not run for non-pending jobs")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fail_if_called)

    with pytest.raises(ValueError, match="pending"):
        runner.run(job.job_id)


def test_pipeline_runner_marks_job_failed_even_when_failure_logging_also_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        raise RuntimeError("translate exploded")

    original_update_status = store.update_status
    original_update_stage_metadata = store.update_stage_metadata
    calls: list[str] = []

    def flaky_update_stage_metadata(**kwargs: object) -> object:
        calls.append("update_stage_metadata")
        if kwargs.get("error") is not None:
            raise OSError("metadata write failed")
        return original_update_stage_metadata(**kwargs)

    def flaky_append_log(**kwargs: object) -> object:
        calls.append("append_log")
        raise OSError("log write failed")

    def tracking_update_status(**kwargs: object):
        calls.append(f"update_status:{kwargs['status']}")
        return original_update_status(**kwargs)

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr(store, "update_stage_metadata", flaky_update_stage_metadata)
    monkeypatch.setattr(store, "append_log", flaky_append_log)
    monkeypatch.setattr(store, "update_status", tracking_update_status)

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert saved.status == "failed"
    assert saved.current_stage == "translate"
    assert calls == [
        "update_status:running",
        "update_stage_metadata",
        "update_status:running",
        "update_stage_metadata",
        "append_log",
        "update_status:failed",
    ]


def test_pipeline_runner_consumes_claim_before_first_stage_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store, gateway=object(), settings=object())
    calls: list[str] = []

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        calls.append("x-fetch")
        assert not (tmp_path / context.job_id / ".run-claim").exists()
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("translate")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="02-translation.md",
            content="# translation",
        )
        return "# translation"

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("review")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="03-reviewed.md",
            content="# reviewed",
        )
        return "# reviewed"

    def fake_wechat_rewrite(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("wechat-rewrite")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="04-wechat.md",
            content="# wechat",
        )
        return "# wechat"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        calls.append("render-html")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="05-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", fake_wechat_rewrite)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)

    job = runner.create_job("https://x.com/a/status/1")
    claim_token = store.claim_run(job_id=job.job_id)

    original_consume_run_claim = store.consume_run_claim

    def tracking_consume_run_claim(*, job_id: str, claim_token: str) -> None:
        current = store.read_job(job_id)
        assert current.status == "pending"
        assert current.current_stage is None

        with pytest.raises(FileExistsError, match="Run claim already exists"):
            store.claim_run(job_id=job_id)

        original_consume_run_claim(job_id=job_id, claim_token=claim_token)

    monkeypatch.setattr(store, "consume_run_claim", tracking_consume_run_claim)

    result = runner.run(job.job_id, claim_token)

    assert result.status == "succeeded"
    assert calls == [
        "x-fetch",
        "translate",
        "review",
        "wechat-rewrite",
        "render-html",
    ]
    assert not (tmp_path / job.job_id / ".run-claim").exists()


def test_pipeline_creates_all_artifacts_after_successful_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store, gateway=object(), settings=object())

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="02-translation.md",
            content="# translation",
        )
        return "# translation"

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="03-reviewed.md",
            content="# reviewed",
        )
        return "# reviewed"

    def fake_wechat_rewrite(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="04-wechat.md",
            content="# wechat",
        )
        return "# wechat"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="05-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", fake_wechat_rewrite)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)
    job_dir = tmp_path / job.job_id

    assert result.status == "succeeded"
    assert (job_dir / "01-source.md").is_file()
    assert (job_dir / "02-translation.md").is_file()
    assert (job_dir / "03-reviewed.md").is_file()
    assert (job_dir / "04-wechat.md").is_file()
    assert (job_dir / "05-wechat.html").is_file()


def test_pipeline_runner_marks_job_failed_when_consume_run_claim_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)
    job = runner.create_job("https://x.com/a/status/1")
    claim_token = store.claim_run(job_id=job.job_id)

    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("stages must not run when consume_run_claim fails")

    def broken_consume_run_claim(*, job_id: str, claim_token: str) -> None:
        raise RuntimeError("claim cleanup exploded")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fail_if_called)
    monkeypatch.setattr(store, "consume_run_claim", broken_consume_run_claim)

    with pytest.raises(RuntimeError, match="consume_run_claim failed before starting stage x-fetch"):
        runner.run(job.job_id, claim_token)

    saved = store.read_job(job.job_id)

    assert saved.status == "pending"
    assert saved.current_stage is None
    assert saved.started_at is None
    assert saved.finished_at is None
    assert saved.stage_models == {}
    assert saved.prompt_versions == {}
    assert saved.stage_durations == {}
    assert saved.stage_errors == {}
    assert (tmp_path / job.job_id / ".run-claim").is_file()
