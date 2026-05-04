from __future__ import annotations

import re

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext
from agent.stages.helpers import is_substantially_shorter, load_final_check_result

URL_PATTERN = re.compile(r"https?://[^\s)>，。；、\]》）—]+")


def build_targeted_fix_input(candidate_markdown: str, issues_json: str) -> str:
    return (
        "请根据 Final Check issues 对下面文章做定点修复，只修复明确指出的问题。\n\n"
        f"【候选最终稿】\n{candidate_markdown}\n\n"
        f"【Final Check Issues】\n{issues_json}"
    )


def _blockquote_payloads(markdown: str) -> list[str]:
    payloads: list[str] = []
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(">"):
            continue

        payload = stripped[1:].strip()
        if payload:
            payloads.append(payload)
    return payloads


def _blockquote_url_set(markdown: str) -> set[str]:
    urls: set[str] = set()
    for payload in _blockquote_payloads(markdown):
        urls.update(URL_PATTERN.findall(payload))
    return urls


def _assert_blockquotes_preserved(candidate_markdown: str, fixed_markdown: str) -> None:
    candidate_payloads = _blockquote_payloads(candidate_markdown)
    if not candidate_payloads:
        return

    fixed_payloads = _blockquote_payloads(fixed_markdown)
    if len(fixed_payloads) < len(candidate_payloads):
        raise ValueError(
            "Targeted fix changed blockquote formatting; refusing to publish because quoted references must stay quoted."
        )

    candidate_urls = _blockquote_url_set(candidate_markdown)
    fixed_urls = _blockquote_url_set(fixed_markdown)
    missing_urls = sorted(candidate_urls - fixed_urls)
    if missing_urls:
        raise ValueError(
            "Targeted fix changed blockquote URL formatting; refusing to publish because quoted references must stay quoted."
        )


def run_targeted_fix(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    final_check = load_final_check_result(store=store, job_id=context.job_id)
    candidate_markdown = store.read_artifact(job_id=context.job_id, relative_path="07-final-candidate.md")
    if final_check.pass_ or not final_check.fix_required:
        return candidate_markdown

    issues_json = store.read_artifact(job_id=context.job_id, relative_path="08-final-check.json")
    fixed_markdown = gateway.generate_markdown(
        model=settings.stage_models["targeted-fix"],
        system_prompt=load_prompt("targeted_fix_zh.txt"),
        user_prompt=build_targeted_fix_input(candidate_markdown, issues_json),
    )
    if is_substantially_shorter(candidate_markdown, fixed_markdown, min_ratio=0.85):
        raise ValueError("Targeted fix output appears truncated compared with final candidate; refusing to overwrite with a shortened draft.")
    _assert_blockquotes_preserved(candidate_markdown, fixed_markdown)
    store.write_artifact(
        job_id=context.job_id,
        relative_path="09-final-fixed.md",
        content=fixed_markdown,
    )
    return fixed_markdown
