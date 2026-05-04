from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from agent.prompts.loader import load_prompt


router = APIRouter()


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


@router.get("/prompts/{filename}")
def get_prompt(filename: str) -> PlainTextResponse:
    """暴露当前 Prompt 文本，便于在 UI 中直接查看每个阶段的提示词。"""
    try:
        content = load_prompt(filename)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Prompt not found") from exc

    return PlainTextResponse(content)
