from __future__ import annotations

import json
from typing import Any

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.models.schemas import FinalCheckResult
from agent.prompts.loader import load_prompt
from agent.stages.base import StageContext
from agent.stages.helpers import (
    dump_json,
    enhance_readability_markdown,
    extract_json_object,
    load_route_payload,
    normalize_final_check_payload,
    read_json_artifact,
    route_candidate_artifact,
    write_model_exchange_assets,
    write_json_artifact,
)


def build_final_check_input(
    *,
    candidate_markdown: str,
    metadata: dict[str, Any],
    route_payload: dict[str, Any],
) -> str:
    return (
        "请对下面这篇候选最终稿做发布前 Final Check，只输出严格 JSON。\n"
        "注意：只有【最终候选稿】属于待发布正文；【路由结果】和【元信息】都只是辅助上下文，绝不能把它们当成正文内容，也不能据此判定‘元信息泄露’。\n\n"
        f"【路由结果】\n{dump_json(route_payload)}\n"
        f"【元信息】\n{dump_json(metadata)}\n"
        f"【最终候选稿】\n{candidate_markdown}"
    )


def select_candidate_markdown(*, store: JobStore, job_id: str) -> tuple[str, str, dict[str, Any]]:
    route_payload = load_route_payload(store=store, job_id=job_id)
    candidate_artifact = route_candidate_artifact(str(route_payload.get("decision") or "LIGHT_POLISH"))
    candidate_markdown = store.read_artifact(job_id=job_id, relative_path=candidate_artifact)
    return candidate_artifact, candidate_markdown, route_payload


def run_final_check_model(
    *,
    store: JobStore | None = None,
    job_id: str | None = None,
    trace_call_prefix: str = "",
    gateway: ModelGateway,
    settings: Settings,
    candidate_markdown: str,
    metadata: dict[str, Any],
    route_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    prompt = load_prompt("final_check_zh.txt")
    user_prompt = build_final_check_input(
        candidate_markdown=candidate_markdown,
        metadata=metadata,
        route_payload=route_payload,
    )
    if store is not None and job_id is not None:
        write_model_exchange_assets(
            store=store,
            job_id=job_id,
            stage="final-check",
            call_id=f"{trace_call_prefix}attempt-1",
            model=settings.stage_models["final-check"],
            system_prompt=prompt,
            user_prompt=user_prompt,
            raw_response=None,
        )
    raw_response = gateway.generate_markdown(
        model=settings.stage_models["final-check"],
        system_prompt=prompt,
        user_prompt=user_prompt,
    )
    if store is not None and job_id is not None:
        write_model_exchange_assets(
            store=store,
            job_id=job_id,
            stage="final-check",
            call_id=f"{trace_call_prefix}attempt-1",
            model=settings.stage_models["final-check"],
            system_prompt=prompt,
            user_prompt=user_prompt,
            raw_response=raw_response,
        )
    try:
        payload = json.loads(extract_json_object(raw_response))
        parsed = FinalCheckResult.model_validate(normalize_final_check_payload(payload))
        return parsed.model_dump(mode="json", by_alias=True), raw_response
    except Exception:
        retry_user_prompt = f"请只输出严格 JSON，不要输出任何解释。\n\n{user_prompt}"
        if store is not None and job_id is not None:
            write_model_exchange_assets(
                store=store,
                job_id=job_id,
                stage="final-check",
                call_id=f"{trace_call_prefix}attempt-2",
                model=settings.stage_models["final-check"],
                system_prompt=prompt,
                user_prompt=retry_user_prompt,
                raw_response=None,
            )
        retry_response = gateway.generate_markdown(
            model=settings.stage_models["final-check"],
            system_prompt=prompt,
            user_prompt=retry_user_prompt,
        )
        if store is not None and job_id is not None:
            write_model_exchange_assets(
                store=store,
                job_id=job_id,
                stage="final-check",
                call_id=f"{trace_call_prefix}attempt-2",
                model=settings.stage_models["final-check"],
                system_prompt=prompt,
                user_prompt=retry_user_prompt,
                raw_response=retry_response,
            )
        payload = json.loads(extract_json_object(retry_response))
        parsed = FinalCheckResult.model_validate(normalize_final_check_payload(payload))
        return parsed.model_dump(mode="json", by_alias=True), retry_response


def run_final_check(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    metadata = read_json_artifact(store=store, job_id=context.job_id, relative_path="metadata.json")
    _candidate_artifact, candidate_markdown, route_payload = select_candidate_markdown(
        store=store,
        job_id=context.job_id,
    )
    candidate_markdown = enhance_readability_markdown(candidate_markdown)
    store.write_artifact(
        job_id=context.job_id,
        relative_path="07-final-candidate.md",
        content=candidate_markdown,
    )
    try:
        payload, _raw_response = run_final_check_model(
            store=store,
            job_id=context.job_id,
            gateway=gateway,
            settings=settings,
            candidate_markdown=candidate_markdown,
            metadata=metadata,
            route_payload=route_payload,
        )
    except Exception as exc:
        store.write_artifact(
            job_id=context.job_id,
            relative_path="final_check_raw.txt",
            content=str(exc),
        )
        failure_payload = {
            "pass": False,
            "risk": "HIGH",
            "fix_required": True,
            "issues": [
                {
                    "type": "final_check_parse_failure",
                    "severity": "HIGH",
                    "detail": "Final Check 未返回可解析 JSON。",
                    "fix_suggestion": "检查 final_check_raw.txt 并人工处理后再重跑。",
                }
            ],
        }
        write_json_artifact(
            store=store,
            job_id=context.job_id,
            relative_path="final_check_failed.json",
            payload=failure_payload,
        )
        raise ValueError("Final Check did not return strict JSON; manual review required.") from exc

    write_json_artifact(store=store, job_id=context.job_id, relative_path="08-final-check.json", payload=payload)
    return dump_json(payload)
