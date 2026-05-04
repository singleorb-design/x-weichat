from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.base import (
    StageContext,
    _unwrap_outer_markdown_fence,
    read_stage_markdown,
    split_markdown_into_chunks,
)
from agent.stages.helpers import is_substantially_shorter


# 审校需要同时看原文和译文，因此把单边 chunk 控制在 6k 左右，避免整体 prompt 过长。
MAX_REVIEW_CHARS_PER_REQUEST = 12000


def build_review_input(source_markdown: str, translated_markdown: str) -> str:
    """把原文与译文一起包装成审校任务输入。"""
    return (
        "请对照英文原文审校下面的中文 Markdown，只输出修正后的完整中文稿。\n\n"
        f"【原文】\n{source_markdown}\n\n"
        f"【译文】\n{translated_markdown}"
    )


def _rebucket_chunks(chunks: list[str], *, target_count: int) -> list[str]:
    if target_count <= 1 or len(chunks) == 1:
        return ["\n\n".join(chunk for chunk in chunks if chunk.strip())]

    if target_count > len(chunks):
        expanded = [chunk for chunk in chunks if chunk.strip()]
        while len(expanded) < target_count:
            split_index = max(range(len(expanded)), key=lambda index: len(expanded[index]))
            split_pair = _split_chunk_in_two(expanded[split_index])
            if split_pair is None:
                break
            expanded[split_index : split_index + 1] = [split_pair[0], split_pair[1]]
        return expanded

    bucketed: list[str] = []
    for index in range(target_count):
        start = (index * len(chunks)) // target_count
        end = ((index + 1) * len(chunks)) // target_count
        if start == end:
            end = min(start + 1, len(chunks))
        bucketed.append("\n\n".join(chunk for chunk in chunks[start:end] if chunk.strip()))
    return bucketed


def _split_chunk_in_two(chunk: str) -> tuple[str, str] | None:
    blocks = [block.strip("\n") for block in chunk.split("\n\n") if block.strip()]
    if len(blocks) >= 2:
        midpoint = len(blocks) // 2
        return ("\n\n".join(blocks[:midpoint]), "\n\n".join(blocks[midpoint:]))

    lines = [line for line in chunk.splitlines() if line.strip()]
    if len(lines) >= 2:
        midpoint = len(lines) // 2
        return ("\n".join(lines[:midpoint]), "\n".join(lines[midpoint:]))

    normalized = chunk.strip()
    if len(normalized) < 2:
        return None

    midpoint = len(normalized) // 2
    return (normalized[:midpoint], normalized[midpoint:])


def run_review(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    """审校阶段。

    相比翻译阶段，这一步既要保留结构又会产生较长输出，因此使用更保守的分块阈值。
    """
    source_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path="01-source.md",
    )
    translated_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path="02-translation.md",
    )

    max_chars_per_side = max(2000, MAX_REVIEW_CHARS_PER_REQUEST // 2)
    source_chunks = split_markdown_into_chunks(source_markdown, max_chars=max_chars_per_side)
    translated_chunks = split_markdown_into_chunks(translated_markdown, max_chars=max_chars_per_side)
    target_count = max(len(source_chunks), len(translated_chunks))
    paired_source_chunks = _rebucket_chunks(source_chunks, target_count=target_count)
    paired_translated_chunks = _rebucket_chunks(translated_chunks, target_count=target_count)
    prompt = load_prompt("review_zh.txt")

    outputs: list[str] = []
    for source_chunk, translated_chunk in zip(paired_source_chunks, paired_translated_chunks, strict=True):
        outputs.append(
            gateway.generate_markdown(
                model=settings.stage_models["review"],
                system_prompt=prompt,
                user_prompt=build_review_input(source_chunk, translated_chunk),
            )
        )

    reviewed_markdown = outputs[0] if len(outputs) == 1 else "\n\n".join(
        _unwrap_outer_markdown_fence(chunk).strip() for chunk in outputs if chunk.strip()
    )

    if is_substantially_shorter(translated_markdown, reviewed_markdown, min_ratio=0.75):
        raise ValueError("Review output appears truncated compared with translation input; please rerun review.")

    store.write_artifact(
        job_id=context.job_id,
        relative_path="03-reviewed.md",
        content=reviewed_markdown,
    )
    return reviewed_markdown
