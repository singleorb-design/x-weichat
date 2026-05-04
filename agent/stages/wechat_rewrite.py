from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import StageContext, run_markdown_stage


def build_wechat_rewrite_input(markdown: str) -> str:
    return f"请把下面内容改写成公众号文章：\n\n{markdown}"


def run_wechat_rewrite(
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
        input_artifact="03-reviewed.md",
        output_artifact="04-wechat.md",
        prompt_filename="wechat_rewrite_zh.txt",
        model=settings.stage_models["wechat-rewrite"],
        build_input=build_wechat_rewrite_input,
    )
