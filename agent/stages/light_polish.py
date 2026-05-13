from __future__ import annotations

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.base import ChunkPromptContext, StageContext, read_stage_markdown, run_chunked_markdown_stage
from agent.stages.helpers import dump_json, is_substantially_shorter, load_route_payload, read_json_artifact


# 轻编辑必须保留全文信息，但输出通常与输入等长；超长文章改为分块可降低尾段丢失概率。
MAX_LIGHT_POLISH_CHARS_PER_REQUEST = 6000
LIGHT_POLISH_MIN_OUTPUT_RATIO = 0.88
LIGHT_POLISH_CHUNK_RETRY_SIZES = (6000, 4200, 3000, 2200, 1600)


def build_light_polish_input(reviewed_markdown: str, metadata: dict[str, object]) -> str:
    return (
        "请对下面的已审校译文做公众号轻编辑，只提升标题、开头、小标题、过渡句和模板包装，不能删减信息。\n\n"
        f"【元信息】\n{dump_json(metadata)}\n"
        f"【Review 后译文】\n{reviewed_markdown}"
    )


def build_light_polish_chunk_input(
    reviewed_markdown: str,
    metadata: dict[str, object],
    chunk: ChunkPromptContext,
) -> str:
    if chunk.chunk_count == 1:
        return build_light_polish_input(reviewed_markdown, metadata)

    chunk_label = f"第 {chunk.chunk_index + 1} / {chunk.chunk_count} 段"
    if chunk.is_first:
        instruction = "请正常处理标题、开头和这一段中的结构优化，但必须完整保留本段全部信息点。"
    elif chunk.is_last:
        instruction = "请延续前文即可，不要重复整篇标题或开场导语；如果内容自然结束，再收束全文，但不要漏掉本段任何信息。"
    else:
        instruction = "请延续前文即可，不要重复整篇标题或开场导语，也不要提前总结全文；必须完整保留本段全部信息点。"

    return (
        "请对下面的已审校译文做公众号轻编辑，只处理当前这一段。\n"
        f"当前处理的是整篇文章的{chunk_label}。\n"
        f"{instruction}\n"
        "只输出这一段应有的 Markdown 正文，不要解释。\n\n"
        f"【元信息】\n{dump_json(metadata)}\n"
        f"【Review 后译文】\n{reviewed_markdown}"
    )


def run_light_polish(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    route_payload = load_route_payload(store=store, job_id=context.job_id)
    reviewed_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path="03-reviewed.md",
    )
    if route_payload.get("decision") != "LIGHT_POLISH":
        return reviewed_markdown

    metadata = read_json_artifact(store=store, job_id=context.job_id, relative_path="metadata.json")
    attempted_sizes: list[int] = []
    polished_markdown = ""

    for chunk_size in _light_polish_chunk_sizes(reviewed_markdown):
        attempted_sizes.append(chunk_size)
        polished_markdown = run_chunked_markdown_stage(
            context=context,
            store=store,
            gateway=gateway,
            input_artifact="03-reviewed.md",
            output_artifact="05-polished.md",
            prompt_filename="light_polish_zh.txt",
            model=settings.stage_models["light-polish"],
            build_input=lambda markdown: build_light_polish_input(markdown, metadata),
            build_chunk_input=lambda markdown, chunk: build_light_polish_chunk_input(markdown, metadata, chunk),
            max_chars_per_request=chunk_size,
            trace_stage="light-polish",
        )
        if not is_substantially_shorter(
            reviewed_markdown,
            polished_markdown,
            min_ratio=LIGHT_POLISH_MIN_OUTPUT_RATIO,
        ):
            return polished_markdown

    store.write_artifact(
        job_id=context.job_id,
        relative_path="05-polished.md",
        content=reviewed_markdown,
    )
    return reviewed_markdown


def _light_polish_chunk_sizes(reviewed_markdown: str) -> list[int]:
    sizes: list[int] = []
    source_length = max(len(reviewed_markdown), 1)
    for candidate in (MAX_LIGHT_POLISH_CHARS_PER_REQUEST, *LIGHT_POLISH_CHUNK_RETRY_SIZES):
        normalized = min(candidate, source_length)
        if normalized not in sizes:
            sizes.append(normalized)
    return sizes
