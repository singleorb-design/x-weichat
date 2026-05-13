from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl, field_validator

from agent.models.schemas import RetryMode, StageError, StageName


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


class BatchCreateJobsRequest(BaseModel):
    urls_text: str
    run: bool = True

    @field_validator("urls_text")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("urls_text must not be empty")
        return value


class UpdateFinalMarkdownRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_non_empty_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be empty")
        return value


class SetPublishedRequest(BaseModel):
    published: bool


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


def _extract_first_url_candidate(line: str) -> str | None:
    """从一行文本里提取第一个 URL token。

    支持用户直接粘贴一行 URL，也支持带前后空格/注释的场景。
    """

    match = re.search(r"https?://\S+", line)
    if not match:
        return None

    candidate = match.group(0).strip().rstrip(",)")
    return candidate or None


@router.get("/jobs")
def list_jobs(request: Request) -> list[dict[str, object]]:
    jobs = request.app.state.store.list_jobs()
    return [job.model_dump(mode="json") for job in jobs]


@router.get("/jobs/trash")
def list_trash(request: Request) -> list[dict[str, object]]:
    jobs = request.app.state.store.list_trashed_jobs()
    return [job.model_dump(mode="json") for job in jobs]


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: CreateJobRequest, request: Request) -> dict[str, str]:
    job = request.app.state.pipeline.create_job(str(payload.url))
    return {
        "job_id": job.job_id,
        "status": job.status,
    }


@router.post("/jobs/batch")
def create_jobs_batch(
    payload: BatchCreateJobsRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, object]:
    """批量创建任务。

    输入支持：每行一个 X URL（tweet 或 article），可带 query 参数。
    默认行为：创建后立即调度运行（与单条提交行为保持一致）。
    """

    pipeline = request.app.state.pipeline
    store = request.app.state.store

    items: list[dict[str, object]] = []
    created = 0
    scheduled = 0
    invalid = 0

    for line_no, raw_line in enumerate(payload.urls_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        candidate = _extract_first_url_candidate(line)
        if not candidate or not is_supported_x_url(candidate):
            invalid += 1
            items.append(
                {
                    "line": line_no,
                    "input": raw_line,
                    "url": candidate,
                    "ok": False,
                    "job_id": None,
                    "status": None,
                    "error": SUPPORTED_X_URL_MESSAGE,
                }
            )
            continue

        try:
            job = pipeline.create_job(candidate)
            created += 1
        except Exception as exc:
            items.append(
                {
                    "line": line_no,
                    "input": raw_line,
                    "url": candidate,
                    "ok": False,
                    "job_id": None,
                    "status": None,
                    "error": str(exc),
                }
            )
            continue

        run_status: str | None = "pending"
        if payload.run:
            try:
                claim_token = store.claim_run(job_id=job.job_id)
                background_tasks.add_task(pipeline.run, job.job_id, claim_token)
                run_status = "accepted"
                scheduled += 1
            except Exception as exc:
                run_status = "pending"
                items.append(
                    {
                        "line": line_no,
                        "input": raw_line,
                        "url": candidate,
                        "ok": True,
                        "job_id": job.job_id,
                        "status": run_status,
                        "error": f"任务已创建，但调度运行失败：{exc}",
                    }
                )
                continue

        items.append(
            {
                "line": line_no,
                "input": raw_line,
                "url": candidate,
                "ok": True,
                "job_id": job.job_id,
                "status": run_status,
                "error": None,
            }
        )

    return {
        "items": items,
        "stats": {
            "created": created,
            "scheduled": scheduled,
            "invalid": invalid,
        },
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
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_locked_for_delete",
                message=str(exc),
                suggestion="当前任务仍在运行或排队中，等待它结束后再删除。",
            ),
        ) from exc


@router.post("/jobs/{job_id}/restore")
def restore_job(job_id: str, request: Request) -> dict[str, object]:
    try:
        job = request.app.state.store.restore_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_restore_conflict",
                message=str(exc),
                suggestion="任务无法恢复；请刷新回收站状态后重试。",
            ),
        ) from exc

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


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str, request: Request) -> dict[str, object]:
    """停止一个卡住的任务。

    设计目标：
    - 让用户在 UI 中可以对 running 任务做“停止”，避免卡死占用列表。
    - 停止后任务应可被删除。

    注意：当前执行是在后台线程内进行，stop 是“逻辑停止”（将状态标记为 canceled），
    正在执行的阶段会在下一次状态检查点停止推进。
    """

    store = request.app.state.store
    try:
        job = store.read_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    if job.status in {"succeeded", "failed", "canceled", "published"}:
        return job.model_dump(mode="json")

    stage = job.current_stage
    if stage:
        try:
            store.update_stage_metadata(
                job_id=job_id,
                stage=stage,
                error=StageError(
                    error_type="job_canceled",
                    message="任务已被用户手动停止",
                    retryable=False,
                    suggestion="如需继续可在 UI 中选择阶段重跑。",
                ),
            )
        except Exception:
            pass

    try:
        job = store.update_status(job_id=job_id, status="canceled")
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_stop_conflict",
                message=str(exc),
                suggestion="当前任务状态无法停止；请刷新状态后重试。",
            ),
        ) from exc

    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/published")
def set_published(job_id: str, payload: SetPublishedRequest, request: Request) -> dict[str, object]:
    """手动标记任务为已发布（published）。

    仅允许：
    - succeeded -> published
    - published -> succeeded（撤销）
    """

    store = request.app.state.store
    try:
        job = store.read_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    if payload.published:
        if job.status in {"published"}:
            return job.model_dump(mode="json")
        if job.status != "succeeded":
            raise HTTPException(
                status_code=409,
                detail=conflict_detail(
                    code="job_not_publishable",
                    message=f"Job status {job.status} cannot be marked as published",
                    suggestion="只有 succeeded 的任务才可以标记为已发布。",
                ),
            )
        try:
            updated = store.update_status(job_id=job_id, status="published")
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=conflict_detail(
                    code="job_publish_conflict",
                    message=str(exc),
                    suggestion="当前任务状态无法标记为已发布；请刷新列表后重试。",
                ),
            ) from exc
        return updated.model_dump(mode="json")

    # payload.published == False: allow unpublish for corrections.
    if job.status in {"succeeded"}:
        return job.model_dump(mode="json")
    if job.status != "published":
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_not_unpublishable",
                message=f"Job status {job.status} cannot be un-published",
                suggestion="只有 published 的任务才可以撤销发布。",
            ),
        )
    try:
        updated = store.update_status(job_id=job_id, status="succeeded")
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_unpublish_conflict",
                message=str(exc),
                suggestion="当前任务状态无法撤销发布；请刷新列表后重试。",
            ),
        ) from exc
    return updated.model_dump(mode="json")


@router.put("/jobs/{job_id}/final-markdown")
def update_final_markdown(
    job_id: str,
    payload: UpdateFinalMarkdownRequest,
    request: Request,
) -> dict[str, str]:
    store = request.app.state.store
    try:
        job = store.read_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    if job.status == "running":
        raise HTTPException(
            status_code=409,
            detail=conflict_detail(
                code="job_locked_for_final_markdown_edit",
                message=f"Job {job.job_id} is running and cannot edit final markdown yet",
                suggestion="请等待当前任务完成或先停止任务，再编辑最终稿并重新生成 HTML。",
            ),
        )

    store.write_artifact(job_id=job_id, relative_path="10-final.md", content=payload.content)
    return {
        "job_id": job_id,
        "status": "saved",
        "relative_path": "10-final.md",
    }
