from __future__ import annotations

import mimetypes

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from agent.prompts.loader import load_prompt
from agent.models.schemas import StageName
from agent.stages.render_html import render_markdown_to_html


router = APIRouter()


class StageHtmlPreviewRequest(BaseModel):
    stage: StageName
    force: bool = Field(default=False)


@router.get("/jobs/{job_id}/artifacts-index")
def list_artifacts(job_id: str, request: Request) -> dict[str, object]:
    """列出当前 job 已生成的可公开访问产物。

    主要用于 UI 调试：展示每次模型请求/返回、diff 等 trace 文件。
    """
    try:
        files = request.app.state.store.list_public_artifacts(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    return {"job_id": job_id, "files": files}


@router.get("/jobs/{job_id}/artifacts/{artifact_path:path}")
def get_artifact(job_id: str, artifact_path: str, request: Request) -> Response:
    """返回任务产物。

    Markdown 以纯文本返回，HTML 以 `text/html` 返回，
    方便前端分别用于源码查看和 iframe 预览。
    """
    try:
        file_path = request.app.state.store.resolve_public_artifact_path(
            job_id=job_id,
            relative_path=artifact_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if "/" not in artifact_path and artifact_path.endswith(".html"):
        content = file_path.read_text(encoding="utf-8")
        return HTMLResponse(content)

    if "/" not in artifact_path:
        content = file_path.read_text(encoding="utf-8")
        return PlainTextResponse(content)

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@router.post("/jobs/{job_id}/html-preview")
def generate_stage_html_preview(job_id: str, payload: StageHtmlPreviewRequest, request: Request) -> dict[str, object]:
    """按阶段生成 HTML 预览文件，供 UI iframe 加载。

    生成结果写入 `preview.assets/<stage>.html`，并返回可访问的 artifact_path。
    """

    store = request.app.state.store
    stage = payload.stage

    # render-html 阶段本身已经产出 11-wechat.html，优先复用。
    if stage == "render-html":
        try:
            store.resolve_public_artifact_path(job_id=job_id, relative_path="11-wechat.html")
            return {
                "job_id": job_id,
                "stage": stage,
                "source_artifact": "11-wechat.html",
                "artifact_path": "11-wechat.html",
                "status": "ready",
            }
        except Exception:
            # 如果 render-html 还没跑完，则降级用 final-output 的 Markdown 现渲。
            pass

    stage_to_markdown = {
        "x-fetch": "01-source.md",
        "translate": "02-translation.md",
        "review": "03-reviewed.md",
        # route 阶段本身输出 JSON，但阅读体验更依赖当时的 Markdown 候选稿。
        "route": "03-reviewed.md",
        "light-polish": "05-polished.md",
        "final-check": "07-final-candidate.md",
        "targeted-fix": "09-final-fixed.md",
        "final-output": "10-final.md",
    }

    source_artifact = stage_to_markdown.get(stage)
    if not source_artifact:
        raise HTTPException(status_code=400, detail="Unsupported stage")

    preview_path = f"preview.assets/{stage}.html"
    if not payload.force:
        try:
            store.resolve_public_artifact_path(job_id=job_id, relative_path=preview_path)
            return {
                "job_id": job_id,
                "stage": stage,
                "source_artifact": source_artifact,
                "artifact_path": preview_path,
                "status": "cached",
            }
        except Exception:
            pass

    try:
        markdown = store.read_artifact(job_id=job_id, relative_path=source_artifact)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stage artifact not found") from exc

    html = render_markdown_to_html(markdown=markdown, input_name=source_artifact)
    store.write_public_asset(job_id=job_id, relative_path=preview_path, content=html)

    return {
        "job_id": job_id,
        "stage": stage,
        "source_artifact": source_artifact,
        "artifact_path": preview_path,
        "status": "generated",
    }


@router.get("/prompts/{filename}")
def get_prompt(filename: str) -> PlainTextResponse:
    """暴露当前 Prompt 文本，便于在 UI 中直接查看每个阶段的提示词。"""
    try:
        content = load_prompt(filename)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Prompt not found") from exc

    return PlainTextResponse(content)
