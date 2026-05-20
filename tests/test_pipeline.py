import json
from pathlib import Path
import subprocess

import pytest

import agent.stages.review as review_stage
import agent.stages.light_polish as light_polish_stage
import agent.stages.translate as translate_stage
from agent.config import Settings
from agent.core.pipeline import PipelineRunner
from agent.jobs.store import JobStore
from agent.models.gateway import build_messages
from agent.models.schemas import StageError, StageModelInfo
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext
from agent.stages.final_check import build_final_check_input
from agent.stages.final_output import run_final_output
from agent.stages.helpers import enhance_readability_markdown, sanitize_publish_markdown, write_json_artifact
from agent.stages.light_polish import run_light_polish
from agent.stages.review import build_review_input, run_review
from agent.stages.targeted_fix import run_targeted_fix
from agent.stages.translate import build_translate_input, run_translate
from packages.x_fetch.client import fetch_x_markdown_with_skill


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
        request_timeout_seconds: float | None = None,
    ) -> str:
        del request_timeout_seconds
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        return self._outputs[len(self.calls) - 1]


def write_metadata_artifact(
    store: JobStore,
    *,
    job_id: str,
    source_type: str = "article",
    title: str = "构建可靠的 Agent",
) -> None:
    store.write_artifact(
        job_id=job_id,
        relative_path="metadata.json",
        content=json.dumps(
            {
                "url": "https://x.com/hooeem/article/2050332284675362853",
                "requestedUrl": "https://x.com/hooeem/article/2050332284675362853",
                "source_type": source_type,
                "title": title,
                "coverImage": "https://example.com/cover.png",
            },
            ensure_ascii=False,
        ),
    )


def write_route_artifact(
    store: JobStore,
    *,
    job_id: str,
    decision: str,
    risk: str = "LOW",
) -> None:
    write_json_artifact(
        store=store,
        job_id=job_id,
        relative_path="04-route.json",
        payload={
            "decision": decision,
            "reason": "test route decision",
            "risk": risk,
            "recommended_next_prompt": decision,
        },
    )


def write_final_check_artifact(
    store: JobStore,
    *,
    job_id: str,
    passed: bool,
    fix_required: bool = False,
    risk: str = "LOW",
    issues: list[dict[str, str]] | None = None,
) -> None:
    write_json_artifact(
        store=store,
        job_id=job_id,
        relative_path="08-final-check.json",
        payload={
            "pass": passed,
            "risk": risk,
            "fix_required": fix_required,
            "issues": issues or [],
        },
    )


def test_prompts_are_chinese_text_files() -> None:
    translate_prompt = load_prompt("translate_zh.txt")
    review_prompt = load_prompt("review_zh.txt")
    route_prompt = load_prompt("route_zh.txt")

    assert "你是一个专业的技术翻译助手" in translate_prompt
    assert "你是一名资深技术编辑 + 翻译审校专家" in review_prompt
    assert '"decision": "PASS | LIGHT_POLISH"' in route_prompt
    assert "REWRITE" not in route_prompt


def test_article_output_prompts_avoid_emoji_style_markers() -> None:
    prompt_names = [
        "translate_zh.txt",
        "review_zh.txt",
        "light_polish_zh.txt",
        "targeted_fix_zh.txt",
    ]
    disallowed_markers = [
        "\u2705",
        "\u274c",
        "\U0001f525",
        "\U0001f680",
        "\U0001f4a1",
        "\U0001f449",
        "\u2b50",
        "\u26a0\ufe0f",
    ]

    for prompt_name in prompt_names:
        prompt = load_prompt(prompt_name)
        assert "不得使用 emoji" in prompt
        for marker in disallowed_markers:
            assert marker not in prompt


def test_article_output_prompts_remove_social_cta_lines() -> None:
    prompt_names = [
        "translate_zh.txt",
        "review_zh.txt",
        "light_polish_zh.txt",
        "targeted_fix_zh.txt",
    ]

    for prompt_name in prompt_names:
        prompt = load_prompt(prompt_name)
        assert "关注我" in prompt
        assert "感谢阅读" in prompt
        assert "收藏 + 转发" in prompt
        assert "建议先收藏本文" in prompt


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


def test_final_check_input_treats_metadata_as_context_not_publish_body() -> None:
    text = build_final_check_input(
        candidate_markdown="# 标题\n\n正文",
        metadata={"url": "https://x.com/i/article/1", "requestedUrl": "https://x.com/u/article/1"},
        route_payload={"decision": "LIGHT_POLISH", "risk": "LOW"},
    )

    assert "只有【最终候选稿】属于待发布正文" in text
    assert "【路由结果】和【元信息】都只是辅助上下文" in text


def test_translate_stage_splits_large_markdown_into_multiple_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    large_source = "---\ntitle: source\n---\n\n" + ("## Section\n\n" + ("A" * 4000) + "\n\n") * 3
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    store.write_artifact(job_id=context.job_id, relative_path="01-source.md", content=large_source)

    chunks_seen: list[str] = []

    class RecordingGateway:
        def generate_markdown(
            self,
            *,
            model: str,
            system_prompt: str,
            user_prompt: str,
        ) -> str:
            chunks_seen.append(user_prompt)
            return f"translated-{len(chunks_seen)}"

    monkeypatch.setattr(translate_stage, "MAX_TRANSLATE_CHARS_PER_REQUEST", 6000)

    output = run_translate(
        context=context,
        store=store,
        gateway=RecordingGateway(),
        settings=settings,
    )

    assert output == "translated-1\n\ntranslated-2\n\ntranslated-3"
    assert store.read_artifact(job_id=context.job_id, relative_path="02-translation.md") == output
    assert len(chunks_seen) == 3
    assert all(prompt.startswith("请把下面内容翻译成中文") for prompt in chunks_seen)


