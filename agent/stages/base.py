from dataclasses import dataclass
import re
from typing import Callable

from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.prompts.loader import load_prompt
from agent.stages.helpers import write_model_exchange_assets


@dataclass(slots=True)
class StageContext:
    """跨 stage 传递的最小上下文。

    只保留任务链路里稳定且通用的信息，避免某个阶段偷偷依赖过多隐式状态。
    """
    job_id: str
    url: str
    storage_state: str | None = None


@dataclass(slots=True)
class ChunkPromptContext:
    """描述当前分块在整篇文档中的位置。

    某些 stage（例如公众号改写）在多块场景下需要根据位置调整提示词：
    首块负责开篇，中间块只续写，末块再自然收束。
    """

    chunk_index: int
    chunk_count: int

    @property
    def is_first(self) -> bool:
        return self.chunk_index == 0

    @property
    def is_last(self) -> bool:
        return self.chunk_index == self.chunk_count - 1


def read_stage_markdown(
    *,
    store: JobStore,
    context: StageContext,
    relative_path: str,
) -> str:
    """读取 stage 输入产物，统一走 `JobStore`。"""
    return store.read_artifact(job_id=context.job_id, relative_path=relative_path)


def run_markdown_stage(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
    input_artifact: str,
    output_artifact: str,
    prompt_filename: str,
    model: str,
    build_input: Callable[[str], str],
    trace_stage: str | None = None,
) -> str:
    """单次请求即可完成的标准 Markdown stage。"""
    source_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path=input_artifact,
    )
    system_prompt = load_prompt(prompt_filename)
    user_prompt = build_input(source_markdown)
    if trace_stage:
        write_model_exchange_assets(
            store=store,
            job_id=context.job_id,
            stage=trace_stage,
            call_id="call-001",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response=None,
        )

    output_markdown = gateway.generate_markdown(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    if trace_stage:
        write_model_exchange_assets(
            store=store,
            job_id=context.job_id,
            stage=trace_stage,
            call_id="call-001",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response=output_markdown,
        )
    store.write_artifact(
        job_id=context.job_id,
        relative_path=output_artifact,
        content=output_markdown,
    )
    return output_markdown


def run_chunked_markdown_stage(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    input_artifact: str,
    output_artifact: str,
    prompt_filename: str,
    model: str,
    build_input: Callable[[str], str],
    build_chunk_input: Callable[[str, ChunkPromptContext], str] | None = None,
    max_chars_per_request: int,
    trace_stage: str | None = None,
) -> str:
    """对超长 Markdown 做分块调用，降低长请求被网关断开的概率。

    分块策略尽量按段落边界切分；如果单个段落仍然过长，再降级到逐行切分。
    单块输入时保持原始输出，避免对已有行为造成额外格式扰动。
    """
    source_markdown = read_stage_markdown(
        store=store,
        context=context,
        relative_path=input_artifact,
    )
    prompt = load_prompt(prompt_filename)
    chunks = split_markdown_into_chunks(source_markdown, max_chars=max_chars_per_request)
    outputs = []
    for index, chunk in enumerate(chunks):
        chunk_context = ChunkPromptContext(chunk_index=index, chunk_count=len(chunks))
        user_prompt = build_chunk_input(chunk, chunk_context) if build_chunk_input else build_input(chunk)
        call_id = f"call-{index + 1:03d}-of-{len(chunks):03d}"
        if trace_stage:
            write_model_exchange_assets(
                store=store,
                job_id=context.job_id,
                stage=trace_stage,
                call_id=call_id,
                model=model,
                system_prompt=prompt,
                user_prompt=user_prompt,
                raw_response=None,
            )
        outputs.append(
            gateway.generate_markdown(
                model=model,
                system_prompt=prompt,
                user_prompt=user_prompt,
            )
        )
        if trace_stage:
            write_model_exchange_assets(
                store=store,
                job_id=context.job_id,
                stage=trace_stage,
                call_id=call_id,
                model=model,
                system_prompt=prompt,
                user_prompt=user_prompt,
                raw_response=outputs[-1],
            )

    if len(outputs) == 1:
        output_markdown = outputs[0]
    else:
        normalized_outputs = [_unwrap_outer_markdown_fence(chunk).strip() for chunk in outputs]
        output_markdown = "\n\n".join(chunk for chunk in normalized_outputs if chunk)
    store.write_artifact(
        job_id=context.job_id,
        relative_path=output_artifact,
        content=output_markdown,
    )
    return output_markdown


def split_markdown_into_chunks(markdown: str, *, max_chars: int) -> list[str]:
    """优先按段落切分 Markdown，尽量保持结构边界完整。"""
    if len(markdown) <= max_chars:
        return [markdown]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for block in markdown.split("\n\n"):
        normalized_block = block.strip("\n")
        if not normalized_block:
            continue

        if len(normalized_block) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            chunks.extend(_split_large_block(normalized_block, max_chars=max_chars))
            continue

        block_text = normalized_block if not current else f"\n\n{normalized_block}"
        if current and current_length + len(block_text) > max_chars:
            chunks.append("\n\n".join(current))
            current = [normalized_block]
            current_length = len(normalized_block)
            continue

        current.append(normalized_block)
        current_length += len(block_text)

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _split_large_block(block: str, *, max_chars: int) -> list[str]:
    """当单个段落仍然过大时，退化为逐行切分。"""
    lines = block.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in lines:
        candidate_length = current_length + len(line) + (1 if current else 0)
        if current and candidate_length > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_length = len(line)
            continue

        if len(line) > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_length = 0
            chunks.extend(line[index : index + max_chars] for index in range(0, len(line), max_chars))
            continue

        current.append(line)
        current_length = candidate_length

    if current:
        chunks.append("\n".join(current))

    return chunks


def _unwrap_outer_markdown_fence(markdown: str) -> str:
    """去掉模型把整段结果包成 ```markdown 的外层围栏。

    多块拼接时如果直接保留这些围栏，最终产物会出现大量原始 ```，
    对后续 stage 和 HTML 渲染都非常不友好。
    """

    trimmed = markdown.strip()
    wrapped_match = trimmed and re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$", trimmed, re.IGNORECASE)
    if wrapped_match:
        return wrapped_match.group(1)

    return markdown
