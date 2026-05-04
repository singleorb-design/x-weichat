from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl, field_validator


router = APIRouter()
SUPPORTED_X_URL_MESSAGE = (
    "Supported URLs are X tweet URLs like https://x.com/<user>/status/<id> "
    "and X article URLs like https://x.com/i/articles/<id>."
)
TWEET_URL_PATTERN = re.compile(r"^https://(?:www\.)?x\.com/[A-Za-z0-9_]{1,15}/status/\d+(?:[/?#].*)?$")
ARTICLE_URL_PATTERN = re.compile(r"^https://(?:www\.)?x\.com/i/articles/\d+(?:[/?#].*)?$")


class CreateJobRequest(BaseModel):
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def validate_supported_x_url(cls, value: HttpUrl) -> HttpUrl:
        if is_supported_x_url(str(value)):
            return value

        raise ValueError(SUPPORTED_X_URL_MESSAGE)


def is_supported_x_url(url: str) -> bool:
    return bool(TWEET_URL_PATTERN.match(url) or ARTICLE_URL_PATTERN.match(url))


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
        raise HTTPException(status_code=409, detail="Job must be pending before run")

    background_tasks.add_task(request.app.state.pipeline.run, job_id, claim_token)
    return {
        "job_id": job_id,
        "status": "accepted",
    }
