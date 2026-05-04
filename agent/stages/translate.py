from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext, run_chunked_markdown_stage


MAX_TRANSLATE_CHARS_PER_REQUEST = 12000


def build_translate_input(source_markdown: str) -> str:
    """把原文包装成翻译任务输入，明确要求保留 Markdown 结构。"""
    return f"请把下面内容翻译成中文，保留 Markdown 结构：\n\n{source_markdown}"


def run_translate(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    """翻译阶段。

    原文较长时自动分块，避免单次请求耗时过长或被上游网关中断。
    """
    return run_chunked_markdown_stage(
        context=context,
        store=store,
        gateway=gateway,
        input_artifact="01-source.md",
        output_artifact="02-translation.md",
        prompt_filename="translate_zh.txt",
        model=settings.stage_models["translate"],
        build_input=build_translate_input,
        max_chars_per_request=MAX_TRANSLATE_CHARS_PER_REQUEST,
    )