def test_translate_stage_keeps_single_chunk_output_exactly(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    source = "# Title\n\nShort body"
    expected_output = "# 译文\n\n保留末尾空行\n"
    store.write_artifact(job_id=context.job_id, relative_path="01-source.md", content=source)

    output = run_translate(
        context=context,
        store=store,
        gateway=FakeGateway(outputs=[expected_output]),
        settings=settings,
    )

    assert output == expected_output
    assert store.read_artifact(job_id=context.job_id, relative_path="02-translation.md") == expected_output


def test_translate_stage_keeps_each_qwen_mt_request_within_input_limit(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    source = "# Title\n\n" + ("A" * 7600)
    store.write_artifact(job_id=context.job_id, relative_path="01-source.md", content=source)

    class LengthGuardGateway:
        def __init__(self) -> None:
            self.calls = 0

        def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            messages = build_messages(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
            assert len(messages) == 1
            assert len(messages[0]["content"]) <= 8192
            return f"translated-{self.calls}"

    output = run_translate(
        context=context,
        store=store,
        gateway=LengthGuardGateway(),
        settings=settings,
    )

    assert output == "translated-1\n\ntranslated-2\n\ntranslated-3"
    assert store.read_artifact(job_id=context.job_id, relative_path="02-translation.md") == output


def test_review_stage_splits_large_markdown_into_multiple_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    large_translation = ("# 标题\n\n" + ("段落" * 2500) + "\n\n") * 3
    large_source = ("# Source\n\n" + ("source " * 2500) + "\n\n") * 3
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    store.write_artifact(job_id=context.job_id, relative_path="01-source.md", content=large_source)
    store.write_artifact(job_id=context.job_id, relative_path="02-translation.md", content=large_translation)

    chunks_seen: list[str] = []

    class RecordingGateway:
        def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
            chunks_seen.append(user_prompt)
            return f"reviewed-{len(chunks_seen)}"

    monkeypatch.setattr(review_stage, "MAX_REVIEW_CHARS_PER_REQUEST", 6000)
    monkeypatch.setattr(review_stage, "is_substantially_shorter", lambda *_args, **_kwargs: False)

    output = run_review(
        context=context,
        store=store,
        gateway=RecordingGateway(),
        settings=settings,
    )

    assert output.startswith("reviewed-1")
    assert len(chunks_seen) >= 3
    assert all(prompt.startswith("请对照英文原文审校下面的中文 Markdown") for prompt in chunks_seen)
    assert all("【原文】" in prompt and "【译文】" in prompt for prompt in chunks_seen)


def test_review_rebucket_chunks_expands_without_duplication() -> None:
    chunks = ["A1\n\nA2", "B1\n\nB2"]

    rebucketed = review_stage._rebucket_chunks(chunks, target_count=3)

    assert len(rebucketed) == 3
    assert all(bucket.strip() for bucket in rebucketed)
    assert "\n\n".join(rebucketed) == "A1\n\nA2\n\nB1\n\nB2"


def test_review_rebucket_chunks_expands_single_chunk_to_target_count() -> None:
    chunks = ["A1\n\nA2\n\nA3\n\nA4"]

    rebucketed = review_stage._rebucket_chunks(chunks, target_count=2)

    assert len(rebucketed) == 2
    assert all(bucket.strip() for bucket in rebucketed)
    assert "\n\n".join(rebucketed) == "A1\n\nA2\n\nA3\n\nA4"


def test_light_polish_stage_splits_large_markdown_into_multiple_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    large_reviewed = ("# 标题\n\n" + ("内容" * 2500) + "\n\n") * 3
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content=large_reviewed)
    write_route_artifact(store, job_id=context.job_id, decision="LIGHT_POLISH")
    write_metadata_artifact(store, job_id=context.job_id)

    chunks_seen: list[str] = []

    class RecordingGateway:
        def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
            chunks_seen.append(user_prompt)
            return f"polished-{len(chunks_seen)}"

    monkeypatch.setattr(light_polish_stage, "MAX_LIGHT_POLISH_CHARS_PER_REQUEST", 6000)
    monkeypatch.setattr(light_polish_stage, "is_substantially_shorter", lambda *_args, **_kwargs: False)

    output = run_light_polish(
        context=context,
        store=store,
        gateway=RecordingGateway(),
        settings=settings,
    )

    assert output == "polished-1\n\npolished-2\n\npolished-3"
    assert len(chunks_seen) == 3
    assert all(prompt.startswith("请对下面的已审校译文做公众号轻编辑") for prompt in chunks_seen)
    assert all("【元信息】" in prompt and "【Review 后译文】" in prompt for prompt in chunks_seen)


def test_light_polish_stage_retries_with_smaller_chunks_when_large_chunk_output_is_truncated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    sections = []
    for index in range(1, 5):
        sections.append(f"## /part {index}\n\n" + (f"第 {index} 段内容。" * 180))
    large_reviewed = "# 标题\n\n" + "\n\n".join(sections)
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content=large_reviewed)
    write_route_artifact(store, job_id=context.job_id, decision="LIGHT_POLISH")
    write_metadata_artifact(store, job_id=context.job_id)

    prompts_seen: list[str] = []

    class AdaptiveGateway:
        def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
            prompts_seen.append(user_prompt)
            chunk_markdown = user_prompt.split("【Review 后译文】\n", 1)[1]
            if len(chunk_markdown) > 5000:
                return "# 标题\n\n## /part 1\n\n只剩开头。"
            return chunk_markdown

    monkeypatch.setattr(light_polish_stage, "MAX_LIGHT_POLISH_CHARS_PER_REQUEST", 6000)

    output = run_light_polish(
        context=context,
        store=store,
        gateway=AdaptiveGateway(),
        settings=settings,
    )

    assert output == large_reviewed
    assert len(prompts_seen) > 2
    assert store.read_artifact(job_id=context.job_id, relative_path="05-polished.md") == large_reviewed


def test_light_polish_stage_falls_back_to_reviewed_markdown_when_all_retries_shorten_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    reviewed = "# 标题\n\n## /part 1\n\n" + ("原文内容。" * 400)
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content=reviewed)
    write_route_artifact(store, job_id=context.job_id, decision="LIGHT_POLISH")
    write_metadata_artifact(store, job_id=context.job_id)

    attempts: list[str] = []

    class AlwaysShortGateway:
        def generate_markdown(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
            attempts.append(user_prompt)
            return "# 标题\n\n只保留了开头。"

    monkeypatch.setattr(light_polish_stage, "MAX_LIGHT_POLISH_CHARS_PER_REQUEST", 1200)

    output = run_light_polish(
        context=context,
        store=store,
        gateway=AlwaysShortGateway(),
        settings=settings,
    )

    assert output == reviewed
    assert len(attempts) >= 2
    assert store.read_artifact(job_id=context.job_id, relative_path="05-polished.md") == reviewed


def test_review_input_includes_instruction_and_markdown() -> None:
    source_markdown = "# English Title\n\nThis is the source."
    markdown = "# 中文标题\n\n这里是一段中文内容。"

    review_text = build_review_input(source_markdown, markdown)

    assert "请对照英文原文审校下面的中文 Markdown" in review_text
    assert source_markdown in review_text
    assert markdown in review_text


def test_enhance_readability_markdown_inserts_key_point_for_long_sections() -> None:
    markdown = """## 第一节

第一段说明这个系统的背景，它需要在多次会话之间持续保存上下文。

第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。

第三段说明解决方向，项目配置文件可以把这些稳定信息提前写下来。

第四段说明协作方式，多个智能体可以围绕同一套规则分别完成编码、测试和审查。

第五段说明最终收益，开发者不再需要在每次会话开始时重复说明相同背景。

## 第二节

短段落。
"""

    enhanced = enhance_readability_markdown(markdown)

    assert enhanced.count(">   **要点：**") == 1
    assert (
        ">   **要点：** 第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。"
        in enhanced
    )
    assert enhanced.index(">   **要点：**") < enhanced.index("第三段说明解决方向")


def test_enhance_readability_markdown_skips_short_sections_and_is_idempotent() -> None:
    markdown = """## 第一节

第一段较短。

第二段也较短。
"""
    long_markdown = """## 第一节

第一段说明这个系统的背景，它需要在多次会话之间持续保存上下文。

第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。

第三段说明解决方向，项目配置文件可以把这些稳定信息提前写下来。

第四段说明协作方式，多个智能体可以围绕同一套规则分别完成编码、测试和审查。

第五段说明最终收益，开发者不再需要在每次会话开始时重复说明相同背景。
"""

    assert enhance_readability_markdown(markdown) == markdown
    enhanced = enhance_readability_markdown(long_markdown)
    assert enhance_readability_markdown(enhanced) == enhanced


def test_enhance_readability_markdown_ignores_non_plain_paragraph_sources() -> None:
    markdown = """## 第一节

```md
代码块里有很长的一句话，它不应该被抽取成要点卡片，因为代码块必须保持原样。
```

- 列表里有很长的一句话，它不应该被抽取成要点卡片，因为列表是结构化内容。

> 引用里有很长的一句话，它不应该被抽取成要点卡片，因为引用已经是视觉缓冲。

| 字段 | 说明 |
| --- | --- |
| name | 表格里的内容不应该被抽取 |

![配图](image.png)

https://github.com/example/project

第一段说明这个系统的背景，它需要在多次会话之间持续保存上下文。

第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。

第三段说明解决方向，项目配置文件可以把这些稳定信息提前写下来。

第四段说明协作方式，多个智能体可以围绕同一套规则分别完成编码、测试和审查。

第五段说明最终收益，开发者不再需要在每次会话开始时重复说明相同背景。
"""

    enhanced = enhance_readability_markdown(markdown)

    assert enhanced.count(">   **要点：**") == 1
    assert "代码块里有很长的一句话" not in enhanced.split(">   **要点：**", 1)[1].split("\n", 1)[0]
    assert (
        ">   **要点：** 第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。"
        in enhanced
    )


def test_translate_review_render_html_chain_uses_reviewed_markdown_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.stages.render_html import run_render_html

    source = (FIXTURES_DIR / "source.md").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/hooeem/article/2050332284675362853")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="01-source.md",
        content=source,
    )
    monkeypatch.setenv("X2W_MODEL_TRANSLATE", "translate-model")
    monkeypatch.setenv("X2W_MODEL_REVIEW", "review-model")
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    renderer_calls: list[list[str]] = []
    write_metadata_artifact(store, job_id=job.job_id)

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
    gateway = FakeGateway(outputs=[translated_markdown, reviewed_markdown])
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
    html = run_render_html(context=context, store=store)

    translation_path = tmp_path / job.job_id / "02-translation.md"
    reviewed_path = tmp_path / job.job_id / "03-reviewed.md"
    html_path = tmp_path / job.job_id / "11-wechat.html"

    assert translated == translated_markdown
    assert reviewed == reviewed_markdown
    assert translation_path.is_file()
    assert reviewed_path.is_file()
    assert html_path.is_file()
    assert translation_path.read_text(encoding="utf-8") == translated
    assert reviewed_path.read_text(encoding="utf-8") == reviewed
    assert translation_path.read_text(encoding="utf-8").startswith("# 构建可靠的 Agent")
    assert "- 从一个明确的小任务开始。" in translation_path.read_text(encoding="utf-8")
    assert reviewed_path.read_text(encoding="utf-8").count("\n- ") == 3
    assert html == html_path.read_text(encoding="utf-8")
    assert html.lstrip().startswith("<html>")
    assert "<article>" in html
    assert "<h1>构建可靠的 Agent：把大模型工作流做稳</h1>" not in html
    assert "<section># 构建可靠的 Agent" in html
    assert [call["model"] for call in gateway.calls] == ["translate-model", "review-model"]
    assert gateway.calls[0]["system_prompt"] == load_prompt("translate_zh.txt")
    assert gateway.calls[0]["user_prompt"] == build_translate_input(source)
    assert gateway.calls[1]["system_prompt"] == load_prompt("review_zh.txt")
    assert gateway.calls[1]["user_prompt"] == build_review_input(source, translated)
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


