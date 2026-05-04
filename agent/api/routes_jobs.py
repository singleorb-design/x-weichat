from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl, field_validator

from agent.models.schemas import RetryMode, StageName


router = APIRouter()
SUPPORTED_X_URL_MESSAGE = (
    "Supported URLs are X tweet URLs like https://x.com/<user>/status/<id> "
    "and X article URLs like https://x.com/i/article/<id>, https://x.com/i/articles/<id>, "
    "or https://x.com/<user>/article/<id>."
)
TWEET_URL_PATTERN = re.compile(r"^https://(?:www\.)?x\.com/[A-Za-z0-9_]{1,15}/status/\d+(?:[/?#].*)?$")
ARTICLE_URL_PATTERN = re.compile(
    r"^https://(?:www\.)?x\.com/(?:(?:i/articles?)|(?:[A-Za-z0-9_]{1,15}/article))/\d+(?:[/?#].*)?$"
)


class CreateJobRequest(BaseModel):
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def validate_supported_x_url(cls, value: HttpUrl) -> HttpUrl:
        if is_supported_x_url(str(value)):
            return value

        raise ValueError(SUPPORTED_X_URL_MESSAGE)


class RetryJobRequest(BaseModel):
    stage: StageName
    mode: RetryMode


def conflict_detail(
    *,
    code: str,
    message: str,
    suggestion: str,
    can_change_stage: bool = False,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "suggestion": suggestion,
        "can_change_stage": can_change_stage,
    }


def is_supported_x_url(url: str) -> bool:
    return bool(TWEET_URL_PATTERN.match(url) or ARTICLE_URL_PATTERN.match(url))


@router.get("/jobs")
def list_jobs(request: Request) -> list[dict[str, object]]:
    jobs = request.app.state.store.list_jobs()
    return [job.model_dump(mode="json") for job in jobs]


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: CreateJobRequest, request: Request) -> dict[str, str]:
    job = request.app.state.pipeline.create_job(str(payload.url))
    return {
        "job_id": job.job_id,
        "status": job.status,
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, object]:
    try:
        job = request.app.state.store.read_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    return job.model_dump(mode="json")


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, request: Request) -> None:
    try:
        request.app.state.store.delete_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_locked_for_delete",
                message=str(exc),
                suggestion="当前任务仍在运行或排队中，等待它结束后再删除。",
            ),
        ) from exc


@router.post("/jobs/{job_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    try:
        claim_token = request.app.state.store.claim_run(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_not_pending_for_run",
                message="Job must be pending before run",
                suggestion="只有 pending 任务可以开始运行；如果你想重新执行已完成或失败的任务，请使用重跑。",
            ),
        ) from exc

    background_tasks.add_task(request.app.state.pipeline.run, job_id, claim_token)
    return {
        "job_id": job_id,
        "status": "accepted",
    }


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str,
    payload: RetryJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    try:
        claim_token = request.app.state.store.claim_execution(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_retry_claim_conflict",
                message=str(exc),
                suggestion=(
                    "这个任务已经有一次运行或重跑在进行中。先等当前执行结束，再决定是否继续重跑；"
                    "如果刚才起始阶段选错了，任务恢复到 succeeded / failed 后，可以直接重新选择阶段再试。"
                ),
                can_change_stage=True,
            ),
        ) from exc

    background_tasks.add_task(
        request.app.state.pipeline.retry,
        job_id,
        stage=payload.stage,
        mode=payload.mode,
        claim_token=claim_token,
    )
    return {
        "job_id": job_id,
        "status": "accepted",
        "stage": payload.stage,
        "mode": payload.mode,
    }
