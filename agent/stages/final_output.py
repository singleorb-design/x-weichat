from __future__ import annotations

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext
from agent.stages.final_check import run_final_check_model, select_candidate_markdown
from agent.stages.helpers import (
    dump_json,
    enhance_readability_markdown,
    extract_markdown_title,
    load_final_check_result,
    now_iso,
    read_json_artifact,
    sanitize_publish_markdown,
    write_diff_asset,
    write_model_exchange_assets,
    write_json_artifact,
)
from agent.prompts.loader import load_prompt
from agent.stages.targeted_fix import build_targeted_fix_input, _assert_blockquotes_preserved, _should_flag_truncation


def _write_final(store: JobStore, job_id: str, markdown: str) -> str:
    final_markdown = sanitize_publish_markdown(markdown)
    store.write_artifact(job_id=job_id, relative_path="10-final.md", content=final_markdown)

    # 列表展示用标题：优先用最终稿的 H1（比原文标题更符合“最终产物”视角）。
    try:
        title = extract_markdown_title(final_markdown)
    except Exception:
        title = None
    if title:
        try:
            store.update_source_title(job_id=job_id, source_title=title)
        except Exception:
            pass
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
    candidate_markdown = enhance_readability_markdown(candidate_markdown)

    if initial_check.pass_:
        final_markdown = _write_final(store, context.job_id, candidate_markdown)
        # 额外生成“轻编辑稿 vs 最终稿”的 diff，方便人工校对与采纳。
        try:
            polished = store.read_artifact(job_id=context.job_id, relative_path="05-polished.md")
        except Exception:
            polished = None
        if polished:
            write_diff_asset(
                store=store,
                job_id=context.job_id,
                relative_path="diff.assets/final/05-polished_vs_10-final.patch",
                before=polished,
                after=final_markdown,
                from_label="05-polished.md",
                to_label="10-final.md",
            )
        return final_markdown

    # Final Check 明确禁止自动修复时，仍然输出一个“半成品 final”，避免整条 pipeline 失败。
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
        store.write_public_asset(
            job_id=context.job_id,
            relative_path="final_output.assets/summary.txt",
            content=(
                "Final Check blocked automatic fixes; published best-effort output anyway.\n"
                f"checked_at: {now_iso()}\n"
            ),
        )
        final_markdown = _write_final(store, context.job_id, candidate_markdown)
        try:
            polished = store.read_artifact(job_id=context.job_id, relative_path="05-polished.md")
        except Exception:
            polished = None
        if polished:
            write_diff_asset(
                store=store,
                job_id=context.job_id,
                relative_path="diff.assets/final/05-polished_vs_10-final.patch",
                before=polished,
                after=final_markdown,
                from_label="05-polished.md",
                to_label="10-final.md",
            )
        return final_markdown

    max_rounds = getattr(settings, "final_output_max_fix_rounds", 3)
    max_rounds = max(1, int(max_rounds))

    # targeted-fix stage 会尝试写入 `09-final-fixed.md`；即使失败也会 fallback 写候选稿。
    try:
        current_markdown = store.read_artifact(job_id=context.job_id, relative_path="09-final-fixed.md")
    except Exception:
        current_markdown = candidate_markdown
    current_markdown = enhance_readability_markdown(current_markdown)

    best_markdown = current_markdown
    best_check_payload: dict[str, object] = initial_check.model_dump(mode="json", by_alias=True)

    prompt = load_prompt("targeted_fix_zh.txt")
    fix_model = settings.stage_models["targeted-fix"]

    last_payload: dict[str, object] | None = None
    passed = False

    for round_index in range(1, max_rounds + 1):
        # 每轮先终检当前稿件。
        payload, _raw = run_final_check_model(
            store=store,
            job_id=context.job_id,
            trace_call_prefix=f"round-{round_index}.",
            gateway=gateway,
            settings=settings,
            candidate_markdown=current_markdown,
            metadata=metadata,
            route_payload=route_payload,
        )
        last_payload = payload
        store.write_public_asset(
            job_id=context.job_id,
            relative_path=f"final_output.assets/final-check/round-{round_index}.json",
            content=dump_json(payload),
        )
        if round_index == 1:
            write_json_artifact(
                store=store,
                job_id=context.job_id,
                relative_path="final_check_after_fix.json",
                payload=payload,
            )

        if payload.get("pass"):
            passed = True
            best_markdown = current_markdown
            best_check_payload = payload
            break

        best_markdown = current_markdown
        best_check_payload = payload

        # 终检不允许自动修复或已经到达最大轮次，直接停止并输出 best-effort。
        if not payload.get("fix_required") or round_index >= max_rounds:
            break

        issues_json = dump_json(payload)
        user_prompt = build_targeted_fix_input(current_markdown, issues_json)

        fixed_candidate: str | None = None
        last_fix_error: str | None = None
        for attempt in range(1, 3):
            call_id = f"round-{round_index + 1}.attempt-{attempt}"
            write_model_exchange_assets(
                store=store,
                job_id=context.job_id,
                stage="final-output-targeted-fix",
                call_id=call_id,
                model=fix_model,
                system_prompt=prompt,
                user_prompt=user_prompt,
                raw_response=None,
            )
            candidate = gateway.generate_markdown(
                model=fix_model,
                system_prompt=prompt,
                user_prompt=user_prompt,
            )
            write_model_exchange_assets(
                store=store,
                job_id=context.job_id,
                stage="final-output-targeted-fix",
                call_id=call_id,
                model=fix_model,
                system_prompt=prompt,
                user_prompt=user_prompt,
                raw_response=candidate,
            )

            is_truncated, signals = _should_flag_truncation(current_markdown, candidate)
            if is_truncated:
                last_fix_error = f"truncation(signals={signals})"
                store.write_public_asset(
                    job_id=context.job_id,
                    relative_path=f"trace.assets/final-output-targeted-fix/{call_id}.error.txt",
                    content=f"checked_at: {now_iso()}\nerror: {last_fix_error}\n",
                )
                continue

            try:
                _assert_blockquotes_preserved(current_markdown, candidate)
            except Exception as exc:
                last_fix_error = f"{type(exc).__name__}: {exc}"
                store.write_public_asset(
                    job_id=context.job_id,
                    relative_path=f"trace.assets/final-output-targeted-fix/{call_id}.error.txt",
                    content=f"checked_at: {now_iso()}\nerror: {last_fix_error}\n",
                )
                continue

            fixed_candidate = candidate
            break

        if fixed_candidate is None:
            store.write_public_asset(
                job_id=context.job_id,
                relative_path=f"final_output.assets/targeted-fix/round-{round_index + 1}.fallback.txt",
                content=(
                    f"checked_at: {now_iso()}\n"
                    f"reason: {last_fix_error or 'unknown'}\n"
                    "behavior: keep previous markdown and stop retry loop\n"
                ),
            )
            break

        write_diff_asset(
            store=store,
            job_id=context.job_id,
            relative_path=f"diff.assets/final-output/round-{round_index}_vs_round-{round_index + 1}.patch",
            before=current_markdown,
            after=fixed_candidate,
            from_label=f"round-{round_index}",
            to_label=f"round-{round_index + 1}",
        )
        current_markdown = enhance_readability_markdown(fixed_candidate)

    if not passed and last_payload is not None:
        write_json_artifact(
            store=store,
            job_id=context.job_id,
            relative_path="final_check_failed.json",
            payload=last_payload,
        )
        store.write_artifact(
            job_id=context.job_id,
            relative_path="final_candidate_failed.md",
            content=best_markdown,
        )
        store.write_public_asset(
            job_id=context.job_id,
            relative_path="final_output.assets/summary.txt",
            content=(
                "Final output published with unresolved Final Check issues (best-effort fallback).\n"
                f"checked_at: {now_iso()}\n"
                f"max_rounds: {max_rounds}\n"
            ),
        )

    final_markdown = _write_final(store, context.job_id, best_markdown)
    try:
        polished = store.read_artifact(job_id=context.job_id, relative_path="05-polished.md")
    except Exception:
        polished = None
    if polished:
        write_diff_asset(
            store=store,
            job_id=context.job_id,
            relative_path="diff.assets/final/05-polished_vs_10-final.patch",
            before=polished,
            after=final_markdown,
            from_label="05-polished.md",
            to_label="10-final.md",
        )
    return final_markdown