def test_final_output_sanitizes_publish_markdown_before_writing_final_artifact(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    reviewed_markdown = """---
title: 最终标题
url: https://example.com/source
requestedUrl: https://example.com/requested
coverImage: https://example.com/cover.png
---

以下是翻译：

# 最终标题

正文第一段。
"""

    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content=reviewed_markdown)
    write_metadata_artifact(store, job_id=job.job_id)
    write_route_artifact(store, job_id=job.job_id, decision="PASS")
    write_final_check_artifact(store, job_id=job.job_id, passed=True)

    final_markdown = run_final_output(
        context=context,
        store=store,
        gateway=FakeGateway(outputs=[]),
        settings=settings,
    )

    assert final_markdown == sanitize_publish_markdown(reviewed_markdown)
    assert final_markdown.startswith("## 最终标题")
    assert "以下是翻译" not in final_markdown
    assert "requestedUrl" not in final_markdown
    assert "coverImage" not in final_markdown
    assert store.read_artifact(job_id=job.job_id, relative_path="10-final.md") == final_markdown


def test_final_check_checks_enhanced_readability_candidate(tmp_path: Path) -> None:
    from agent.stages.final_check import run_final_check

    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    reviewed_markdown = """## 第一节

第一段说明这个系统的背景，它需要在多次会话之间持续保存上下文。

第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。

第三段说明解决方向，项目配置文件可以把这些稳定信息提前写下来。

第四段说明协作方式，多个智能体可以围绕同一套规则分别完成编码、测试和审查。

第五段说明最终收益，开发者不再需要在每次会话开始时重复说明相同背景。
"""
    final_check_response = json.dumps(
        {
            "pass": True,
            "risk": "LOW",
            "fix_required": False,
            "issues": [],
        },
        ensure_ascii=False,
    )

    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content=reviewed_markdown)
    write_metadata_artifact(store, job_id=job.job_id)
    write_route_artifact(store, job_id=job.job_id, decision="PASS")
    gateway = FakeGateway(outputs=[final_check_response])

    run_final_check(context=context, store=store, gateway=gateway, settings=settings)

    candidate = store.read_artifact(job_id=job.job_id, relative_path="07-final-candidate.md")
    assert candidate.count(">   **要点：**") == 1
    assert ">   **要点：**" in gateway.calls[0]["user_prompt"]


