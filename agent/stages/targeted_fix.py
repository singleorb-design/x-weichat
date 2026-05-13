from __future__ import annotations

import json
import re

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext
from agent.stages.helpers import (
    count_markdown_features,
    dump_json,
    extract_frontmatter,
    load_final_check_result,
    now_iso,
    write_diff_asset,
    write_model_exchange_assets,
)

URL_PATTERN = re.compile(r"https?://[^\s)>，。；、\]》）—]+")
HEADING_PATTERN = re.compile(r"(?m)^#{2,6}\s+(.+)$")
IMAGE_PATTERN = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def build_targeted_fix_input(candidate_markdown: str, issues_json: str) -> str:
    return (
        "请根据 Final Check issues 对下面文章做定点修复，只修复明确指出的问题。\n\n"
        f"【候选最终稿】\n{candidate_markdown}\n\n"
        f"【Final Check Issues】\n{issues_json}"
    )


def _issue_type_set(issues) -> set[str]:
    return {getattr(issue, "type", "").strip() for issue in issues if getattr(issue, "type", "").strip()}


def _first_issue_by_type(issues, issue_type: str):
    for issue in issues:
        if getattr(issue, "type", "").strip() == issue_type:
            return issue
    return None


def _remove_yaml_frontmatter_if_present(markdown: str) -> tuple[str, bool]:
    frontmatter, body = extract_frontmatter(markdown)
    if not frontmatter:
        return markdown, False
    if body == markdown:
        return markdown, False
    return body.strip() + "\n", True


