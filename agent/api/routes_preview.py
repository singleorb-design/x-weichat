from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response


router = APIRouter()


@router.get("/jobs/{job_id}/artifacts/{filename}")
def get_artifact(job_id: str, filename: str, request: Request) -> Response:
    try:
        content = request.app.state.store.read_artifact(
            job_id=job_id,
            relative_path=filename,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if filename.endswith(".html"):
        return HTMLResponse(content)

    return PlainTextResponse(content)
