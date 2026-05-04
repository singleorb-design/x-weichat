from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext, run_markdown_stage


def build_translate_input(source_markdown: str) -> str:
    return f"请把下面内容翻译成中文，保留 Markdown 结构：\n\n{source_markdown}"


def run_translate(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    return run_markdown_stage(
        context=context,
        store=store,
        gateway=gateway,
        settings=settings,
        input_artifact="01-source.md",
        output_artifact="02-translation.md",
        prompt_filename="translate_zh.txt",
        model=settings.stage_models["translate"],
        build_input=build_translate_input,
    )