def _looks_like_image_leadin(line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return False
    if "下图" in normalized or "如下图" in normalized or "见下图" in normalized:
        return True
    if normalized.endswith((":", "：")):
        return True
    return False


def _add_image_leadins(markdown: str) -> tuple[str, int]:
    """为缺乏上下文引导的图片引用增加一句引导语。

    规则目标：改善阅读连贯性；不引入新事实，只复用图片 alt 文本。
    """

    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    out: list[str] = []
    inserted = 0
    in_fence = False

    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        match = IMAGE_PATTERN.match(line.strip())
        if not match:
            out.append(line)
            continue

        alt_text = match.group(1).strip()
        # 找到上一条“可见文本行”（忽略空行），用于判断是否已有引导语。
        prev_text = ""
        for prev in reversed(out):
            if prev.strip():
                prev_text = prev
                break

        if prev_text and _looks_like_image_leadin(prev_text):
            out.append(line)
            continue

        leadin = (
            f"下图展示了{alt_text}：" if alt_text else "下图展示了相关示意："
        )

        # 确保引导语与图片之间有一行空行，避免黏连。
        if out and out[-1].strip():
            out.append("")
        out.append(leadin)
        out.append("")
        out.append(line)
        inserted += 1

    return "\n".join(out).strip() + "\n", inserted


def _extract_suggested_title(issue) -> str | None:
    suggestion = str(getattr(issue, "fix_suggestion", "") or "").strip()
    if not suggestion:
        return None

    # 兼容示例格式：例如：'xxx'
    for pattern in [r"['“](.{8,120}?)['”]", r"《(.{8,120}?)》", r"\"(.{8,120}?)\""]:
        match = re.search(pattern, suggestion)
        if match:
            return match.group(1).strip()
    return None


def _soften_title(markdown: str, *, issue) -> tuple[str, bool]:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()

    title_index = None
    for idx, line in enumerate(lines):
        if re.match(r"^#\s+\S", line):
            title_index = idx
            break
    if title_index is None:
        return markdown, False

    old_title = re.sub(r"^#\s+", "", lines[title_index]).strip()
    new_title = _extract_suggested_title(issue)
    if not new_title:
        # 保守兜底：去掉高风险/夸张修饰，尽量不改变核心语义。
        new_title = old_title
        new_title = re.sub(r"\b24\s*/\s*7\b", "", new_title, flags=re.IGNORECASE)
        new_title = new_title.replace("全天候", "").replace("完整指南", "")
        new_title = re.sub(r"[（(][^）)]*(开源|完整|指南|仓库|Repos?)[^）)]*[）)]", "", new_title)
        new_title = re.sub(r"\s{2,}", " ", new_title).strip(" -—:：")

    if not new_title or new_title == old_title:
        return markdown, False

    lines[title_index] = f"# {new_title}"
    return "\n".join(lines).strip() + "\n", True


def _dedupe_repeated_blocks(markdown: str) -> tuple[str, int]:
    """删除重复段落（严格相同的块），避免误删改写内容。"""

    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", normalized.strip())
    seen: set[str] = set()
    kept: list[str] = []
    removed = 0

    for block in blocks:
        raw = block.strip()
        if not raw:
            continue
        # 保护标题/小标题/代码块
        if raw.startswith("#") or "```" in raw:
            kept.append(raw)
            continue
        key = re.sub(r"\s+", " ", raw)
        if len(key) < 120:
            kept.append(raw)
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(raw)

    return "\n\n".join(kept).strip() + "\n", removed


def _remove_ai_cta_lines(markdown: str) -> tuple[str, int]:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    out: list[str] = []
    removed = 0
    in_fence = False

    cta_patterns = [
        r"^(你现在的|你目前的).{0,80}[？?]\s*$",
        r"^(关注我|点赞|收藏|转发|私信|下期|下篇|求赞|求转).*$",
    ]
    cta_re = re.compile("|".join(f"(?:{p})" for p in cta_patterns))

    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        if cta_re.match(line.strip()):
            removed += 1
            continue
        out.append(line)

    return "\n".join(out).strip() + "\n", removed


def apply_rule_fixes(*, candidate_markdown: str, issues) -> tuple[str, list[dict[str, object]]]:
    """对常见 issues 做确定性修复。

    返回：修复后的 markdown + 规则应用记录（用于 trace）。
    """

    issue_types = _issue_type_set(issues)
    rules_applied: list[dict[str, object]] = []
    current = candidate_markdown

    if "元信息泄露" in issue_types:
        current, changed = _remove_yaml_frontmatter_if_present(current)
        rules_applied.append({"rule": "remove_frontmatter", "applied": changed})

    if "标题夸张或偏离正文" in issue_types:
        issue = _first_issue_by_type(issues, "标题夸张或偏离正文")
        current, changed = _soften_title(current, issue=issue)
        rules_applied.append({"rule": "soften_title", "applied": changed})

    if "重复段落" in issue_types:
        current, removed = _dedupe_repeated_blocks(current)
        rules_applied.append({"rule": "dedupe_sections", "applied": removed > 0, "removed": removed})

    if "AI 痕迹检查" in issue_types:
        current, removed = _remove_ai_cta_lines(current)
        rules_applied.append({"rule": "remove_ai_cta_or_convert", "applied": removed > 0, "removed": removed})

    if "图片引用缺乏自然引导语" in issue_types:
        current, inserted = _add_image_leadins(current)
        rules_applied.append({"rule": "add_image_leadin", "applied": inserted > 0, "inserted": inserted})

    return current, rules_applied


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
    """确保“引用来源”仍以引用块形式保留。

    定点修复会被要求删除某些引用块（例如 `> **要点：** ...` 这种强调句式），
    因此不能再用“引用块数量不能减少”做硬约束。

    我们真正需要保护的是：候选稿中那些放在引用块里的 URL（通常是来源/脚注）
    必须仍然出现在引用块里，不能被移出引用块或丢失。
    """

    candidate_urls = _blockquote_url_set(candidate_markdown)
    if not candidate_urls:
        return

    fixed_urls = _blockquote_url_set(fixed_markdown)
    missing_urls = sorted(candidate_urls - fixed_urls)
    if missing_urls:
        raise ValueError(
            "Targeted fix changed blockquote URL formatting; refusing to publish because quoted references must stay quoted."
        )


def _last_heading_text(markdown: str) -> str | None:
    matches = HEADING_PATTERN.findall(markdown)
    return matches[-1].strip() if matches else None


def _should_flag_truncation(candidate_markdown: str, fixed_markdown: str) -> tuple[bool, str]:
    """判定定点修复输出是否像“被截断”。

    注意：定点修复合法场景会删除 YAML frontmatter、导流话术等内容，
    纯粹用长度比例容易误伤；因此这里改为“结构保真”为主、长度为辅。
    """

    _candidate_frontmatter, candidate_body = extract_frontmatter(candidate_markdown)
    _fixed_frontmatter, fixed_body = extract_frontmatter(fixed_markdown)

    candidate_body = candidate_body.strip()
    fixed_body = fixed_body.strip()
    if not candidate_body:
        return False, ""

    candidate_stats = count_markdown_features(candidate_markdown)
    fixed_stats = count_markdown_features(fixed_markdown)

    signals: list[str] = []
    min_body_ratio = 0.7
    if len(fixed_body) < len(candidate_body) * min_body_ratio:
        signals.append(f"length<{min_body_ratio:.2f}")

    if fixed_stats.get("code_fences", 0) < candidate_stats.get("code_fences", 0):
        signals.append("code_fences")

    if fixed_stats.get("headings", 0) < max(1, int(candidate_stats.get("headings", 0) * 0.6)):
        signals.append("headings")

    last_heading = _last_heading_text(candidate_markdown)
    if last_heading and last_heading not in fixed_markdown:
        signals.append("tail_heading")

    # 只有“明显变短”同时伴随结构缺失，才认为是截断。
    is_truncated = "length<0.70" in signals and any(
        signal in signals for signal in ("code_fences", "tail_heading")
    )
    return is_truncated, ",".join(signals)


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
        store.write_artifact(
            job_id=context.job_id,
            relative_path="09-final-fixed.md",
            content=candidate_markdown,
        )
        return candidate_markdown

    issues_json = store.read_artifact(job_id=context.job_id, relative_path="08-final-check.json")

    # 1) Rule-first deterministic fixes.
    rule_fixed_markdown, rule_records = apply_rule_fixes(
        candidate_markdown=candidate_markdown,
        issues=final_check.issues,
    )
    store.write_public_asset(
        job_id=context.job_id,
        relative_path="trace.assets/targeted-fix/rules.json",
        content=dump_json(
            {
                "checked_at": now_iso(),
                "issue_types": sorted(_issue_type_set(final_check.issues)),
                "rules": rule_records,
            }
        ),
    )

    # 规则修复产物先落盘，避免 LLM 卡住导致没有可用输出。
    store.write_artifact(
        job_id=context.job_id,
        relative_path="09-final-fixed.md",
        content=rule_fixed_markdown,
    )
    write_diff_asset(
        store=store,
        job_id=context.job_id,
        relative_path="diff.assets/targeted-fix/07-final-candidate_vs_09-final-fixed.rules.patch",
        before=candidate_markdown,
        after=rule_fixed_markdown,
        from_label="07-final-candidate.md",
        to_label="09-final-fixed.md (rules)",
    )

    # 判断是否需要 LLM 兜底。
    supported_issue_types = {
        "元信息泄露",
        "标题夸张或偏离正文",
        "重复段落",
        "AI 痕迹检查",
        "图片引用缺乏自然引导语",
    }
    issue_types = _issue_type_set(final_check.issues)
    has_uncovered = bool(issue_types - supported_issue_types)
    has_unapplied_rule = any(
        rec.get("applied") is False
        and rec.get("rule")
        in {
            "remove_frontmatter",
            "soften_title",
            "dedupe_sections",
            "remove_ai_cta_or_convert",
            "add_image_leadin",
        }
        for rec in rule_records
    )
    needs_llm = has_uncovered or has_unapplied_rule
    if not settings.targeted_fix_enable_llm_fallback or not needs_llm:
        write_diff_asset(
            store=store,
            job_id=context.job_id,
            relative_path="diff.assets/targeted-fix/07-final-candidate_vs_09-final-fixed.patch",
            before=candidate_markdown,
            after=rule_fixed_markdown,
            from_label="07-final-candidate.md",
            to_label="09-final-fixed.md",
        )
        return rule_fixed_markdown

    prompt = load_prompt("targeted_fix_zh.txt")
    user_prompt = build_targeted_fix_input(rule_fixed_markdown, issues_json)
    model = settings.stage_models["targeted-fix"]

    last_error: str | None = None
    max_attempts = settings.targeted_fix_max_attempts
    for attempt in range(1, max_attempts + 1):
        call_id = f"attempt-{attempt}"
        write_model_exchange_assets(
            store=store,
            job_id=context.job_id,
            stage="targeted-fix",
            call_id=call_id,
            model=model,
            system_prompt=prompt,
            user_prompt=user_prompt,
            raw_response=None,
        )

        try:
            fixed_markdown = gateway.generate_markdown(
                model=model,
                system_prompt=prompt,
                user_prompt=user_prompt,
                request_timeout_seconds=settings.targeted_fix_timeout_seconds,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/llm.{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            continue

        write_model_exchange_assets(
            store=store,
            job_id=context.job_id,
            stage="targeted-fix",
            call_id=call_id,
            model=model,
            system_prompt=prompt,
            user_prompt=user_prompt,
            raw_response=fixed_markdown,
        )

        is_truncated, signals = _should_flag_truncation(rule_fixed_markdown, fixed_markdown)
        if is_truncated:
            last_error = (
                "Targeted fix output appears truncated compared with final candidate; "
                f"skipping this attempt (signals={signals})."
            )
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/llm.{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            continue

        try:
            _assert_blockquotes_preserved(rule_fixed_markdown, fixed_markdown)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"trace.assets/targeted-fix/llm.{call_id}.error.txt",
                content=f"checked_at: {now_iso()}\nerror: {last_error}\n",
            )
            continue

        store.write_artifact(
            job_id=context.job_id,
            relative_path="09-final-fixed.md",
            content=fixed_markdown,
        )
        write_diff_asset(
            store=store,
            job_id=context.job_id,
            relative_path="diff.assets/targeted-fix/07-final-candidate_vs_09-final-fixed.patch",
            before=candidate_markdown,
            after=fixed_markdown,
            from_label="07-final-candidate.md",
            to_label="09-final-fixed.md",
        )
        write_diff_asset(
            store=store,
            job_id=context.job_id,
            relative_path="diff.assets/targeted-fix/09-final-fixed.rules_vs_llm.patch",
            before=rule_fixed_markdown,
            after=fixed_markdown,
            from_label="09-final-fixed.md (rules)",
            to_label="09-final-fixed.md (llm)",
        )
        return fixed_markdown

    # 所有尝试都不可用：不让 pipeline 因定点修复失败而中断。
    fallback_note = {
        "checked_at": now_iso(),
        "reason": last_error or "unknown",
        "attempted": max_attempts,
        "behavior": "fall back to rule_fixed_markdown and continue pipeline",
        "issues_json": json.loads(issues_json) if issues_json.strip().startswith("{") else issues_json,
    }
    store.write_public_asset(
        job_id=context.job_id,
        relative_path="trace.assets/targeted-fix/fallback.json",
        content=dump_json(fallback_note),
    )
    store.write_artifact(
        job_id=context.job_id,
        relative_path="09-final-fixed.md",
        content=rule_fixed_markdown,
    )
    write_diff_asset(
        store=store,
        job_id=context.job_id,
        relative_path="diff.assets/targeted-fix/07-final-candidate_vs_09-final-fixed.patch",
        before=candidate_markdown,
        after=rule_fixed_markdown,
        from_label="07-final-candidate.md",
        to_label="09-final-fixed.md",
    )
    return rule_fixed_markdown