def test_targeted_fix_rejects_outputs_that_unquote_reference_urls(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    candidate_markdown = (
        "## 记忆层\n\n"
        "这一思路源自 LLM Wiki。\n\n"
        "> https://github.com/karpathy/llm-wiki——用于保存长期记忆。\n"
    )
    fixed_markdown = (
        "## 记忆层\n\n"
        "这一思路源自 LLM Wiki。\n\n"
        "[llm-wiki](https://github.com/karpathy/llm-wiki)\n"
    )

    store.write_artifact(job_id=job.job_id, relative_path="07-final-candidate.md", content=candidate_markdown)
    write_final_check_artifact(
        store,
        job_id=job.job_id,
        passed=False,
        fix_required=True,
        issues=[
            {
                "type": "cta",
                "severity": "LOW",
                "detail": "删除无关导流话术。",
                "fix_suggestion": "只删除导流句。",
            }
        ],
    )

    output = run_targeted_fix(
        context=context,
        store=store,
        gateway=FakeGateway(outputs=[fixed_markdown, fixed_markdown, fixed_markdown]),
        settings=settings,
    )

    # 定点修复不得把引用块里的来源 URL 移出引用块；当模型输出不满足约束时，pipeline 继续但回退到候选稿。
    assert output == candidate_markdown
    assert store.read_artifact(job_id=job.job_id, relative_path="09-final-fixed.md") == candidate_markdown
    assert "trace.assets/targeted-fix/fallback.json" in store.list_public_artifacts(job_id=job.job_id)

    # `09-final-fixed.md` 会被写入（成功时为修复稿；失败时回退为候选稿），确保后续 final-output 可继续。


def test_targeted_fix_applies_rule_fixes_without_llm_when_issues_are_covered(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    candidate_markdown = (
        "---\n"
        "url: https://x.com/i/article/1\n"
        "requestedUrl: https://x.com/u/article/1\n"
        "title: 夸张标题\n"
        "---\n\n"
        "# 夸张标题\n\n"
        "正文第一段。\n\n"
        "![示意图](https://example.com/a.png)\n"
    )
    store.write_artifact(job_id=job.job_id, relative_path="07-final-candidate.md", content=candidate_markdown)
    write_final_check_artifact(
        store,
        job_id=job.job_id,
        passed=False,
        fix_required=True,
        issues=[
            {
                "type": "元信息泄露",
                "severity": "HIGH",
                "detail": "正文开头存在 YAML 元信息块。",
                "fix_suggestion": "删除 YAML front matter。",
            },
            {
                "type": "图片引用缺乏自然引导语",
                "severity": "LOW",
                "detail": "图片缺少引导语。",
                "fix_suggestion": "每张图前增加一句引导说明。",
            },
        ],
    )

    gateway = FakeGateway(outputs=[])
    output = run_targeted_fix(context=context, store=store, gateway=gateway, settings=settings)

    assert gateway.calls == []
    assert output.startswith("# 夸张标题")
    assert "---\nurl:" not in output
    assert "下图展示了示意图" in output
    assert store.read_artifact(job_id=job.job_id, relative_path="09-final-fixed.md") == output


def test_final_output_preserves_initial_failed_check_and_writes_second_check_separately(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    fixed_markdown = "## 修复后的最终稿\n\n正文。"
    second_check_response = json.dumps(
        {
            "pass": True,
            "risk": "LOW",
            "fix_required": False,
            "issues": [],
        },
        ensure_ascii=False,
    )

    write_metadata_artifact(store, job_id=job.job_id)
    write_route_artifact(store, job_id=job.job_id, decision="LIGHT_POLISH")
    store.write_artifact(job_id=job.job_id, relative_path="05-polished.md", content="## 初始候选稿\n\n正文。")
    write_final_check_artifact(
        store,
        job_id=job.job_id,
        passed=False,
        fix_required=True,
        risk="MEDIUM",
        issues=[
            {
                "type": "format",
                "severity": "MEDIUM",
                "detail": "引用格式需要修复。",
                "fix_suggestion": "只修复引用格式。",
            }
        ],
    )
    store.write_artifact(job_id=job.job_id, relative_path="09-final-fixed.md", content=fixed_markdown)

    final_markdown = run_final_output(
        context=context,
        store=store,
        gateway=FakeGateway(outputs=[second_check_response]),
        settings=settings,
    )

    initial_check = json.loads(store.read_artifact(job_id=job.job_id, relative_path="08-final-check.json"))
    second_check = json.loads(store.read_artifact(job_id=job.job_id, relative_path="final_check_after_fix.json"))
    assert initial_check["pass"] is False
    assert initial_check["fix_required"] is True
    assert second_check["pass"] is True
    assert second_check["fix_required"] is False
    assert final_markdown == sanitize_publish_markdown(fixed_markdown)
    assert store.read_artifact(job_id=job.job_id, relative_path="10-final.md") == final_markdown


def test_final_output_enhances_fixed_markdown_before_second_check_and_final_artifact(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    fixed_markdown = """## 修复后的最终稿

第一段说明这个系统的背景，它需要在多次会话之间持续保存上下文。

第二段说明实际问题，用户每天都会反复解释技术栈、目录结构和部署方式。

第三段说明解决方向，项目配置文件可以把这些稳定信息提前写下来。

第四段说明协作方式，多个智能体可以围绕同一套规则分别完成编码、测试和审查。

第五段说明最终收益，开发者不再需要在每次会话开始时重复说明相同背景。
"""
    second_check_response = json.dumps(
        {
            "pass": True,
            "risk": "LOW",
            "fix_required": False,
            "issues": [],
        },
        ensure_ascii=False,
    )

    write_metadata_artifact(store, job_id=job.job_id)
    write_route_artifact(store, job_id=job.job_id, decision="LIGHT_POLISH")
    store.write_artifact(job_id=job.job_id, relative_path="05-polished.md", content="## 初始候选稿\n\n正文。")
    write_final_check_artifact(
        store,
        job_id=job.job_id,
        passed=False,
        fix_required=True,
        issues=[
            {
                "type": "format",
                "severity": "LOW",
                "detail": "需要定点修复。",
                "fix_suggestion": "只修复指定问题。",
            }
        ],
    )
    store.write_artifact(job_id=job.job_id, relative_path="09-final-fixed.md", content=fixed_markdown)
    gateway = FakeGateway(outputs=[second_check_response])

    final_markdown = run_final_output(
        context=context,
        store=store,
        gateway=gateway,
        settings=settings,
    )

    assert final_markdown.count(">   **要点：**") == 1
    assert ">   **要点：**" in gateway.calls[0]["user_prompt"]
    assert store.read_artifact(job_id=job.job_id, relative_path="10-final.md") == final_markdown


def test_final_output_falls_back_when_iterative_targeted_fix_request_fails(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    job = store.create_job(url="https://x.com/a/status/1")
    context = StageContext(job_id=job.job_id, url=job.url)
    fixed_markdown = "# 如何将 AI 编码费用降低 50%–80%（实操指南）\n\n正文。"
    second_check_response = json.dumps(
        {
            "pass": False,
            "risk": "MEDIUM",
            "fix_required": True,
            "issues": [
                {
                    "type": "标题夸张或偏离正文",
                    "severity": "MEDIUM",
                    "detail": "标题仍需调整。",
                    "fix_suggestion": "继续收敛标题。",
                }
            ],
        },
        ensure_ascii=False,
    )

    class FailingFixGateway:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def generate_markdown(
            self,
            *,
            model: str,
            system_prompt: str,
            user_prompt: str,
            request_timeout_seconds: float | None = None,
        ) -> str:
            del request_timeout_seconds
            self.calls.append(
                {
                    "model": model,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                }
            )
            if len(self.calls) == 1:
                return second_check_response
            raise RuntimeError("Range of input length should be [1, 8192]")

    write_metadata_artifact(store, job_id=job.job_id)
    write_route_artifact(store, job_id=job.job_id, decision="LIGHT_POLISH")
    store.write_artifact(job_id=job.job_id, relative_path="05-polished.md", content="## 初始候选稿\n\n正文。")
    write_final_check_artifact(
        store,
        job_id=job.job_id,
        passed=False,
        fix_required=True,
        risk="MEDIUM",
        issues=[
            {
                "type": "标题夸张或偏离正文",
                "severity": "MEDIUM",
                "detail": "标题过度承诺。",
                "fix_suggestion": "修改标题。",
            }
        ],
    )
    store.write_artifact(job_id=job.job_id, relative_path="09-final-fixed.md", content=fixed_markdown)
    gateway = FailingFixGateway()

    final_markdown = run_final_output(
        context=context,
        store=store,
        gateway=gateway,
        settings=settings,
    )

    assert final_markdown == sanitize_publish_markdown(fixed_markdown)
    assert store.read_artifact(job_id=job.job_id, relative_path="10-final.md") == final_markdown
    fallback_text = (
        store.get_job_dir(job.job_id)
        / "final_output.assets"
        / "targeted-fix"
        / "round-2.fallback.txt"
    ).read_text(encoding="utf-8")
    assert "Range of input length should be [1, 8192]" in fallback_text


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
        relative_path="03-reviewed.md",
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
    assert (tmp_path / job.job_id / "11-wechat.html").read_text(encoding="utf-8") == html
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


def test_render_html_stage_falls_back_to_legacy_final_markdown_when_reviewed_artifact_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.stages.render_html import run_render_html

    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(
        job_id=job.job_id,
        relative_path="10-final.md",
        content="# 旧最终稿\n\n正文",
    )
    context = StageContext(job_id=job.job_id, url=job.url)

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        input_path = Path(command[2])
        output_path = Path(command[3])
        markdown = input_path.read_text(encoding="utf-8")
        output_path.write_text(f"<html><body>{markdown}</body></html>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("agent.stages.render_html.subprocess.run", fake_run)

    html = run_render_html(context=context, store=store)

    assert html == "<html><body># 旧最终稿\n\n正文</body></html>"


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
    probe_calls: list[tuple[str, str]] = []

    class ProbeGateway:
        def probe_model(self, *, model: str, stage: str | None = None) -> str:
            assert stage is not None
            probe_calls.append((stage, model))
            return "OK"

    gateway = ProbeGateway()
    settings = type(
        "SettingsStub",
        (),
        {
            "provider": "openai",
            "stage_models": {
                "translate": "gpt-4.1-mini",
                "review": "gpt-4.1",
            },
            "x_storage_state_path": None,
        },
    )()
    runner = PipelineRunner(store=store, gateway=gateway, settings=settings)
    calls: list[str] = []
    perf_values = iter([10.0, 10.5, 20.0, 21.25, 30.0, 30.75, 40.0, 40.2])

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        assert stage_store is store
        calls.append("x-fetch")
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        write_metadata_artifact(stage_store, job_id=context.job_id, source_type="tweet")
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

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        calls.append("render-html")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="11-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
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
        "render-html",
    ]
    assert probe_calls == [
        ("translate", "gpt-4.1-mini"),
        ("review", "gpt-4.1"),
    ]
    assert set(saved.stage_probes) == {"translate", "review"}
    assert all(probe.status == "passed" for probe in saved.stage_probes.values())
    assert saved.status == "succeeded"
    assert saved.current_stage == "render-html"
    assert saved.started_at is not None
    assert saved.finished_at is not None
    assert saved.stage_errors == {}
    assert saved.stage_models == {
        "x-fetch": StageModelInfo(provider="builtin", model="local:x-fetch"),
        "translate": StageModelInfo(provider="openai", model="gpt-4.1-mini"),
        "review": StageModelInfo(provider="openai", model="gpt-4.1"),
        "render-html": StageModelInfo(provider="builtin", model="local:render-html"),
    }
    assert saved.prompt_versions == {
        "translate": "translate_zh.txt",
        "review": "review_zh.txt",
    }
    assert saved.stage_durations == pytest.approx(
        {
            "x-fetch": 0.5,
            "translate": 1.25,
            "review": 0.75,
            "render-html": 0.2,
        }
    )
    assert store.read_artifact(job_id=job.job_id, relative_path="01-source.md") == "# source"
    assert json.loads(store.read_artifact(job_id=job.job_id, relative_path="metadata.json"))["source_type"] == "tweet"
    assert store.read_artifact(job_id=job.job_id, relative_path="02-translation.md") == "# translation"
    assert store.read_artifact(job_id=job.job_id, relative_path="03-reviewed.md") == "# reviewed"
    assert store.read_artifact(job_id=job.job_id, relative_path="11-wechat.html") == "<html></html>"


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
            suggestion="请查看该任务的 `pipeline.log` 和该阶段输入后再重跑。",
        )
    }
    assert log_path.read_text(encoding="utf-8")
    assert "translate" in log_path.read_text(encoding="utf-8")
    assert "translate exploded" in log_path.read_text(encoding="utf-8")
    assert store.read_artifact(job_id=job.job_id, relative_path="01-source.md") == "# source"
    with pytest.raises(FileNotFoundError):
        store.read_artifact(job_id=job.job_id, relative_path="02-translation.md")


def test_pipeline_runner_marks_connection_errors_retryable_and_preserves_cause_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)

    class APIConnectionError(RuntimeError):
        pass

    class ConnectError(OSError):
        pass

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        error = APIConnectionError("Connection error.")
        error.__cause__ = ConnectError("temporary DNS failure")
        raise error

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)
    log_text = (tmp_path / job.job_id / "logs" / "pipeline.log").read_text(encoding="utf-8")

    assert result.status == "failed"
    assert saved.stage_errors == {
        "translate": StageError(
            error_type="APIConnectionError",
            message="Connection error. (caused by ConnectError: temporary DNS failure)",
            retryable=True,
            suggestion="模型网关连接失败，可检查网络连通性、API Base、代理配置后重试。",
        )
    }
    assert "ConnectError: temporary DNS failure" in log_text


def test_pipeline_runner_marks_x_fetch_empty_body_retryable_with_actionable_hint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.jobs.store import JobStore
    from agent.core.pipeline import PipelineRunner
    from packages.x_fetch.client import XFetchError

    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)

    def fail_x_fetch(_context: StageContext, _stage_store: JobStore) -> str:
        raise XFetchError("原文抓取失败：未解析到有效正文内容")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fail_x_fetch)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert saved.stage_errors["x-fetch"].error_type == "XFetchError"
    assert saved.stage_errors["x-fetch"].retryable is True
    assert "未解析到有效正文内容" in saved.stage_errors["x-fetch"].message
    assert "x-fetch" in saved.stage_errors["x-fetch"].suggestion


