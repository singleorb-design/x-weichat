from __future__ import annotations

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext, read_stage_markdown
from agent.stages.helpers import (
    build_markdown_outline,
    count_markdown_features,
    dump_json,
    normalize_route_payload,
    read_json_artifact,
    write_json_artifact,
)


def build_route_input(
    *,
    reviewed_markdown: str,
    metadata: dict[str, object],
    source_outline: str,
    source_stats: dict[str, int],
) -> str:
    return (
        "请根据下面的已审校译文和原文结构信息，判断它应该 PASS、LIGHT_POLISH 还是 REWRITE。\n\n"
        f"【来源元信息】\n{dump_json(metadata)}\n"
        f"【原文结构摘要】\n{source_outline}\n\n"
        f"【原文结构统计】\n{dump_json(source_stats)}\n"
        f"【Review 后译文】\n{reviewed_markdown}"
    )


def run_route(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    source_markdown = read_stage_markdown(store=store, context=context, relative_path="01-source.md")
    reviewed_markdown = read_stage_markdown(store=store, context=context, relative_path="03-reviewed.md")
    metadata = read_json_artifact(store=store, job_id=context.job_id, relative_path="metadata.json")
    raw_response = gateway.generate_markdown(
        model=settings.stage_models["route"],
        system_prompt=load_prompt("route_zh.txt"),
        user_prompt=build_route_input(
            reviewed_markdown=reviewed_markdown,
            metadata=metadata,
            source_outline=build_markdown_outline(source_markdown),
            source_stats=count_markdown_features(source_markdown),
        ),
    )
    payload = normalize_route_payload(
        raw_response,
        source_type=str(metadata.get("source_type") or ""),
    )
    write_json_artifact(store=store, job_id=context.job_id, relative_path="04-route.json", payload=payload)
    return payload["decision"]
