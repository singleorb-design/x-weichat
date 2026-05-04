from pathlib import Path
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


def run_render_html(*, context: StageContext, store: JobStore) -> str:
    markdown = store.read_artifact(job_id=context.job_id, relative_path="10-final.md")

    with TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "10-final.md"
        output_path = Path(temp_dir) / "11-wechat.html"
        input_path.write_text(markdown, encoding="utf-8")

        render_html(input_path, output_path)

        html = output_path.read_text(encoding="utf-8")

    store.write_artifact(
        job_id=context.job_id,
        relative_path="11-wechat.html",
        content=html,
    )
    return html
