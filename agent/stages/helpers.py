from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent.jobs.store import JobStore
from agent.models.schemas import FinalCheckResult, RouteDecision


T = TypeVar("T", bound=BaseModel)

ROUTE_CANDIDATE_ARTIFACTS = {
    "PASS": "03-reviewed.md",
    "LIGHT_POLISH": "05-polished.md",
    "REWRITE": "06-rewritten.md",
}


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


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
    match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
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
    if decision not in {"PASS", "LIGHT_POLISH", "REWRITE"}:
        decision = "LIGHT_POLISH"
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
    return FinalCheckResult.model_validate(payload)