def test_pipeline_runner_marks_token_quota_rate_limits_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)

    class RateLimitError(RuntimeError):
        pass

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        raise RateLimitError(
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check your plan and billing details.', "
            "'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}, 'request_id': 'req-1'}"
        )

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert saved.stage_errors == {
        "translate": StageError(
            error_type="RateLimitError",
            message=(
                "Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check your plan and billing details.', "
                "'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}, 'request_id': 'req-1'}"
            ),
            retryable=True,
            suggestion="模型请求触发 Token 消耗限流；请等待约 1 分钟后重试，或缩短输入、拆分任务、降低并发，必要时在百炼控制台提升该模型的 TPM 限额。",
        )
    }


def test_pipeline_runner_marks_clear_billing_rate_limits_non_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)

    class RateLimitError(RuntimeError):
        pass

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        raise RateLimitError(
            "Error code: 429 - {'error': {'message': 'Free allocated quota exceeded.', "
            "'code': 'insufficient_quota'}, 'request_id': 'req-1'}"
        )

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert saved.stage_errors == {
        "translate": StageError(
            error_type="RateLimitError",
            message=(
                "Error code: 429 - {'error': {'message': 'Free allocated quota exceeded.', "
                "'code': 'insufficient_quota'}, 'request_id': 'req-1'}"
            ),
            retryable=False,
            suggestion="模型额度已用尽或账户计费异常，请检查套餐、余额或 Billing 状态后再重试。",
        )
    }


