# Stage Retry And Modern Red Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `x-to-wechat-agent` 增加“失败阶段重试 + 从任意阶段重跑”能力，并将 `render-html` 替换为仓库内置的 `modern red` 风格渲染实现。

**Architecture:** 后端继续沿用单 `job` / 单工作目录模型，在 `JobStore` 中集中实现“按阶段重置尾部状态”，由 `PipelineRunner` 从指定阶段继续执行到末尾。前端在失败态卡片上提供默认重试入口，并在任务详情中提供高级“从该阶段重跑”入口。渲染器保持 Python 调仓库内 Node CLI 的边界不变，但把 `modern red` 所需的模板、样式和辅助逻辑 vendor 到 `packages/renderer/src/vendor/modern-red/` 中，保持本仓库可构建、可测试、可版本化。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、pytest、React 18、TypeScript、Vitest、Node.js、marked。

---

## File Map

**Backend retry core**
- Modify: `agent/models/schemas.py`
- Modify: `agent/jobs/store.py`
- Modify: `agent/core/pipeline.py`
- Modify: `agent/api/routes_jobs.py`
- Test: `tests/test_job_store.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_api_jobs.py`

**Frontend retry UI**
- Modify: `apps/web/src/types.ts`
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/JobStatus.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/app.test.tsx`

**Renderer modern red vendor**
- Modify: `agent/stages/render_html.py`
- Modify: `packages/renderer/src/index.ts`
- Modify: `packages/renderer/src/render.ts`
- Modify: `packages/renderer/src/template.ts`
- Create: `packages/renderer/src/vendor/modern-red/index.ts`
- Create: `packages/renderer/src/vendor/modern-red/template.ts`
- Create: `packages/renderer/src/vendor/modern-red/styles.ts`
- Create: `packages/renderer/src/vendor/modern-red/content.ts`
- Test: `packages/renderer/src/render.test.ts`

### Task 1: Add shared retry types and JobStore reset support

**Files:**
- Modify: `agent/models/schemas.py`
- Modify: `agent/jobs/store.py`
- Test: `tests/test_job_store.py`

- [ ] **Step 1: Write the failing tests for tail reset semantics**

```python
def test_reset_for_retry_from_review_clears_tail_artifacts_and_metadata(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    for name in ["01-source.md", "02-translation.md", "03-reviewed.md", "04-wechat.md", "05-wechat.html"]:
        store.write_artifact(job_id=job.job_id, relative_path=name, content=f"{name}\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_stage_metadata(job_id=job.job_id, stage="review", provider="qwen", model="qwen-plus", prompt_version="review_zh.txt", duration=1.2)
    store.update_stage_metadata(job_id=job.job_id, stage="wechat-rewrite", provider="qwen", model="qwen-max", prompt_version="wechat_rewrite_zh.txt", duration=2.3)
    store.update_status(job_id=job.job_id, status="failed", current_stage="wechat-rewrite")

    reset = store.reset_for_retry(job_id=job.job_id, stage="review")

    assert reset.status == "pending"
    assert reset.current_stage == "review"
    assert (tmp_path / job.job_id / "01-source.md").is_file()
    assert (tmp_path / job.job_id / "02-translation.md").is_file()
    assert not (tmp_path / job.job_id / "03-reviewed.md").exists()
    assert not (tmp_path / job.job_id / "04-wechat.md").exists()
    assert not (tmp_path / job.job_id / "05-wechat.html").exists()
    assert "review" not in reset.stage_durations
    assert "wechat-rewrite" not in reset.stage_durations


def test_reset_for_retry_from_render_html_only_removes_html(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/a/status/1")
    for name in ["01-source.md", "02-translation.md", "03-reviewed.md", "04-wechat.md", "05-wechat.html"]:
        store.write_artifact(job_id=job.job_id, relative_path=name, content=f"{name}\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="succeeded", current_stage="render-html")

    reset = store.reset_for_retry(job_id=job.job_id, stage="render-html")

    assert reset.status == "pending"
    assert reset.current_stage == "render-html"
    assert (tmp_path / job.job_id / "04-wechat.md").is_file()
    assert not (tmp_path / job.job_id / "05-wechat.html").exists()
```

- [ ] **Step 2: Run the targeted store tests to verify they fail**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_job_store.py -k reset_for_retry`

Expected: FAIL with `AttributeError: 'JobStore' object has no attribute 'reset_for_retry'` or equivalent missing-symbol error.

- [ ] **Step 3: Add retry enums/stage helpers and implement `JobStore.reset_for_retry()`**

```python
# agent/models/schemas.py
StageName = Literal["x-fetch", "translate", "review", "wechat-rewrite", "render-html"]
RetryMode = Literal["failed-stage", "from-stage"]


# agent/jobs/store.py
STAGE_TO_ARTIFACT = {
    "x-fetch": "01-source.md",
    "translate": "02-translation.md",
    "review": "03-reviewed.md",
    "wechat-rewrite": "04-wechat.md",
    "render-html": "05-wechat.html",
}

def reset_for_retry(self, *, job_id: str, stage: str) -> JobRecord:
    record = self.read_job(job_id)
    if record.status == "running":
        raise ValueError(f"Job {job_id} is scheduled or running and cannot be retried")

    stages = JobRecord.ALLOWED_STAGES
    if stage not in stages:
        allowed = ", ".join(stages)
        raise ValueError(f"stage must be one of: {allowed}")

    stage_index = stages.index(stage)
    stages_to_clear = stages[stage_index:]
    for retry_stage in stages_to_clear:
        artifact_name = STAGE_TO_ARTIFACT[retry_stage]
        artifact_path = self._job_dir(job_id) / artifact_name
        artifact_path.unlink(missing_ok=True)

    payload = record.model_dump(mode="python") | {
        "status": "pending",
        "current_stage": stage,
        "started_at": None,
        "finished_at": None,
        "stage_models": {k: v for k, v in record.stage_models.items() if k not in stages_to_clear},
        "prompt_versions": {k: v for k, v in record.prompt_versions.items() if k not in stages_to_clear},
        "stage_durations": {k: v for k, v in record.stage_durations.items() if k not in stages_to_clear},
        "stage_errors": {k: v for k, v in record.stage_errors.items() if k not in stages_to_clear},
    }
    updated = JobRecord.model_validate(payload)
    self._write_job(updated)
    return updated
```

- [ ] **Step 4: Re-run the store tests and the broader JobStore suite**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_job_store.py`

Expected: PASS for the new `reset_for_retry` tests and no regressions in existing JobStore tests.

- [ ] **Step 5: Commit the isolated JobStore groundwork**

```bash
git add agent/models/schemas.py agent/jobs/store.py tests/test_job_store.py
git commit -m "feat: add staged job retry reset support"
```

### Task 2: Teach `PipelineRunner` to execute from an arbitrary stage

**Files:**
- Modify: `agent/core/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests for retry execution from a specified stage**

```python
def test_pipeline_runner_retry_runs_tail_only_from_review(tmp_path: Path, monkeypatch) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="01-source.md", content="# source\n")
    store.write_artifact(job_id=job.job_id, relative_path="02-translation.md", content="# translation\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")
    store.update_status(job_id=job.job_id, status="failed", current_stage="review")

    calls: list[str] = []
    monkeypatch.setattr("agent.core.pipeline.run_review", lambda **kwargs: calls.append("review") or "reviewed")
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", lambda **kwargs: calls.append("wechat-rewrite") or "wechat")
    monkeypatch.setattr("agent.core.pipeline.run_render_html", lambda **kwargs: calls.append("render-html") or "html")

    result = runner.retry(job.job_id, stage="review", mode="failed-stage")

    assert result.status == "succeeded"
    assert calls == ["review", "wechat-rewrite", "render-html"]


def test_pipeline_runner_retry_rejects_failed_stage_mode_when_stage_does_not_match(tmp_path: Path) -> None:
    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store, gateway=object(), settings=Settings(api_key="test-key", artifacts_dir=str(tmp_path)))
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="wechat-rewrite")
    store.update_status(job_id=job.job_id, status="failed", current_stage="wechat-rewrite")

    with pytest.raises(ValueError, match="failed stage"):
        runner.retry(job.job_id, stage="review", mode="failed-stage")
```

- [ ] **Step 2: Run the focused pipeline retry tests to verify they fail**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_pipeline.py -k retry_runs_tail_only_from_review or retry_rejects_failed_stage_mode`

Expected: FAIL because `PipelineRunner.retry` does not exist yet.

- [ ] **Step 3: Implement `PipelineRunner.retry()` and a shared execution helper**

```python
# agent/core/pipeline.py
def retry(self, job_id: str, *, stage: str, mode: str, claim_token: str | None = None) -> JobRecord:
    if claim_token is None:
        claim_token = self.store.claim_execution(job_id=job_id)
    self.store.verify_run_claim(job_id=job_id, claim_token=claim_token)

    job = self.store.read_job(job_id)
    if mode == "failed-stage":
        if job.status != "failed" or job.current_stage != stage:
            raise ValueError("failed stage retry requires the requested stage to match the failed current_stage")
    elif mode == "from-stage":
        if job.status == "pending":
            raise ValueError("from-stage retry requires a previously executed job")
    else:
        raise ValueError(f"Unsupported retry mode: {mode}")

    self.store.consume_run_claim(job_id=job_id, claim_token=claim_token)
    self.store.reset_for_retry(job_id=job_id, stage=stage)
    return self._execute_from_stage(job_id=job_id, start_stage=stage)


def _execute_from_stage(self, *, job_id: str, start_stage: str) -> JobRecord:
    job = self.store.read_job(job_id)
    stages = self.STAGE_ORDER[self.STAGE_ORDER.index(start_stage):]
    self.store.update_status(job_id=job_id, status="running", current_stage=start_stage)
    context = StageContext(job_id=job.job_id, url=job.url, storage_state=getattr(self.settings, "x_storage_state_path", None))
    for index, stage in enumerate(stages):
        if index > 0:
            self.store.update_status(job_id=job_id, status="running", current_stage=stage)
        started_at = perf_counter()
        try:
            self._run_stage(stage=stage, context=context)
            self._record_stage_success(job_id=job_id, stage=stage, duration=perf_counter() - started_at)
        except Exception as exc:
            return self._fail_job(job_id=job_id, stage=stage, exc=exc, duration=perf_counter() - started_at)
    return self.store.update_status(job_id=job_id, status="succeeded", current_stage=stages[-1])
```

- [ ] **Step 4: Run the pipeline suite and verify retry semantics hold**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_pipeline.py`

Expected: PASS for the new retry tests and the existing pipeline chain tests.

- [ ] **Step 5: Commit the retry execution logic**

```bash
git add agent/core/pipeline.py tests/test_pipeline.py
git commit -m "feat: support retrying pipeline from a stage"
```

### Task 3: Expose `POST /api/jobs/{job_id}/retry`

**Files:**
- Modify: `agent/api/routes_jobs.py`
- Test: `tests/test_api_jobs.py`

- [ ] **Step 1: Write failing API tests for retry acceptance and conflicts**

```python
def test_retry_job_returns_accepted_status(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")
    store.update_status(job_id=job.job_id, status="failed", current_stage="review")
    calls: list[tuple[str, str, str, str | None]] = []

    def fake_retry(job_id: str, *, stage: str, mode: str, claim_token: str | None = None):
        calls.append((job_id, stage, mode, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "retry", fake_retry)

    response = client.post(f"/api/jobs/{job.job_id}/retry", json={"stage": "review", "mode": "failed-stage"})

    assert response.status_code == 202
    assert response.json() == {"job_id": job.job_id, "status": "accepted", "stage": "review", "mode": "failed-stage"}
    assert calls == [(job.job_id, "review", "failed-stage", calls[0][3])]


def test_retry_job_rejects_running_job(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")

    response = client.post(f"/api/jobs/{job.job_id}/retry", json={"stage": "review", "mode": "failed-stage"})

    assert response.status_code == 409
```

- [ ] **Step 2: Run the API retry tests to verify they fail**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_api_jobs.py -k retry_job`

Expected: FAIL because the `/retry` route and `RetryJobRequest` do not exist.

- [ ] **Step 3: Add the request model and retry route**

```python
# agent/api/routes_jobs.py
class RetryJobRequest(BaseModel):
    stage: str
    mode: str


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: str, payload: RetryJobRequest, background_tasks: BackgroundTasks, request: Request) -> dict[str, str]:
    try:
        claim_token = request.app.state.store.claim_execution(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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
```

- [ ] **Step 4: Run the full API suite**

Run: `PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_api_jobs.py`

Expected: PASS for the new retry route tests and the pre-existing job route tests.

- [ ] **Step 5: Commit the API surface**

```bash
git add agent/api/routes_jobs.py tests/test_api_jobs.py
git commit -m "feat: add job retry api"
```

### Task 4: Add the default failed-stage retry UI

**Files:**
- Modify: `apps/web/src/types.ts`
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/JobStatus.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/app.test.tsx`

- [ ] **Step 1: Write the failing frontend test for “重试此阶段”**

```tsx
it('retries the failed stage from the error card and clears stale artifact content', async () => {
  fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const method = init?.method ?? 'GET'
    if (url === '/api/jobs' && method === 'GET') {
      return Promise.resolve(jsonResponse([{ job_id: 'job-failed', url: 'https://x.com/a/status/1', created_at: '2026-05-03T00:00:00Z', status: 'failed', current_stage: 'review', started_at: '2026-05-03T00:00:01Z', finished_at: '2026-05-03T00:00:10Z', stage_models: {}, prompt_versions: {}, stage_durations: { review: 9 }, stage_errors: { review: { error_type: 'RuntimeError', message: 'boom', retryable: true, suggestion: 'retry' } } }]))
    }
    if (url === '/api/jobs/job-failed' && method === 'GET') {
      return Promise.resolve(jsonResponse({ job_id: 'job-failed', url: 'https://x.com/a/status/1', created_at: '2026-05-03T00:00:00Z', status: 'failed', current_stage: 'review', started_at: '2026-05-03T00:00:01Z', finished_at: '2026-05-03T00:00:10Z', stage_models: {}, prompt_versions: {}, stage_durations: { review: 9 }, stage_errors: { review: { error_type: 'RuntimeError', message: 'boom', retryable: true, suggestion: 'retry' } } }))
    }
    if (url === '/api/jobs/job-failed/retry' && method === 'POST') {
      expect(JSON.parse(String(init?.body))).toEqual({ stage: 'review', mode: 'failed-stage' })
      return Promise.resolve(jsonResponse({ job_id: 'job-failed', status: 'accepted', stage: 'review', mode: 'failed-stage' }, 202))
    }
    return Promise.resolve(textResponse('artifact body'))
  })

  await act(async () => {
    root.render(<App />)
    await flushMicrotasks()
  })

  const retryButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '重试此阶段')
  expect(retryButton).not.toBeUndefined()

  await act(async () => {
    retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-failed/retry', expect.objectContaining({ method: 'POST' }))
})
```

- [ ] **Step 2: Run the focused frontend retry test and confirm it fails**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" test -- --runInBand`

Expected: FAIL because there is no retry API helper, no retry UI, and no retry props in `JobStatus`.

- [ ] **Step 3: Add retry types, API helper, app handlers, and the failed-stage button**

```ts
// apps/web/src/types.ts
export type StageName = 'x-fetch' | 'translate' | 'review' | 'wechat-rewrite' | 'render-html'
export type RetryMode = 'failed-stage' | 'from-stage'
export interface RetryJobRequest { stage: StageName; mode: RetryMode }
export interface RetryJobResponse { job_id: string; status: string; stage: StageName; mode: RetryMode }


// apps/web/src/api.ts
export async function retryJob(jobId: string, payload: RetryJobRequest): Promise<RetryJobResponse> {
  const response = await fetch(`/api/jobs/${jobId}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseJson<RetryJobResponse>(response)
}


// apps/web/src/App.tsx
const [retrying, setRetrying] = useState(false)
const [retryError, setRetryError] = useState<string | null>(null)

const handleRetryFailedStage = async () => {
  if (!jobId || !job?.current_stage) return
  setRetrying(true)
  setRetryError(null)
  setArtifactContent(null)
  setArtifactError(null)
  try {
    await retryJob(jobId, { stage: job.current_stage as StageName, mode: 'failed-stage' })
    setPollTick(0)
  } catch (error) {
    setRetryError(error instanceof Error ? error.message : '阶段重试失败')
  } finally {
    setRetrying(false)
  }
}


// apps/web/src/components/JobStatus.tsx
interface JobStatusProps {
  ...
  retryBusy: boolean
  retryError: string | null
  onRetryFailedStage: (() => void) | null
}
```

- [ ] **Step 4: Re-run the frontend tests, then verify the app build**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" test && npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" run build`

Expected: PASS for the new retry interaction test and a successful TypeScript/Vite build.

- [ ] **Step 5: Commit the default retry UX**

```bash
git add apps/web/src/types.ts apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/components/JobStatus.tsx apps/web/src/styles.css apps/web/src/app.test.tsx
git commit -m "feat: add failed-stage retry controls"
```

### Task 5: Add the advanced “从该阶段重跑” UI

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/JobStatus.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/app.test.tsx`

- [ ] **Step 1: Write the failing test for the advanced retry selector**

```tsx
it('allows retrying a finished job from a selected stage', async () => {
  fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const method = init?.method ?? 'GET'
    if (url === '/api/jobs' && method === 'GET') {
      return Promise.resolve(jsonResponse([{ job_id: 'job-done', url: 'https://x.com/a/status/1', created_at: '2026-05-03T00:00:00Z', status: 'succeeded', current_stage: 'render-html', started_at: '2026-05-03T00:00:01Z', finished_at: '2026-05-03T00:00:10Z', stage_models: {}, prompt_versions: {}, stage_durations: {}, stage_errors: {} }]))
    }
    if (url === '/api/jobs/job-done' && method === 'GET') {
      return Promise.resolve(jsonResponse({ job_id: 'job-done', url: 'https://x.com/a/status/1', created_at: '2026-05-03T00:00:00Z', status: 'succeeded', current_stage: 'render-html', started_at: '2026-05-03T00:00:01Z', finished_at: '2026-05-03T00:00:10Z', stage_models: {}, prompt_versions: {}, stage_durations: {}, stage_errors: {} }))
    }
    if (url === '/api/jobs/job-done/retry' && method === 'POST') {
      expect(JSON.parse(String(init?.body))).toEqual({ stage: 'wechat-rewrite', mode: 'from-stage' })
      return Promise.resolve(jsonResponse({ job_id: 'job-done', status: 'accepted', stage: 'wechat-rewrite', mode: 'from-stage' }, 202))
    }
    return Promise.resolve(textResponse('ok'))
  })

  await act(async () => {
    root.render(<App />)
    await flushMicrotasks()
  })

  const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) => item.textContent?.includes('job-done'))
  await act(async () => {
    jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })

  const select = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement
  await act(async () => {
    updateInputValue(select as unknown as HTMLInputElement, 'wechat-rewrite')
    await flushMicrotasks()
  })
  const button = Array.from(container.querySelectorAll('button')).find((item) => item.textContent === '从该阶段重跑')
  await act(async () => {
    button!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
  expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-done/retry', expect.objectContaining({ method: 'POST' }))
})
```

- [ ] **Step 2: Run the frontend suite to verify the advanced path fails first**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" test`

Expected: FAIL because there is no advanced selector or `from-stage` handler yet.

- [ ] **Step 3: Implement the selected-stage retry controls and guardrails**

```tsx
// apps/web/src/App.tsx
const [retryStage, setRetryStage] = useState<StageName>('render-html')

const handleRetryFromStage = async () => {
  if (!jobId) return
  setRetrying(true)
  setRetryError(null)
  setArtifactContent(null)
  setArtifactError(null)
  try {
    await retryJob(jobId, { stage: retryStage, mode: 'from-stage' })
  } catch (error) {
    setRetryError(error instanceof Error ? error.message : '从指定阶段重跑失败')
  } finally {
    setRetrying(false)
  }
}


// apps/web/src/components/JobStatus.tsx
{jobId ? (
  <div className="retry-panel">
    <strong>高级操作</strong>
    <p className="muted">从选中阶段重新生成该阶段及其后续产物。</p>
    <label>
      <span>起始阶段</span>
      <select name="retry-stage" value={retryStage} onChange={(event) => onRetryStageChange?.(event.target.value)} disabled={retryDisabled}>
        <option value="x-fetch">原文抓取</option>
        <option value="translate">翻译</option>
        <option value="review">审阅</option>
        <option value="wechat-rewrite">公众号改写</option>
        <option value="render-html">HTML 渲染</option>
      </select>
    </label>
    <button type="button" disabled={retryDisabled} onClick={onRetryFromStage}>从该阶段重跑</button>
  </div>
) : null}
```

- [ ] **Step 4: Re-run the frontend suite and verify no regressions**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" test && npm --prefix "/Users/bytedance/GolandProjects/x-weichat/apps/web" run build`

Expected: PASS for both failed-stage retry and from-stage retry scenarios.

- [ ] **Step 5: Commit the advanced retry controls**

```bash
git add apps/web/src/App.tsx apps/web/src/components/JobStatus.tsx apps/web/src/styles.css apps/web/src/app.test.tsx
git commit -m "feat: add selected-stage retry controls"
```

### Task 6: Vendor the `modern red` renderer subset into the repo

**Files:**
- Modify: `packages/renderer/src/render.ts`
- Modify: `packages/renderer/src/template.ts`
- Modify: `packages/renderer/src/index.ts`
- Create: `packages/renderer/src/vendor/modern-red/index.ts`
- Create: `packages/renderer/src/vendor/modern-red/template.ts`
- Create: `packages/renderer/src/vendor/modern-red/styles.ts`
- Create: `packages/renderer/src/vendor/modern-red/content.ts`
- Modify: `packages/renderer/src/render.test.ts`
- Modify: `agent/stages/render_html.py`

- [ ] **Step 1: Write renderer tests that lock the `modern red` structure and safety behavior**

```ts
it('renders modern red style wrappers for headings, blockquotes, tables, and code blocks', () => {
  const html = renderWechatHtml('---\ntitle: "外层标题"\n---\n\n# 正文标题\n\n> 引用\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n```ts\nconsole.log(1)\n```')
  expect(html).toContain('<title>外层标题</title>')
  expect(html).toMatch(/modern|wechat|article/i)
  expect(html).toContain('<blockquote')
  expect(html).toContain('<table')
  expect(html).toContain('<pre')
  expect(html).toContain('A93226')
})

it('keeps blocking unsafe urls after switching to modern red', () => {
  const html = renderWechatHtml('[危险链接](javascript:alert(1))')
  expect(html).not.toContain('javascript:alert(1)')
})
```

- [ ] **Step 2: Run the renderer tests to verify the current simplified template fails them**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/packages/renderer" test`

Expected: FAIL because the current renderer does not emit the `modern red` wrapper/style structure.

- [ ] **Step 3: Vendor the needed `modern red` subset and route `renderWechatHtml()` through it**

```ts
// packages/renderer/src/vendor/modern-red/styles.ts
export const MODERN_RED_PRIMARY = '#A93226'
export const MODERN_RED_STYLES = `
  :root { --md-primary: ${MODERN_RED_PRIMARY}; }
  body { background: #f6f2ed; color: #2b2118; }
  .wechat-article { max-width: 860px; margin: 0 auto; }
  .wechat-article-title { color: var(--md-primary); }
  blockquote { border-left: 4px solid var(--md-primary); background: #fbf4ef; }
`


// packages/renderer/src/vendor/modern-red/template.ts
export function renderModernRedPage(body: string, title: string): string {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>${title}</title><style>${MODERN_RED_STYLES}</style></head><body><article class="wechat-article"><header class="wechat-article-header"><h1 class="wechat-article-title">${title}</h1></header><section class="wechat-article-content">${body}</section></article></body></html>`
}


// packages/renderer/src/render.ts
import { renderModernRedPage } from './vendor/modern-red/template.js'

export function renderWechatHtml(markdown: string): string {
  const normalizedMarkdown = unwrapTopLevelMarkdownFence(markdown)
  const { body: renderableMarkdown, frontmatter } = splitFrontmatter(normalizedMarkdown)
  const title = extractTitle(frontmatter, renderableMarkdown)
  const renderer = new Renderer()
  renderer.html = ({ text }) => escapeHtml(text)
  renderer.link = (token) => hasUnsafeUrlScheme(token.href) ? renderer.parser.parseInline(token.tokens) : Renderer.prototype.link.call(renderer, token)
  renderer.image = (token) => hasUnsafeUrlScheme(token.href) ? escapeHtml(token.text) : Renderer.prototype.image.call(renderer, token)
  const body = marked.parse(renderableMarkdown, { async: false, renderer }) as string
  return renderModernRedPage(body, escapeHtml(title))
}
```

- [ ] **Step 4: Run renderer tests, build the renderer, and run the Python render-html test chain**

Run: `npm --prefix "/Users/bytedance/GolandProjects/x-weichat/packages/renderer" test && npm --prefix "/Users/bytedance/GolandProjects/x-weichat/packages/renderer" run build && PYTHONPATH="/Users/bytedance/GolandProjects/x-weichat" uv run --directory "/Users/bytedance/GolandProjects/x-weichat" --python 3.11 --extra dev pytest -v tests/test_pipeline.py -k render_html`

Expected: PASS for renderer tests, successful build, and passing render-html chain coverage on the Python side.

- [ ] **Step 5: Commit the internalized modern red renderer**

```bash
git add agent/stages/render_html.py packages/renderer/src/index.ts packages/renderer/src/render.ts packages/renderer/src/template.ts packages/renderer/src/vendor/modern-red/index.ts packages/renderer/src/vendor/modern-red/template.ts packages/renderer/src/vendor/modern-red/styles.ts packages/renderer/src/vendor/modern-red/content.ts packages/renderer/src/render.test.ts
git commit -m "feat: vendor modern red renderer into repo"
```

### Task 7: Run full regression coverage for retry + renderer together

**Files:**
- Test: `tests/test_job_store.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_api_jobs.py`
- Test: `apps/web/src/app.test.tsx`
- Test: `packages/renderer/src/render.test.ts`

- [ ] **Step 1: Add one end-to-end retry regression test at the pipeline layer**

```python
def test_retry_after_review_failure_regenerates_tail_and_finishes_successfully(tmp_path: Path, monkeypatch) -> None:
    store = JobStore(root_dir=tmp_path)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    runner = PipelineRunner(store=store, gateway=object(), settings=settings)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="01-source.md", content="# source\n")
    store.write_artifact(job_id=job.job_id, relative_path="02-translation.md", content="# translation\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")
    store.update_status(job_id=job.job_id, status="failed", current_stage="review")

    monkeypatch.setattr("agent.core.pipeline.run_review", lambda **kwargs: store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content="# reviewed\n") or "# reviewed")
    monkeypatch.setattr("agent.core.pipeline.run_wechat_rewrite", lambda **kwargs: store.write_artifact(job_id=job.job_id, relative_path="04-wechat.md", content="# wechat\n") or "# wechat")
    monkeypatch.setattr("agent.core.pipeline.run_render_html", lambda **kwargs: store.write_artifact(job_id=job.job_id, relative_path="05-wechat.html", content="<html>ok</html>") or "<html>ok</html>")

    result = runner.retry(job.job_id, stage="review", mode="failed-stage")

    assert result.status == "succeeded"
    assert store.read_artifact(job_id=job.job_id, relative_path="03-reviewed.md") == "# reviewed\n"
    assert store.read_artifact(job_id=job.job_id, relative_path="05-wechat.html") == "<html>ok</html>"
