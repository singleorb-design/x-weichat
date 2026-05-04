from __future__ import annotations

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext
from agent.stages.final_check import run_final_check_model, select_candidate_markdown
from agent.stages.helpers import (
    load_final_check_result,
    read_json_artifact,
    sanitize_publish_markdown,
    write_json_artifact,
)


def _write_final(store: JobStore, job_id: str, markdown: str) -> str:
    final_markdown = sanitize_publish_markdown(markdown)
    store.write_artifact(job_id=job_id, relative_path="10-final.md", content=final_markdown)
    return final_markdown


def run_final_output(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    initial_check = load_final_check_result(store=store, job_id=context.job_id)
    metadata = read_json_artifact(store=store, job_id=context.job_id, relative_path="metadata.json")
    _candidate_artifact, candidate_markdown, route_payload = select_candidate_markdown(
        store=store,
        job_id=context.job_id,
    )

    if initial_check.pass_:
        return _write_final(store, context.job_id, candidate_markdown)

    if not initial_check.fix_required:
        write_json_artifact(
            store=store,
            job_id=context.job_id,
            relative_path="final_check_failed.json",
            payload=initial_check.model_dump(mode="json", by_alias=True),
        )
        store.write_artifact(
            job_id=context.job_id,
            relative_path="final_candidate_failed.md",
            content=candidate_markdown,
        )
        raise ValueError("Final Check blocked publication and did not allow automatic fixes; manual review required.")

    fixed_markdown = store.read_artifact(job_id=context.job_id, relative_path="09-final-fixed.md")
    second_check_payload, _raw_response = run_final_check_model(
        gateway=gateway,
        settings=settings,
        candidate_markdown=fixed_markdown,
        metadata=metadata,
        route_payload=route_payload,
    )
    write_json_artifact(
        store=store,
        job_id=context.job_id,
        relative_path="final_check_after_fix.json",
        payload=second_check_payload,
    )
    if second_check_payload.get("pass"):
        return _write_final(store, context.job_id, fixed_markdown)

    write_json_artifact(
        store=store,
        job_id=context.job_id,
        relative_path="final_check_failed.json",
        payload=second_check_payload,
    )
    store.write_artifact(
        job_id=context.job_id,
        relative_path="final_candidate_failed.md",
        content=fixed_markdown,
    )
    raise ValueError("Final Check still failed after targeted fix; manual review required before publishing.")