def test_pipeline_runner_explains_light_polish_connection_errors_with_stage_model_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(
        api_key="test-key",
        artifacts_dir=str(tmp_path),
        provider="openai",
        model_translate="gpt-4.1-mini",
        model_review="qwen-mt-plus",
    )
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)

    class APIConnectionError(RuntimeError):
        pass

    class RemoteProtocolError(OSError):
        pass

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        stage_store.write_artifact(
            job_id=context.job_id,
            relative_path="01-source.md",
            content="# source",
        )
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(job_id=context.job_id, relative_path="02-translation.md", content="# translation")
        return "# translation"

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content="# reviewed")
        return "# reviewed"

    def fake_route(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        write_json_artifact(
            store=store,
            job_id=context.job_id,
            relative_path="04-route.json",
            payload={
                "decision": "LIGHT_POLISH",
                "reason": "needs small polish",
                "risk": "LOW",
                "recommended_next_prompt": "LIGHT_POLISH",
            },
        )
        return "LIGHT_POLISH"

    def fake_light_polish(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        error = APIConnectionError("Connection error.")
        error.__cause__ = RemoteProtocolError("Server disconnected without sending a response.")
        raise error

    def fail_if_called(**_: object) -> str:
        raise AssertionError("later stages must not run after light-polish connection failure")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_route", fake_route)
    monkeypatch.setattr("agent.core.pipeline.run_light_polish", fake_light_polish)
    monkeypatch.setattr("agent.core.pipeline.run_final_check", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_targeted_fix", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_final_output", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fail_if_called)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert saved.stage_errors == {
        "light-polish": StageError(
            error_type="APIConnectionError",
            message=(
                "Connection error. (caused by RemoteProtocolError: "
                "Server disconnected without sending a response.)"
            ),
            retryable=True,
            suggestion=(
                "轻编辑阶段当前使用模型 qwen-mt-plus。"
                "请优先检查该模型的可用性、API Base、代理配置后重试。"
            ),
        )
    }


def test_pipeline_runner_fails_before_stage_execution_when_preflight_probe_breaks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    probe_calls: list[tuple[str, str]] = []

    class APIConnectionError(RuntimeError):
        pass

    class ProbeGateway:
        def probe_model(self, *, model: str, stage: str | None = None) -> str:
            assert stage is not None
            probe_calls.append((stage, model))
            if stage == "light-polish":
                raise APIConnectionError("preflight probe failed")
            return "OK"

    settings = type(
        "SettingsStub",
        (),
        {
            "provider": "qwen",
            "stage_models": {
                "translate": "qwen-mt-plus",
                "review": "qwen-mt-plus",
                "route": "qwen-mt-plus",
                "final-check": "qwen-mt-plus",
                "light-polish": "qwen-mt-plus",
                "targeted-fix": "qwen-mt-plus",
            },
            "x_storage_state_path": None,
        },
    )()
    runner = PipelineRunner(store=store, gateway=ProbeGateway(), settings=settings)
    calls: list[str] = []

    def fake_x_fetch(context: StageContext, stage_store: JobStore) -> str:
        calls.append("x-fetch")
        stage_store.write_artifact(job_id=context.job_id, relative_path="01-source.md", content="# source")
        return "# source"

    def fake_translate(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("translate")
        store.write_artifact(job_id=context.job_id, relative_path="02-translation.md", content="# translation")
        return "# translation"

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("review")
        store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content="# reviewed")
        return "# reviewed"

    def fake_route(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("route")
        write_route_artifact(store, job_id=context.job_id, decision="LIGHT_POLISH")
        return "LIGHT_POLISH"

    def fail_if_called(**_: object) -> str:
        raise AssertionError("light-polish stage body must not run after probe failure")

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_route", fake_route)
    monkeypatch.setattr("agent.core.pipeline.run_light_polish", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_final_check", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_targeted_fix", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_final_output", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fail_if_called)

    job = runner.create_job("https://x.com/a/status/1")
    result = runner.run(job.job_id)
    saved = store.read_job(job.job_id)

    assert result.status == "failed"
    assert calls == ["x-fetch", "translate", "review", "route"]
    assert probe_calls == [
        ("translate", "qwen-mt-plus"),
        ("review", "qwen-mt-plus"),
        ("route", "qwen-mt-plus"),
        ("light-polish", "qwen-mt-plus"),
    ]
    assert saved.current_stage == "light-polish"
    assert saved.stage_probes["light-polish"].status == "failed"
    assert saved.stage_probes["light-polish"].message == "preflight probe failed"
    assert saved.stage_errors == {
        "light-polish": StageError(
            error_type="APIConnectionError",
            message="preflight probe failed",
            retryable=True,
            suggestion="轻编辑阶段当前使用模型 qwen-mt-plus。请优先检查该模型的可用性、API Base、代理配置后重试。",
        )
    }


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


def test_pipeline_runner_retry_runs_tail_only_from_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)
    job = store.create_job(url="https://x.com/a/status/1")
    perf_values = iter([10.0, 10.4, 20.0, 20.2])

    store.write_artifact(job_id=job.job_id, relative_path="01-source.md", content="# source\n")
    store.write_artifact(job_id=job.job_id, relative_path="02-translation.md", content="# translation\n")
    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content="# stale reviewed\n")
    write_metadata_artifact(store, job_id=job.job_id)
    store.write_artifact(job_id=job.job_id, relative_path="11-wechat.html", content="<html>stale</html>")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")
    store.update_status(job_id=job.job_id, status="failed", current_stage="review")

    calls: list[str] = []

    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("stages before retry start must not run")

    def fake_review(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("review")
        store.write_artifact(job_id=context.job_id, relative_path="03-reviewed.md", content="# reviewed\n")
        return "# reviewed\n"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        calls.append("render-html")
        store.write_artifact(job_id=context.job_id, relative_path="11-wechat.html", content="<html>fresh</html>")
        return "<html>fresh</html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)
    monkeypatch.setattr("agent.core.pipeline.perf_counter", lambda: next(perf_values))

    result = runner.retry(job.job_id, stage="review", mode="failed-stage")
    saved = store.read_job(job.job_id)

    assert result.status == "succeeded"
    assert calls == ["review", "render-html"]
    assert saved.status == "succeeded"
    assert saved.current_stage == "render-html"
    assert saved.stage_durations == pytest.approx(
        {
            "review": 0.4,
            "render-html": 0.2,
        }
    )
    assert store.read_artifact(job_id=job.job_id, relative_path="01-source.md") == "# source\n"
    assert store.read_artifact(job_id=job.job_id, relative_path="02-translation.md") == "# translation\n"
    assert store.read_artifact(job_id=job.job_id, relative_path="03-reviewed.md") == "# reviewed\n"
    assert store.read_artifact(job_id=job.job_id, relative_path="11-wechat.html") == "<html>fresh</html>"


def test_pipeline_runner_retry_rejects_failed_stage_mode_when_stage_does_not_match(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(
        store=store,
        gateway=object(),
        settings=Settings(api_key="test-key", artifacts_dir=str(tmp_path)),
    )
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="failed", current_stage="render-html")

    with pytest.raises(ValueError, match="failed current_stage"):
        runner.retry(job.job_id, stage="review", mode="failed-stage")


def test_pipeline_runner_retry_rejects_from_stage_for_pending_job(
    tmp_path: Path,
) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(
        store=store,
        gateway=object(),
        settings=Settings(api_key="test-key", artifacts_dir=str(tmp_path)),
    )
    job = store.create_job(url="https://x.com/a/status/1")

    with pytest.raises(ValueError, match="must not be pending"):
        runner.retry(job.job_id, stage="review", mode="from-stage")


def test_pipeline_runner_retry_from_render_html_only_reruns_render_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)
    job = store.create_job(url="https://x.com/a/status/1")
    perf_values = iter([40.0, 40.5])

    store.write_artifact(job_id=job.job_id, relative_path="01-source.md", content="# source\n")
    store.write_artifact(job_id=job.job_id, relative_path="02-translation.md", content="# translation\n")
    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content="# reviewed\n")
    write_metadata_artifact(store, job_id=job.job_id)
    store.write_artifact(job_id=job.job_id, relative_path="11-wechat.html", content="<html>stale</html>")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="succeeded", current_stage="render-html")

    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("stages before render-html must not run")

    render_calls: list[str] = []

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        render_calls.append("render-html")
        store.write_artifact(job_id=context.job_id, relative_path="11-wechat.html", content="<html>rerendered</html>")
        return "<html>rerendered</html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_review", fail_if_called)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)
    monkeypatch.setattr("agent.core.pipeline.perf_counter", lambda: next(perf_values))

    result = runner.retry(job.job_id, stage="render-html", mode="from-stage")
    saved = store.read_job(job.job_id)

    assert result.status == "succeeded"
    assert render_calls == ["render-html"]
    assert saved.current_stage == "render-html"
    assert saved.stage_durations == pytest.approx({"render-html": 0.5})
    assert store.read_artifact(job_id=job.job_id, relative_path="03-reviewed.md") == "# reviewed\n"
    assert store.read_artifact(job_id=job.job_id, relative_path="11-wechat.html") == "<html>rerendered</html>"


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
        write_metadata_artifact(stage_store, job_id=context.job_id)
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

    def fake_route(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("route")
        write_route_artifact(store, job_id=context.job_id, decision="PASS")
        return "PASS"

    def fake_light_polish(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("light-polish")
        store.write_artifact(job_id=context.job_id, relative_path="05-polished.md", content="# polished")
        return "# polished"

    def fake_final_check(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("final-check")
        store.write_artifact(job_id=context.job_id, relative_path="07-final-candidate.md", content="# candidate")
        write_final_check_artifact(store, job_id=context.job_id, passed=True)
        return '{"pass": true}'

    def fake_targeted_fix(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("targeted-fix")
        store.write_artifact(job_id=context.job_id, relative_path="09-final-fixed.md", content="## fixed")
        return "## fixed"

    def fake_final_output(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        calls.append("final-output")
        store.write_artifact(job_id=context.job_id, relative_path="10-final.md", content="## final")
        return "## final"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        calls.append("render-html")
        store.write_artifact(
            job_id=context.job_id,
            relative_path="11-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_route", fake_route)
    monkeypatch.setattr("agent.core.pipeline.run_light_polish", fake_light_polish)
    monkeypatch.setattr("agent.core.pipeline.run_final_check", fake_final_check)
    monkeypatch.setattr("agent.core.pipeline.run_targeted_fix", fake_targeted_fix)
    monkeypatch.setattr("agent.core.pipeline.run_final_output", fake_final_output)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)

    job = runner.create_job("https://x.com/a/status/1")
    claim_token = store.claim_run(job_id=job.job_id)

    original_consume_run_claim = store.consume_run_claim

    def tracking_consume_run_claim(*, job_id: str, claim_token: str) -> None:
        current = store.read_job(job_id)
        assert current.status == "running"
        assert current.current_stage == "x-fetch"
        assert current.started_at is not None
        assert (tmp_path / job_id / ".run-claim").is_file()

        with pytest.raises(ValueError, match="must be pending"):
            store.claim_run(job_id=job_id)

        original_consume_run_claim(job_id=job_id, claim_token=claim_token)

    monkeypatch.setattr(store, "consume_run_claim", tracking_consume_run_claim)

    result = runner.run(job.job_id, claim_token)

    assert result.status == "succeeded"
    assert calls == [
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
        write_metadata_artifact(stage_store, job_id=context.job_id)
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

    def fake_route(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        write_route_artifact(store, job_id=context.job_id, decision="LIGHT_POLISH")
        return "LIGHT_POLISH"

    def fake_light_polish(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="05-polished.md",
            content="# polished",
        )
        return "# polished"

    def fake_final_check(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="07-final-candidate.md",
            content="# candidate",
        )
        write_final_check_artifact(store, job_id=context.job_id, passed=False, fix_required=True, issues=[
            {
                "type": "fix",
                "severity": "MEDIUM",
                "detail": "需要修复。",
                "fix_suggestion": "按问题修。",
            }
        ])
        return '{"pass": false}'

    def fake_targeted_fix(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="09-final-fixed.md",
            content="## fixed",
        )
        return "## fixed"

    def fake_final_output(*, context: StageContext, store: JobStore, gateway: object, settings: object) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="10-final.md",
            content="## final",
        )
        return "## final"

    def fake_render_html(*, context: StageContext, store: JobStore) -> str:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="11-wechat.html",
            content="<html></html>",
        )
        return "<html></html>"

    monkeypatch.setattr("agent.core.pipeline.run_x_fetch", fake_x_fetch)
    monkeypatch.setattr("agent.core.pipeline.run_translate", fake_translate)
    monkeypatch.setattr("agent.core.pipeline.run_review", fake_review)
    monkeypatch.setattr("agent.core.pipeline.run_route", fake_route)
    monkeypatch.setattr("agent.core.pipeline.run_light_polish", fake_light_polish)
    monkeypatch.setattr("agent.core.pipeline.run_final_check", fake_final_check)
    monkeypatch.setattr("agent.core.pipeline.run_targeted_fix", fake_targeted_fix)
    monkeypatch.setattr("agent.core.pipeline.run_final_output", fake_final_output)
    monkeypatch.setattr("agent.core.pipeline.run_render_html", fake_render_html)

    job = runner.create_job("https://x.com/a/status/1")

    result = runner.run(job.job_id)
    job_dir = tmp_path / job.job_id

    assert result.status == "succeeded"
    assert (job_dir / "01-source.md").is_file()
    assert (job_dir / "02-translation.md").is_file()
    assert (job_dir / "03-reviewed.md").is_file()
    assert (job_dir / "04-route.json").is_file()
    assert (job_dir / "05-polished.md").is_file()
    assert (job_dir / "07-final-candidate.md").is_file()
    assert (job_dir / "08-final-check.json").is_file()
    assert (job_dir / "09-final-fixed.md").is_file()
    assert (job_dir / "10-final.md").is_file()
    assert (job_dir / "11-wechat.html").is_file()
    assert (job_dir / "metadata.json").is_file()


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

    assert saved.status == "failed"
    assert saved.current_stage == "x-fetch"


def test_job_store_reads_legacy_jobs_after_wechat_rewrite_stage_removal(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    payload = json.loads((tmp_path / job.job_id / "job.json").read_text(encoding="utf-8"))

    payload.update(
        {
            "status": "failed",
            "current_stage": "wechat-rewrite",
            "started_at": "2026-05-08T16:00:00+00:00",
            "finished_at": "2026-05-08T16:10:00+00:00",
            "stage_models": {
                **payload.get("stage_models", {}),
                "wechat-rewrite": {"provider": "qwen", "model": "qwen-plus"},
            },
            "prompt_versions": {
                **payload.get("prompt_versions", {}),
                "wechat-rewrite": "wechat_rewrite_zh.txt",
            },
            "stage_durations": {
                **payload.get("stage_durations", {}),
                "wechat-rewrite": 12.5,
            },
            "stage_probes": {
                **payload.get("stage_probes", {}),
                "wechat-rewrite": {
                    "status": "passed",
                    "message": "OK",
                    "checked_at": "2026-05-08T15:59:00+00:00",
                },
            },
        }
    )

    raw_payload = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (tmp_path / job.job_id / "job.json").write_text(raw_payload, encoding="utf-8")
    with store._connect_db() as conn:
        conn.execute("UPDATE jobs SET payload = ? WHERE job_id = ?", (raw_payload, job.job_id))

    loaded = store.read_job(job.job_id)
    listed = store.list_jobs(limit=10)

    assert loaded.current_stage == "light-polish"
    assert "wechat-rewrite" not in loaded.stage_models
    assert "wechat-rewrite" not in loaded.prompt_versions
    assert "wechat-rewrite" not in loaded.stage_durations
    assert "wechat-rewrite" not in loaded.stage_probes
    assert any(record.job_id == job.job_id for record in listed)
    assert loaded.started_at is not None
    assert loaded.finished_at is not None
    assert loaded.stage_models == {}
    assert loaded.prompt_versions == {}
    assert loaded.stage_durations == {}
    assert loaded.stage_errors == {}


def test_fetch_x_markdown_with_skill_copies_downloaded_media_and_rewrites_links(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "skill-output"
    output_dir.mkdir()
    markdown_path = output_dir / "article.md"
    markdown_path.write_text(
        "---\n"
        'requestedUrl: "https://x.com/i/article/123"\n'
        'coverImage: "imgs/chart.jpg"\n'
        'heroImage:    imgs/chart.jpg\n'
        "---\n\n"
        "![](imgs/chart.jpg)\n\n"
        "[demo](videos/demo.mp4)\n",
        encoding="utf-8",
    )

    image_dir = output_dir / "imgs"
    image_dir.mkdir()
    (image_dir / "chart.jpg").write_bytes(b"image-bytes")

    video_dir = output_dir / "videos"
    video_dir.mkdir()
    (video_dir / "demo.mp4").write_bytes(b"video-bytes")

    script_path = tmp_path / "main.ts"
    script_path.write_text("console.log('stub')\n", encoding="utf-8")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"markdownPath": "article.md"}),
            stderr="",
        )

    monkeypatch.setattr("packages.x_fetch.client.X_TO_MARKDOWN_SKILL_SCRIPT", script_path)
    monkeypatch.setattr("packages.x_fetch.client.shutil.which", lambda name: "/usr/bin/bun")
    monkeypatch.setattr("packages.x_fetch.client.subprocess.run", fake_run)

    markdown = fetch_x_markdown_with_skill(
        "https://x.com/someone/article/123",
        output_dir=output_dir,
        media_output_dir=tmp_path / "job-assets",
        media_link_prefix="01-source.assets",
    )

    assert 'requestedUrl: "https://x.com/someone/article/123"' in markdown
    assert 'coverImage: "01-source.assets/imgs/chart.jpg"' in markdown
    assert "heroImage:    01-source.assets/imgs/chart.jpg" in markdown
    assert "![](01-source.assets/imgs/chart.jpg)" in markdown
    assert "[demo](01-source.assets/videos/demo.mp4)" in markdown
    assert (tmp_path / "job-assets" / "imgs" / "chart.jpg").read_bytes() == b"image-bytes"
    assert (tmp_path / "job-assets" / "videos" / "demo.mp4").read_bytes() == b"video-bytes"