```

- [ ] **Step 2: Run the entire repository test workflow**

Run: `bash "/Users/bytedance/GolandProjects/x-weichat/scripts/test.sh"`

Expected: PASS for pytest, renderer tests/build, and web tests/build.

- [ ] **Step 3: Run the Makefile workflow as the final verification path**

Run: `make -C "/Users/bytedance/GolandProjects/x-weichat" test`

Expected: PASS, matching the repository’s canonical verification path.

- [ ] **Step 4: Review the generated HTML manually with one artifact sample**

Run: `node "/Users/bytedance/GolandProjects/x-weichat/packages/renderer/dist/index.js" "/Users/bytedance/GolandProjects/x-weichat/artifacts/be0f3024324442d688fcdcf9435a5644/04-wechat.md" "/Users/bytedance/GolandProjects/x-weichat/artifacts/be0f3024324442d688fcdcf9435a5644/05-wechat.html"`

Expected: command succeeds and `artifacts/be0f3024324442d688fcdcf9435a5644/05-wechat.html` is regenerated with the new `modern red` structure.

- [ ] **Step 5: Commit the final regression lock-in**

```bash
git add tests/test_pipeline.py tests/test_api_jobs.py tests/test_job_store.py apps/web/src/app.test.tsx packages/renderer/src/render.test.ts
git commit -m "test: lock retry and renderer regressions"
```

## Self-Review

### Spec coverage

- “失败阶段重试” 被 Task 2、Task 3、Task 4 覆盖。
- “从任意阶段重跑” 被 Task 2、Task 3、Task 5 覆盖。
- “目标阶段及后续产物覆盖” 被 Task 1、Task 2、Task 7 覆盖。
- “内嵌 modern red renderer，不依赖外部 skill 路径” 被 Task 6 覆盖。
- “保留现有安全过滤能力” 被 Task 6 的 renderer 测试与实现覆盖。
- “完整回归验证” 被 Task 7 覆盖。

### Placeholder scan

- 本计划未使用 `TBD`、`TODO`、`implement later`、`similar to Task N`。
- 每个代码步骤都提供了具体代码片段。
- 每个验证步骤都提供了确切命令与预期结果。

### Type consistency

- 后端统一使用 `StageName` / `RetryMode` 概念。
- 前端统一使用 `StageName` / `RetryMode` / `RetryJobRequest` / `RetryJobResponse`。
- API payload 中统一使用 `stage` 与 `mode` 字段名。

