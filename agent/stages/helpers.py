from __future__ import annotations

import json
import re
import difflib
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent.jobs.store import JobStore
from agent.models.schemas import FinalCheckResult, RouteDecision


T = TypeVar("T", bound=BaseModel)

ROUTE_CANDIDATE_ARTIFACTS = {
    "PASS": "03-reviewed.md",
    "LIGHT_POLISH": "05-polished.md",
}


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_unified_diff(
    before: str,
    after: str,
    *,
    from_label: str = "before",
    to_label: str = "after",
    context_lines: int = 3,
) -> str:
    before_lines = before.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    after_lines = after.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=from_label,
        tofile=to_label,
        n=context_lines,
    )
    return "".join(diff_lines) or "(no changes)\n"


def write_diff_asset(
    *,
    store: JobStore,
    job_id: str,
    relative_path: str,
    before: str,
    after: str,
    from_label: str,
    to_label: str,
) -> None:
    store.write_public_asset(
        job_id=job_id,
        relative_path=relative_path,
        content=build_unified_diff(before, after, from_label=from_label, to_label=to_label),
    )


def write_model_exchange_assets(
    *,
    store: JobStore,
    job_id: str,
    stage: str,
    call_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    raw_response: str | None,
) -> None:
    """把一次模型调用的输入/输出落盘，供 UI 查看。"""

    base_dir = f"trace.assets/{stage}"
    request_path = f"{base_dir}/{call_id}.request.json"
    response_path = f"{base_dir}/{call_id}.response.txt"

    request_payload = {
        "stage": stage,
        "call_id": call_id,
        "model": model,
        "recorded_at": now_iso(),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    store.write_public_asset(
        job_id=job_id,
        relative_path=request_path,
        content=dump_json(request_payload),
    )
    if raw_response is not None:
        store.write_public_asset(
            job_id=job_id,
            relative_path=response_path,
            content=raw_response,
        )


def write_json_artifact(*, store: JobStore, job_id: str, relative_path: str, payload: Any) -> None:
    store.write_artifact(
        job_id=job_id,
        relative_path=relative_path,
        content=dump_json(payload),
    )


def read_json_artifact(*, store: JobStore, job_id: str, relative_path: str) -> dict[str, Any]:
    return json.loads(store.read_artifact(job_id=job_id, relative_path=relative_path))


def extract_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return {}, markdown

    closing_index = normalized.find("\n---\n", 4)
    if closing_index == -1:
        return {}, markdown

    frontmatter_text = normalized[4:closing_index]
    body = normalized[closing_index + 5 :].lstrip("\n")
    payload: dict[str, Any] = {}
    for raw_line in frontmatter_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip().strip('"\'')
    return payload, body


def extract_markdown_title(markdown: str) -> str | None:
    _frontmatter, body = extract_frontmatter(markdown)
    # `sanitize_publish_markdown()` may demote `#` to `##`, so treat the first heading
    # (any level) as the best-effort title.
    match = re.search(r"^#{1,6}\s+(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


def sanitize_publish_markdown(markdown: str) -> str:
    frontmatter, body = extract_frontmatter(markdown)
    title = str(frontmatter.get("title") or "").strip()
    normalized = body.strip()

    if not re.search(r"^#{1,6}\s+", normalized, re.MULTILINE) and title:
        normalized = f"## {title}\n\n{normalized}" if normalized else f"## {title}"

    normalized = re.sub(
        r"^(以下是翻译[:：]?|以下是改写[:：]?|这是修正版[:：]?|我帮你整理[:：]?|根据你的要求[:：]?|作为 AI.*|如需我继续.*)\s*$",
        "",
        normalized,
        flags=re.MULTILINE,
    )
    normalized = re.sub(r"^#\s+", "## ", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized + "\n"


def enhance_readability_markdown(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter_match = re.match(r"^(---\n[\s\S]*?\n---\n+)", normalized)
    if frontmatter_match:
        prefix = frontmatter_match.group(1)
        body = normalized[len(prefix) :]
        return prefix + _enhance_readability_body(body)

    return _enhance_readability_body(normalized)


def _enhance_readability_body(body: str) -> str:
    section_starts = [match.start() for match in re.finditer(r"(?m)^##\s+", body)]
    if not section_starts:
        return _enhance_readability_section(body)

    sections: list[str] = []
    if section_starts[0] > 0:
        sections.append(body[: section_starts[0]])

    for index, start in enumerate(section_starts):
        end = section_starts[index + 1] if index + 1 < len(section_starts) else len(body)
        sections.append(_enhance_readability_section(body[start:end]))

    return "".join(sections)


def _enhance_readability_section(section: str) -> str:
    if ">   **要点：**" in section or "> **要点：**" in section:
        return section

    trailing_match = re.search(r"\n*$", section)
    trailing_newlines = trailing_match.group(0) if trailing_match else ""
    section_body = section[: len(section) - len(trailing_newlines)] if trailing_newlines else section
    if not section_body.strip():
        return section

    blocks = _split_markdown_blocks(section_body)
    candidates = [
        (index, block, sentence)
        for index, block in enumerate(blocks)
        if (sentence := _extract_summary_sentence(block)) is not None
    ]

    paragraph_chars = sum(len(_plain_block_text(block)) for _index, block, _sentence in candidates)
    if len(candidates) < 5 and paragraph_chars < 600:
        return section

    if len(candidates) < 2:
        return section

    insert_after_index = candidates[1][0]
    summary_sentence = candidates[1][2]
    blocks.insert(insert_after_index + 1, f">   **要点：** {summary_sentence}")
    return "\n\n".join(blocks) + trailing_newlines


def _split_markdown_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            current.append(line)
            continue

        if not in_fence and not line.strip():
            if current:
                blocks.append("\n".join(current).strip("\n"))
                current = []
            continue

        current.append(line)

    if current:
        blocks.append("\n".join(current).strip("\n"))

    return [block for block in blocks if block.strip()]


def _plain_block_text(block: str) -> str:
    return re.sub(r"\s+", "", block.strip())


def _extract_summary_sentence(block: str) -> str | None:
    stripped = block.strip()
    if not _is_plain_paragraph_block(stripped):
        return None

    sentences = re.findall(r"[^。！？.!?]+[。！？.!?]", stripped)
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).strip()
        if 28 <= len(normalized) <= 120 and _is_safe_summary_sentence(normalized):
            return normalized
    return None


def _is_plain_paragraph_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False

    if len(lines) > 1:
        return False

    line = lines[0]
    if re.match(r"^#{1,6}\s+", line):
        return False
    if line.startswith((">", "```", "|", "![", "<")):
        return False
    if re.match(r"^(?:[-*+]|\d+\.)\s+", line):
        return False
    if "|" in line:
        return False
    if "http://" in line or "https://" in line:
        return False
    if re.search(r"!\[[^\]]*\]\([^)]+\)", line):
        return False
    return True


def _is_safe_summary_sentence(sentence: str) -> bool:
    if "http://" in sentence or "https://" in sentence:
        return False
    if re.search(r"!?\[[^\]]*\]\([^)]+\)", sentence):
        return False
    if "|" in sentence:
        return False
    return True


def extract_first_markdown_image(markdown: str) -> str | None:
    image_match = re.search(r"!\[[^\]]*\]\(([^)\s]+)", markdown)
    if image_match:
        return image_match.group(1).strip()
    return None


def build_markdown_outline(markdown: str, *, max_items: int = 18) -> str:
    _frontmatter, body = extract_frontmatter(markdown)
    headings = re.findall(r"^(#{1,6})\s+(.+)$", body, re.MULTILINE)
    if not headings:
        paragraph_count = len([block for block in body.split("\n\n") if block.strip()])
        return f"无显式标题；段落块约 {paragraph_count} 段。"

    lines: list[str] = []
    for level_marks, title in headings[:max_items]:
        lines.append(f"{'  ' * (len(level_marks) - 1)}- {title.strip()}")
    if len(headings) > max_items:
        lines.append(f"- 其余还有 {len(headings) - max_items} 个标题层级")
    return "\n".join(lines)


def count_markdown_features(markdown: str) -> dict[str, int]:
    _frontmatter, body = extract_frontmatter(markdown)
    return {
        "chars": len(body),
        "headings": len(re.findall(r"^#{1,6}\s+", body, re.MULTILINE)),
        "lists": len(re.findall(r"^(?:-|\*|\d+\.)\s+", body, re.MULTILINE)),
        "code_fences": len(re.findall(r"^```", body, re.MULTILINE)) // 2,
        "tables": len(re.findall(r"\|", body)),
    }


def is_substantially_shorter(source_markdown: str, output_markdown: str, *, min_ratio: float) -> bool:
    source_length = max(len(source_markdown.strip()), 1)
    output_length = len(output_markdown.strip())
    return output_length / source_length < min_ratio


def extract_json_object(raw: str) -> str:
    stripped = raw.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", stripped, re.IGNORECASE)
    if fence_match:
        stripped = fence_match.group(1).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    raise ValueError("Unterminated JSON object in model output.")


def parse_model_json(raw: str, model_type: type[T]) -> T:
    payload = json.loads(extract_json_object(raw))
    return model_type.model_validate(payload)


def normalize_final_check_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """让 Final Check JSON 对齐模型契约。

    线上/历史产物里可能出现不一致：`pass=true` 但仍包含 issues。
    这会触发 `FinalCheckResult` 的一致性校验，并导致在 `final-output` 才失败。

    归一化策略（偏保守）：
    - 若 `pass=true` 且 `issues` 非空：视为未通过（pass=false）。
    - 若 issues 非空但 fix_required 未标/为 false：按严重程度推断是否需要 fix。
    """

    normalized = dict(payload)
    passed = bool(normalized.get("pass"))
    issues = normalized.get("issues")
    has_issues = isinstance(issues, list) and len(issues) > 0

    if passed and has_issues:
        normalized["pass"] = False
        passed = False

    if passed:
        normalized["fix_required"] = False
        normalized["issues"] = []
        return normalized

    if has_issues and not normalized.get("fix_required"):
        severities = [
            str(issue.get("severity") or "").upper()
            for issue in issues
            if isinstance(issue, dict)
        ]
        normalized["fix_required"] = any(level in {"HIGH", "MEDIUM"} for level in severities)

    return normalized


def normalize_route_payload(raw: str, *, source_type: str | None = None) -> dict[str, Any]:
    try:
        parsed = parse_model_json(raw, RouteDecision)
        payload = parsed.model_dump(mode="json")
        fallback = False
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "decision": "LIGHT_POLISH",
            "reason": f"路由 JSON 解析失败，按默认策略进入轻编辑：{exc}",
            "risk": "MEDIUM",
            "recommended_next_prompt": "LIGHT_POLISH",
        }
        fallback = True

    decision = payload["decision"]
    risk = payload["risk"]
    if decision not in {"PASS", "LIGHT_POLISH"}:
        decision = "LIGHT_POLISH"
        payload["decision"] = decision
    if payload.get("recommended_next_prompt") != decision:
        payload["recommended_next_prompt"] = decision
    if decision == "PASS" and risk != "LOW":
        payload["decision"] = "LIGHT_POLISH"
        payload["recommended_next_prompt"] = "LIGHT_POLISH"
        payload["reason"] = f"{payload['reason']}；为避免误判，已把 PASS 收敛为 LIGHT_POLISH。"
    if source_type == "tweet" and payload["decision"] == "PASS":
        payload["decision"] = "LIGHT_POLISH"
        payload["recommended_next_prompt"] = "LIGHT_POLISH"
        payload["reason"] = f"{payload['reason']}；推文形态默认至少做轻编辑。"
    if fallback:
        payload["fallback"] = True
        payload["raw_response"] = raw.strip()
    return payload


def route_candidate_artifact(decision: str) -> str:
    if decision not in ROUTE_CANDIDATE_ARTIFACTS:
        raise ValueError(f"Unsupported route decision: {decision}")
    return ROUTE_CANDIDATE_ARTIFACTS[decision]


def load_route_payload(*, store: JobStore, job_id: str) -> dict[str, Any]:
    return read_json_artifact(store=store, job_id=job_id, relative_path="04-route.json")


def load_final_check_result(*, store: JobStore, job_id: str) -> FinalCheckResult:
    payload = read_json_artifact(store=store, job_id=job_id, relative_path="08-final-check.json")
    return FinalCheckResult.model_validate(normalize_final_check_payload(payload))
