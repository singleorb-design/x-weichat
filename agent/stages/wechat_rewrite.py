from agent.config import Settings
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway
from agent.stages.base import ChunkPromptContext, StageContext, run_chunked_markdown_stage
from agent.stages.helpers import is_substantially_shorter, load_route_payload


# 强改写只在少数结构混乱场景触发，尽量减少分块次数，避免模型漏段。
MAX_WECHAT_REWRITE_CHARS_PER_REQUEST = 7000


def build_wechat_rewrite_input(markdown: str) -> str:
    """把审校稿包装成公众号改写任务输入。"""
    return (
        "请把下面内容改写成适合公众号阅读的完整文章，必须保留所有信息、标题、列表、代码块与模板。\n\n"
        f"{markdown}"
    )


def build_wechat_rewrite_chunk_input(markdown: str, chunk: ChunkPromptContext) -> str:
    """多块改写时给模型明确“这是第几段”。

    如果把长文每一块都当成独立文章改写，模型很容易在每块都重复标题、导语和总结，
    最终拼接出的 `04-wechat.md` 就会像“多篇文章串在一起”。
    """

    chunk_label = f"第 {chunk.chunk_index + 1} / {chunk.chunk_count} 段"
    if chunk.chunk_count == 1:
        return build_wechat_rewrite_input(markdown)

    if chunk.is_first:
        instruction = "请正常产出标题、导语和正文结构，为整篇文章建立清晰开头，并完整保留这一段里的所有信息点。"
    elif chunk.is_last:
        instruction = "请延续前文即可，不要重复标题、导语或开场铺垫；如果内容自然结束，再收束全文，但不要漏掉本段的任何信息。"
    else:
        instruction = "请延续前文即可，不要重复标题、导语或开场铺垫，也不要提前总结全文；必须完整保留本段里的所有信息点。"

    return (
        "请把下面内容改写成公众号文章中的连续一段。\n"
        f"当前处理的是整篇文章的{chunk_label}。\n"
        f"{instruction}\n"
        "只输出这一段应有的 Markdown 正文，不要解释你的做法。\n\n"
        f"{markdown}"
    )


def run_wechat_rewrite(
    *,
    context: StageContext,
    store: JobStore,
    gateway: ModelGateway,
    settings: Settings,
) -> str:
    """公众号改写阶段。

    改写输出通常比输入更长，因此限制单次输入规模，给模型留出足够的生成空间。
    """
    route_payload = load_route_payload(store=store, job_id=context.job_id)
    if route_payload.get("decision") != "REWRITE":
        return store.read_artifact(job_id=context.job_id, relative_path="03-reviewed.md")

    reviewed_markdown = store.read_artifact(job_id=context.job_id, relative_path="03-reviewed.md")
    rewritten_markdown = run_chunked_markdown_stage(
        context=context,
        store=store,
        gateway=gateway,
        input_artifact="03-reviewed.md",
        output_artifact="06-rewritten.md",
        prompt_filename="wechat_rewrite_zh.txt",
        model=settings.stage_models["wechat-rewrite"],
        build_input=build_wechat_rewrite_input,
        build_chunk_input=build_wechat_rewrite_chunk_input,
        max_chars_per_request=MAX_WECHAT_REWRITE_CHARS_PER_REQUEST,
    )
    if is_substantially_shorter(reviewed_markdown, rewritten_markdown, min_ratio=0.8):
        raise ValueError("Rewrite output appears truncated compared with reviewed input; refusing to publish a shortened rewrite.")
    return rewritten_markdown
