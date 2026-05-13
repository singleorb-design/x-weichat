from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from agent.jobs.store import JobStore
from agent.stages.base import StageContext


def renderer_cli_path() -> Path:
    return Path(__file__).resolve().parents[2] / "packages" / "renderer" / "dist" / "index.js"


def render_html(input_path: Path, output_path: Path) -> None:
    cli_path = renderer_cli_path()
    if not cli_path.is_file():
        raise FileNotFoundError(
            f"Renderer CLI not found: {cli_path}. Build the in-repo renderer with `npm --prefix packages/renderer run build`."
        )

    subprocess.run(
        ["node", str(cli_path), str(input_path), str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def render_markdown_to_html(*, markdown: str, input_name: str) -> str:
    """把任意 Markdown 渲染为 HTML 字符串（不写入 JobStore）。"""
    with TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / input_name
        output_path = Path(temp_dir) / "preview.html"
        input_path.write_text(markdown, encoding="utf-8")

        render_html(input_path, output_path)

        html = output_path.read_text(encoding="utf-8")

    # 如果输入 Markdown 自带一级标题（`# ...`），避免 renderer 再额外注入一个 <article><h1>...</h1> 造成重复标题。
    if markdown.lstrip().startswith("# "):
        html = re.sub(
            r"(<article[^>]*>\s*)<h1[^>]*>.*?</h1>",
            r"\1",
            html,
            count=1,
            flags=re.DOTALL,
        )

    return html


def run_render_html(*, context: StageContext, store: JobStore) -> str:
    try:
        markdown = store.read_artifact(job_id=context.job_id, relative_path="10-final.md")
        input_name = "10-final.md"
    except FileNotFoundError:
        markdown = store.read_artifact(job_id=context.job_id, relative_path="03-reviewed.md")
        input_name = "03-reviewed.md"

    html = render_markdown_to_html(markdown=markdown, input_name=input_name)

    store.write_artifact(
        job_id=context.job_id,
        relative_path="11-wechat.html",
        content=html,
    )
    return html
