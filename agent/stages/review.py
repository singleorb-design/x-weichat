from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext, run_markdown_stage


def build_review_input(markdown: str) -> str:
    return f"请审校下面中文 Markdown：\n\n{markdown}"


def run_review(
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
        input_artifact="02-translation.md",
        output_artifact="03-reviewed.md",
        prompt_filename="review_zh.txt",
        model=settings.stage_models["review"],
        build_input=build_review_input,
    )
