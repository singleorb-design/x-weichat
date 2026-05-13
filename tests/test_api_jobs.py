from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.config import Settings
from agent.core.pipeline import PipelineRunner
from agent.jobs.store import JobStore


@pytest.fixture
def app_bundle(tmp_path: Path):
    from agent.api.main import create_app

    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(
        store=store,
        gateway=object(),
        settings=Settings(api_key="test-key", artifacts_dir=str(tmp_path)),
    )
    app = create_app(store=store, runner=runner)
    return app, store, runner


def test_create_job_returns_job_id(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)

    response = client.post("/api/jobs", json={"url": "https://x.com/a/status/1"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"]
    assert payload["status"] == "pending"
    assert store.read_job(payload["job_id"]).job_id == payload["job_id"]


def test_create_job_accepts_x_article_url(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)

    response = client.post("/api/jobs", json={"url": "https://x.com/i/articles/987654321"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"]
    assert store.read_job(payload["job_id"]).url == "https://x.com/i/articles/987654321"


def test_create_job_accepts_x_singular_i_article_url(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)

    response = client.post("/api/jobs", json={"url": "https://x.com/i/article/987654321"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"]
    assert store.read_job(payload["job_id"]).url == "https://x.com/i/article/987654321"


def test_create_job_accepts_x_user_article_url(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        json={"url": "https://x.com/hooeem/article/2050332284675362853"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"]
    assert (
        store.read_job(payload["job_id"]).url
        == "https://x.com/hooeem/article/2050332284675362853"
    )


def test_create_job_rejects_non_x_url(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.post("/api/jobs", json={"url": "https://example.com/posts/1"})

    assert response.status_code == 422
    assert "Supported URLs are X tweet URLs" in str(response.json())


def test_create_job_rejects_unsupported_x_url_form(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.post("/api/jobs", json={"url": "https://x.com/home"})

    assert response.status_code == 422
    assert "Supported URLs are X tweet URLs" in str(response.json())


def test_create_jobs_batch_creates_and_schedules_runs(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    calls: list[tuple[str, str | None]] = []

    def fake_run(job_id: str, claim_token: str | None = None):
        calls.append((job_id, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "run", fake_run)

    response = client.post(
        "/api/jobs/batch",
        json={
            "urls_text": "\n".join(
                [
                    "https://x.com/alice/status/123?s=12",
                    "https://x.com/i/articles/987654321",
                ]
            ),
            "run": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"]["created"] == 2
    assert payload["stats"]["scheduled"] == 2
    assert payload["stats"]["invalid"] == 0
    assert len(payload["items"]) == 2
    assert all(item["ok"] for item in payload["items"])
    assert all(item["status"] == "accepted" for item in payload["items"])
    assert len(calls) == 2
    assert all(isinstance(call[1], str) and call[1] for call in calls)


def test_create_jobs_batch_reports_invalid_lines(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.post(
        "/api/jobs/batch",
        json={
            "urls_text": "\n".join(
                [
                    "https://example.com/posts/1",
                    "  https://x.com/home  ",
                    "https://x.com/alice/status/123?s=12",
                ]
            ),
            "run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"]["created"] == 1
    assert payload["stats"]["scheduled"] == 0
    assert payload["stats"]["invalid"] == 2
    assert len(payload["items"]) == 3
    assert [item["ok"] for item in payload["items"]] == [False, False, True]


def test_get_job_returns_status_for_ui(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="translate",
    )

    response = client.get(f"/api/jobs/{job.job_id}")

    assert response.status_code == 200
    assert response.json()["job_id"] == job.job_id
    assert response.json()["status"] == "running"
    assert response.json()["current_stage"] == "translate"


def test_list_jobs_returns_recent_jobs_for_ui(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    older = store.create_job(url="https://x.com/alice/status/1")
    newer = store.create_job(url="https://x.com/hooeem/article/2050332284675362853")
    store.update_status(
        job_id=newer.job_id,
        status="running",
        current_stage="x-fetch",
    )

    response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["job_id"] for item in payload] == [newer.job_id, older.job_id]
    assert payload[0]["status"] == "running"
    assert payload[0]["current_stage"] == "x-fetch"
    assert payload[1]["status"] == "pending"


def test_delete_job_removes_finished_job_from_api_list(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/alice/status/1")

    response = client.delete(f"/api/jobs/{job.job_id}")

    assert response.status_code == 204
    assert client.get("/api/jobs").json() == []
    assert client.get(f"/api/jobs/{job.job_id}").status_code == 404


def test_delete_job_rejects_running_job(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )

    response = client.delete(f"/api/jobs/{job.job_id}")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "job_locked_for_delete",
            "message": f"Job {job.job_id} is scheduled or running and cannot be deleted",
            "suggestion": "当前任务仍在运行或排队中，等待它结束后再删除。",
            "can_change_stage": False,
        }
    }


def test_stop_job_marks_canceled_and_allows_delete(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )

    response = client.post(f"/api/jobs/{job.job_id}/stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.job_id
    assert payload["status"] == "canceled"
    assert payload["finished_at"]

    delete_response = client.delete(f"/api/jobs/{job.job_id}")
    assert delete_response.status_code == 204
    assert client.get(f"/api/jobs/{job.job_id}").status_code == 404


def test_delete_job_moves_to_trash_and_restore_works(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/alice/status/1")

    delete_response = client.delete(f"/api/jobs/{job.job_id}")
    assert delete_response.status_code == 204

    trash_response = client.get("/api/jobs/trash")
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    assert any(item["job_id"] == job.job_id for item in trash_items)

    restore_response = client.post(f"/api/jobs/{job.job_id}/restore")
    assert restore_response.status_code == 200
    payload = restore_response.json()
    assert payload["job_id"] == job.job_id

    get_response = client.get(f"/api/jobs/{job.job_id}")
    assert get_response.status_code == 200


def test_set_published_marks_succeeded_job_as_published(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/alice/status/1")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="succeeded")

    response = client.post(f"/api/jobs/{job.job_id}/published", json={"published": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.job_id
    assert payload["status"] == "published"


@pytest.mark.parametrize(
    ("filename", "content", "expected_content_type"),
    [
        ("01-source.md", "# source\n", "text/plain"),
        ("02-translation.md", "# translation\n", "text/plain"),
        ("03-reviewed.md", "# reviewed\n", "text/plain"),
        ("10-final.md", "# final\n", "text/plain"),
        ("11-wechat.html", "<html>ok</html>", "text/html"),
    ],
)
def test_get_artifact_returns_markdown_or_html(
    app_bundle,
    filename: str,
    content: str,
    expected_content_type: str,
) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path=filename, content=content)

    response = client.get(f"/api/jobs/{job.job_id}/artifacts/{filename}")

    assert response.status_code == 200
    assert response.text == content
    assert expected_content_type in response.headers["content-type"]


def test_update_final_markdown_saves_editable_final_artifact(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content="# reviewed\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="render-html")
    store.update_status(job_id=job.job_id, status="succeeded", current_stage="render-html")

    response = client.put(
        f"/api/jobs/{job.job_id}/final-markdown",
        json={"content": "# edited final\n\nbody"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": job.job_id,
        "status": "saved",
        "relative_path": "10-final.md",
    }
    assert store.read_artifact(job_id=job.job_id, relative_path="10-final.md") == "# edited final\n\nbody"


def test_update_final_markdown_rejects_running_job(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="03-reviewed.md", content="# reviewed\n")
    store.update_status(job_id=job.job_id, status="running", current_stage="review")

    response = client.put(
        f"/api/jobs/{job.job_id}/final-markdown",
        json={"content": "# edited final\n\nbody"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "job_locked_for_final_markdown_edit",
            "message": f"Job {job.job_id} is running and cannot edit final markdown yet",
            "suggestion": "请等待当前任务完成或先停止任务，再编辑最终稿并重新生成 HTML。",
            "can_change_stage": False,
        }
    }


def test_get_artifact_returns_404_when_missing(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")

    response = client.get(f"/api/jobs/{job.job_id}/artifacts/01-source.md")

    assert response.status_code == 404


def test_get_artifact_serves_nested_asset_files_for_html_preview(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    asset_path = store.get_job_dir(job.job_id) / "01-source.assets" / "imgs" / "chart.jpg"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"image-bytes")

    response = client.get(f"/api/jobs/{job.job_id}/artifacts/01-source.assets/imgs/chart.jpg")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert "image/jpeg" in response.headers["content-type"]


def test_generate_stage_html_preview_writes_preview_asset_and_is_fetchable(app_bundle, monkeypatch) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="10-final.md", content="# 标题\n\n正文")

    monkeypatch.setattr(
        "agent.api.routes_preview.render_markdown_to_html",
        lambda *, markdown, input_name: f"<html><body><h1>{input_name}</h1><pre>{markdown}</pre></body></html>",
    )

    response = client.post(
        f"/api/jobs/{job.job_id}/html-preview",
        json={"stage": "final-output"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job.job_id
    assert payload["stage"] == "final-output"
    assert payload["artifact_path"] == "preview.assets/final-output.html"

    preview = client.get(f"/api/jobs/{job.job_id}/artifacts/{payload['artifact_path']}")
    assert preview.status_code == 200
    assert "text/html" in preview.headers["content-type"]
    assert "10-final.md" in preview.text


def test_get_prompt_returns_plain_text_prompt_content(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.get("/api/prompts/translate_zh.txt")

    assert response.status_code == 200
    assert "你是一个专业的技术翻译助手" in response.text
    assert "text/plain" in response.headers["content-type"]


def test_get_prompt_returns_404_for_unknown_prompt(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.get("/api/prompts/does-not-exist.txt")

    assert response.status_code == 404


def test_run_job_returns_accepted_status(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    calls: list[tuple[str, str | None]] = []

    def fake_run(job_id: str, claim_token: str | None = None):
        calls.append((job_id, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "run", fake_run)

    response = client.post(f"/api/jobs/{job.job_id}/run")

    assert response.status_code == 202
    assert response.json() == {"job_id": job.job_id, "status": "accepted"}
    assert calls == [(job.job_id, calls[0][1])]
    assert isinstance(calls[0][1], str)
    assert calls[0][1]


def test_run_job_rejects_duplicate_scheduling_for_same_pending_job(
    app_bundle,
    monkeypatch,
) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    calls: list[tuple[str, str | None]] = []

    def fake_run(job_id: str, claim_token: str | None = None):
        calls.append((job_id, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "run", fake_run)

    first_response = client.post(f"/api/jobs/{job.job_id}/run")
    second_response = client.post(f"/api/jobs/{job.job_id}/run")

    assert first_response.status_code == 202
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": {
            "code": "job_not_pending_for_run",
            "message": "Job must be pending before run",
            "suggestion": "只有 pending 任务可以开始运行；如果你想重新执行已完成或失败的任务，请使用重跑。",
            "can_change_stage": False,
        }
    }
    assert calls == [(job.job_id, calls[0][1])]
    assert isinstance(calls[0][1], str)
    assert calls[0][1]


def test_retry_job_returns_accepted_status(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )
    store.update_status(
        job_id=job.job_id,
        status="failed",
        current_stage="review",
    )
    calls: list[tuple[str, str, str, str | None]] = []

    def fake_retry(
        job_id: str,
        *,
        stage: str,
        mode: str,
        claim_token: str | None = None,
    ):
        calls.append((job_id, stage, mode, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "retry", fake_retry)

    response = client.post(
        f"/api/jobs/{job.job_id}/retry",
        json={"stage": "review", "mode": "failed-stage"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": job.job_id,
        "status": "accepted",
        "stage": "review",
        "mode": "failed-stage",
    }
    assert calls == [(job.job_id, "review", "failed-stage", calls[0][3])]
    assert isinstance(calls[0][3], str)
    assert calls[0][3]


def test_retry_job_rejects_running_job(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )

    response = client.post(
        f"/api/jobs/{job.job_id}/retry",
        json={"stage": "review", "mode": "failed-stage"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "job_retry_claim_conflict",
            "message": f"Job {job.job_id} is scheduled or running and cannot be claimed",
            "suggestion": (
                "这个任务已经有一次运行或重跑在进行中。先等当前执行结束，再决定是否继续重跑；"
                "如果刚才起始阶段选错了，任务恢复到 succeeded / failed 后，可以直接重新选择阶段再试。"
            ),
            "can_change_stage": True,
        }
    }


def test_retry_job_rejects_duplicate_scheduling(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    store.update_status(
        job_id=job.job_id,
        status="running",
        current_stage="review",
    )
    store.update_status(
        job_id=job.job_id,
        status="failed",
        current_stage="review",
    )
    calls: list[tuple[str, str, str, str | None]] = []

    def fake_retry(
        job_id: str,
        *,
        stage: str,
        mode: str,
        claim_token: str | None = None,
    ):
        calls.append((job_id, stage, mode, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "retry", fake_retry)

    first_response = client.post(
        f"/api/jobs/{job.job_id}/retry",
        json={"stage": "review", "mode": "failed-stage"},
    )
    second_response = client.post(
        f"/api/jobs/{job.job_id}/retry",
        json={"stage": "review", "mode": "failed-stage"},
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": {
            "code": "job_retry_claim_conflict",
            "message": f"Run claim already exists for job: {job.job_id}",
            "suggestion": (
                "这个任务已经有一次运行或重跑在进行中。先等当前执行结束，再决定是否继续重跑；"
                "如果刚才起始阶段选错了，任务恢复到 succeeded / failed 后，可以直接重新选择阶段再试。"
            ),
            "can_change_stage": True,
        }
    }
    assert calls == [(job.job_id, "review", "failed-stage", calls[0][3])]


def test_retry_job_returns_404_when_job_missing(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    response = client.post(
        "/api/jobs/does-not-exist/retry",
        json={"stage": "review", "mode": "failed-stage"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_retry_job_rejects_invalid_payload(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")

    response = client.post(
        f"/api/jobs/{job.job_id}/retry",
        json={"stage": "not-a-stage", "mode": "bad-mode"},
    )

    assert response.status_code == 422


def test_enqueue_discovery_auto_runs_created_jobs(app_bundle, monkeypatch) -> None:
    app, store, runner = app_bundle
    client = TestClient(app)
    canonical_url = "https://x.com/i/article/987654321"
    run_id = store.create_x_discovery_run(trigger="test", request_payload={"sources": []})
    store.save_x_discovery_items(
        run_id=run_id,
        items=[
            {
                "canonical_url": canonical_url,
                "original_url": canonical_url,
                "source_kind": "keyword",
                "source_value": "ai",
            }
        ],
    )
    calls: list[tuple[str, str | None]] = []

    def fake_run(job_id: str, claim_token: str | None = None):
        calls.append((job_id, claim_token))
        return store.read_job(job_id)

    monkeypatch.setattr(runner, "run", fake_run)

    response = client.post(
        "/api/x/discovery/enqueue",
        json={
            "run_id": run_id,
            "selected_urls": [canonical_url],
            "auto_run": True,
            "auto_run_limit": 0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["enqueued"]) == 1
    job_id = payload["enqueued"][0]["job_id"]
    assert payload["auto_run"] == {"requested": True, "started": 1, "skipped_due_to_limit": 0}
    assert calls == [(job_id, calls[0][1])]
    assert isinstance(calls[0][1], str)
    assert calls[0][1]


def test_preview_discovery_returns_pending_run_and_starts_background_execution(
    app_bundle,
    monkeypatch,
) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)
    calls: list[tuple[str, dict[str, object], str | None]] = []

    import agent.api.routes_discovery as routes_discovery

    def fake_run_discovery_preview(
        run_id: str,
        payload: dict[str, object],
        *,
        store: JobStore,
        settings: Settings,
        storage_state_path: str | None,
    ) -> None:
        calls.append((run_id, payload, storage_state_path))

    monkeypatch.setattr(routes_discovery, "run_discovery_preview", fake_run_discovery_preview)

    response = client.post(
        "/api/x/discovery/preview",
        json={
            "sources": [{"kind": "keyword", "value": "ai"}],
            "max_candidates": 5,
            "max_scrolls": 2,
            "search_mode": "top",
            "min_likes": 100,
            "required_keywords": ["AI"],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["run_id"]
    assert payload["status"] == "pending"
    assert calls == [
        (
            payload["run_id"],
            {
                "sources": [{"kind": "keyword", "value": "ai"}],
                "max_candidates": 5,
                "max_scrolls": 2,
                "search_mode": "top",
                "min_likes": 100,
                "required_keywords": ["AI"],
            },
            None,
        )
    ]


def test_preview_discovery_passes_resolved_storage_state_to_background_run(
    app_bundle,
    monkeypatch,
    tmp_path: Path,
) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)
    calls: list[tuple[str, dict[str, object], str | None]] = []

    import agent.api.routes_discovery as routes_discovery

    class FakeLoginManager:
        def get_active_storage_state_path(self) -> Path | None:
            return tmp_path / "runtime" / "x-state.json"

    def fake_run_discovery_preview(
        run_id: str,
        payload: dict[str, object],
        *,
        store: JobStore,
        settings: Settings,
        storage_state_path: str | None,
    ) -> None:
        calls.append((run_id, payload, storage_state_path))

    app.state.x_login_manager = FakeLoginManager()
    monkeypatch.setattr(routes_discovery, "run_discovery_preview", fake_run_discovery_preview)

    response = client.post(
        "/api/x/discovery/preview",
        json={
            "sources": [{"kind": "keyword", "value": "ai"}],
            "max_candidates": 5,
            "max_scrolls": 2,
            "search_mode": "top",
            "min_likes": 100,
            "required_keywords": ["AI"],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert calls == [
        (
            payload["run_id"],
            {
                "sources": [{"kind": "keyword", "value": "ai"}],
                "max_candidates": 5,
                "max_scrolls": 2,
                "search_mode": "top",
                "min_likes": 100,
                "required_keywords": ["AI"],
            },
            str(tmp_path / "runtime" / "x-state.json"),
        )
    ]


def test_preview_discovery_reuses_default_saved_storage_state_after_restart(
    app_bundle,
    monkeypatch,
    tmp_path: Path,
) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)
    calls: list[tuple[str, dict[str, object], str | None]] = []

    import agent.api.routes_discovery as routes_discovery

    saved_state_path = tmp_path / "_auth" / "x-state.json"
    saved_state_path.parent.mkdir(parents=True, exist_ok=True)
    saved_state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    class FakeLoginManager:
        def get_active_storage_state_path(self) -> Path | None:
            return None

    def fake_run_discovery_preview(
        run_id: str,
        payload: dict[str, object],
        *,
        store: JobStore,
        settings: Settings,
        storage_state_path: str | None,
    ) -> None:
        calls.append((run_id, payload, storage_state_path))

    app.state.x_login_manager = FakeLoginManager()
    monkeypatch.setattr(routes_discovery, "run_discovery_preview", fake_run_discovery_preview)

    response = client.post(
        "/api/x/discovery/preview",
        json={
            "sources": [{"kind": "keyword", "value": "ai"}],
            "max_candidates": 5,
            "max_scrolls": 2,
            "search_mode": "top",
            "min_likes": 100,
            "required_keywords": ["AI"],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert calls == [
        (
            payload["run_id"],
            {
                "sources": [{"kind": "keyword", "value": "ai"}],
                "max_candidates": 5,
                "max_scrolls": 2,
                "search_mode": "top",
                "min_likes": 100,
                "required_keywords": ["AI"],
            },
            str(saved_state_path),
        )
    ]


def test_build_query_uses_home_timeline_for_recommendation_sources() -> None:
    import agent.api.routes_discovery as routes_discovery

    payload = routes_discovery.DiscoveryPreviewRequest(
        sources=[{"kind": "recommendation", "value": "for_you"}],
        required_keywords=["AI"],
    )
    source = routes_discovery.DiscoverySource(kind="recommendation", value="for_you")

    query, required_keywords = routes_discovery._build_query(payload, source)

    assert query == "home:for_you"
    assert required_keywords == []


def test_build_query_uses_plain_keyword_sources() -> None:
    import agent.api.routes_discovery as routes_discovery

    payload = routes_discovery.DiscoveryPreviewRequest(
        sources=[{"kind": "keyword", "value": "agent"}],
        required_keywords=["AI"],
    )
    source = routes_discovery.DiscoverySource(kind="keyword", value="agent")

    query, required_keywords = routes_discovery._build_query(payload, source)

    assert query == "agent"
    assert required_keywords == []


def test_build_query_uses_plain_account_sources() -> None:
    import agent.api.routes_discovery as routes_discovery

    payload = routes_discovery.DiscoveryPreviewRequest(
        sources=[{"kind": "account", "value": "regent0x_"}],
        required_keywords=["AI", "agent"],
    )
    source = routes_discovery.DiscoverySource(kind="account", value="regent0x_")

    query, required_keywords = routes_discovery._build_query(payload, source)

    assert query == "from:regent0x_"
    assert required_keywords == ["AI", "agent"]


def test_run_discovery_preview_skips_recommendation_when_storage_state_missing(tmp_path: Path, monkeypatch) -> None:
    import agent.api.routes_discovery as routes_discovery
    from agent.jobs.store import JobStore
    from agent.config import Settings

    store = JobStore(root_dir=tmp_path)
    settings = Settings(artifacts_dir=str(tmp_path), api_key="test")
    run_id = store.create_x_discovery_run(trigger="test", request_payload={"sources": [{"kind": "recommendation", "value": "for_you"}]})

    def boom(*args, **kwargs):
        raise AssertionError("recommendation path should be skipped without storage_state")

    monkeypatch.setattr(routes_discovery, "discover_article_candidates_from_home_timeline", boom)
    monkeypatch.setattr(routes_discovery, "discover_article_candidates_from_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(routes_discovery.random, "shuffle", lambda items: None)

    routes_discovery.run_discovery_preview(
        run_id,
        {
            "sources": [{"kind": "recommendation", "value": "for_you"}],
            "max_candidates": 5,
            "max_scrolls": 2,
            "search_mode": "top",
            "min_likes": 100,
            "required_keywords": ["AI"],
        },
        store=store,
        settings=settings,
        storage_state_path=None,
    )

    run = store.get_x_discovery_run(run_id=run_id)
    assert run is not None
    debug_log = (tmp_path / "discovery" / run_id / "debug.log").read_text(encoding="utf-8")
    assert "skip recommendation: missing storage_state" in debug_log


def test_run_discovery_preview_filters_seen_and_continues_until_target(tmp_path: Path, monkeypatch) -> None:
    import agent.api.routes_discovery as routes_discovery
    from agent.jobs.store import JobStore
    from agent.config import Settings

    store = JobStore(root_dir=tmp_path)
    settings = Settings(artifacts_dir=str(tmp_path), api_key="test")
    seen_url = "https://x.com/i/article/100"
    enqueued_url = "https://x.com/i/article/101"
    store.upsert_x_discovery_seen(canonical_url=seen_url)
    store.record_x_discovery_enqueued(canonical_url=enqueued_url, job_id="job-existing")

    run_id = store.create_x_discovery_run(trigger="test", request_payload={"sources": [{"kind": "keyword", "value": "ai"}]})
    attempts = [
        (routes_discovery.DiscoverySource(kind="keyword", value="ai"), "top"),
        (routes_discovery.DiscoverySource(kind="keyword", value="agent"), "latest"),
    ]
    monkeypatch.setattr(routes_discovery, "_build_discovery_attempts", lambda _request: attempts)
    monkeypatch.setattr(routes_discovery.random, "shuffle", lambda items: None)

    def candidate(article_id: int, *, likes: int = 1000) -> dict[str, object]:
        url = f"https://x.com/i/article/{article_id}"
        return {
            "canonical_url": url,
            "original_url": url,
            "likes": likes,
            "tweet_text": "AI article",
            "score": float(likes),
            "reason": "search_like_threshold",
        }

    def fake_search(query: str, **kwargs):
        if query == "ai":
            return [
                {"canonical_url": seen_url, "original_url": seen_url, "likes": 999, "score": 999.0, "reason": "seen"},
                {"canonical_url": enqueued_url, "original_url": enqueued_url, "likes": 998, "score": 998.0, "reason": "enqueued"},
                candidate(201),
            ]
        return [candidate(article_id) for article_id in range(202, 206)]

    monkeypatch.setattr(routes_discovery, "discover_article_candidates_from_search", fake_search)

    routes_discovery.run_discovery_preview(
        run_id,
        {
            "sources": [{"kind": "keyword", "value": "ai"}],
            "max_candidates": 5,
            "max_scrolls": 2,
            "search_mode": "top",
            "min_likes": 100,
            "required_keywords": ["AI"],
        },
        store=store,
        settings=settings,
        storage_state_path=None,
    )

    run = store.get_x_discovery_run(run_id=run_id)
    assert run is not None
    assert run["status"] == "succeeded"
    assert run["result_json"]["returned"] == 5
    assert run["result_json"]["target"] == 5
    assert run["result_json"]["filtered_seen"] == 1
    assert run["result_json"]["filtered_enqueued"] == 1
    assert run["result_json"]["search_rounds"] == 2

    items = store.list_x_discovery_items(run_id=run_id)
    urls = [item["canonical_url"] for item in items]
    assert len(urls) == 5
    assert seen_url not in urls
    assert enqueued_url not in urls
    assert set(urls) == {f"https://x.com/i/article/{article_id}" for article_id in range(201, 206)}


def test_home_timeline_discovery_does_not_fallback_to_dom_when_graphql_succeeds(tmp_path: Path, monkeypatch) -> None:
    import packages.x_fetch.client as x_fetch_client

    def fake_graphql(**kwargs):
        return []

    def boom(**kwargs):
        raise AssertionError("DOM fallback should not run when HomeTimeline GraphQL succeeds")

    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_home_timeline_graphql", fake_graphql)
    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_feed_url", boom)

    results = x_fetch_client.discover_article_candidates_from_home_timeline(
        storage_state={"auth_token": "x", "ct0": "y"},
        max_scrolls=1,
        max_candidates=5,
        min_likes=100,
        required_keywords=None,
        progress_callback=None,
    )

    assert results == []


def test_discovery_run_status_items_and_artifacts_are_pollable(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    canonical_url = "https://x.com/i/article/987654321"
    run_id = store.create_x_discovery_run(
        trigger="test",
        request_payload={"sources": [{"kind": "keyword", "value": "ai"}]},
    )

    store.update_x_discovery_run(
        run_id=run_id,
        status="running",
        current_phase="searching",
        progress_message="正在搜索第 1 / 1 个来源",
        progress_payload={
            "source_total": 1,
            "source_index": 1,
            "current_source_kind": "keyword",
            "current_source_value": "ai",
            "current_query": "ai",
            "current_scroll": 2,
            "max_scrolls": 4,
            "raw_hits": 3,
            "after_likes_filter": 2,
            "after_keywords_filter": 2,
            "deduped_hits": 1,
            "suspected_reason": None,
        },
    )

    status_response = client.get(f"/api/x/discovery/runs/{run_id}")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "run_id": run_id,
        "status": "running",
        "current_phase": "searching",
        "progress_message": "正在搜索第 1 / 1 个来源",
        "progress_json": {
            "source_total": 1,
            "source_index": 1,
            "current_source_kind": "keyword",
            "current_source_value": "ai",
            "current_query": "ai",
            "current_scroll": 2,
            "max_scrolls": 4,
            "raw_hits": 3,
            "after_likes_filter": 2,
            "after_keywords_filter": 2,
            "deduped_hits": 1,
            "suspected_reason": None,
        },
        "stats": {},
        "error_message": None,
        "completed": False,
    }

    store.save_x_discovery_items(
        run_id=run_id,
        items=[
            {
                "canonical_url": canonical_url,
                "original_url": canonical_url,
                "source_kind": "keyword",
                "source_value": "ai",
                "likes": 1234,
                "score": 1234,
                "reason": "search_like_threshold",
            }
        ],
    )
    store.write_x_discovery_artifact(run_id=run_id, relative_path="request.json", content='{"sources":[{"kind":"keyword","value":"ai"}]}')
    store.write_x_discovery_artifact(
        run_id=run_id,
        relative_path="response-summary.json",
        content='{"sources":[{"query":"ai","raw_hits":3}]}',
    )
    store.write_x_discovery_artifact(
        run_id=run_id,
        relative_path="debug.log",
        content="[searching] source=ai scroll=2 raw_hits=3 deduped_hits=1\n",
    )
    store.finish_x_discovery_run(
        run_id=run_id,
        result_payload={"found": 3, "returned": 1, "already_seen": 0, "already_enqueued": 0, "enqueueable": 1},
        status="succeeded",
        current_phase="completed",
        progress_message="本次发现 1 条候选",
        progress_payload={"deduped_hits": 1, "suspected_reason": None},
    )

    items_response = client.get(f"/api/x/discovery/runs/{run_id}/items")
    artifacts_response = client.get(f"/api/x/discovery/runs/{run_id}/artifacts")
    debug_log_response = client.get(f"/api/x/discovery/runs/{run_id}/artifacts/debug.log")

    assert items_response.status_code == 200
    assert items_response.json()["run_id"] == run_id
    assert items_response.json()["items"] == [
        {
            "canonical_url": canonical_url,
            "original_url": canonical_url,
            "likes": 1234,
            "source_kind": "keyword",
            "source_value": "ai",
            "reason": "search_like_threshold",
            "score": 1234.0,
            "already_seen": False,
            "already_enqueued": False,
            "job_id": None,
        }
    ]
    assert artifacts_response.status_code == 200
    assert artifacts_response.json() == {
        "run_id": run_id,
        "files": ["debug.log", "request.json", "response-summary.json"],
    }
    assert debug_log_response.status_code == 200
    assert "source=ai" in debug_log_response.text


def test_failed_discovery_run_exposes_error_message_and_debug_artifacts(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    run_id = store.create_x_discovery_run(
        trigger="test",
        request_payload={"sources": [{"kind": "account", "value": "regent0x_"}]},
    )

    store.write_x_discovery_artifact(
        run_id=run_id,
        relative_path="debug.log",
        content="[searching] suspected_reason=login_required\n",
    )
    store.write_x_discovery_artifact(
        run_id=run_id,
        relative_path="response-summary.json",
        content='{"sources":[{"suspected_reason":"login_required"}]}',
    )
    store.finish_x_discovery_run(
        run_id=run_id,
        result_payload={"found": 0, "returned": 0, "already_seen": 0, "already_enqueued": 0, "enqueueable": 0},
        status="failed",
        current_phase="searching",
        progress_message="搜索失败",
        progress_payload={"suspected_reason": "login_required"},
        error_message="X 搜索页疑似要求重新登录",
    )

    status_response = client.get(f"/api/x/discovery/runs/{run_id}")
    debug_log_response = client.get(f"/api/x/discovery/runs/{run_id}/artifacts/debug.log")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "run_id": run_id,
        "status": "failed",
        "current_phase": "searching",
        "progress_message": "搜索失败",
        "progress_json": {"suspected_reason": "login_required"},
        "stats": {"found": 0, "returned": 0, "already_seen": 0, "already_enqueued": 0, "enqueueable": 0},
        "error_message": "X 搜索页疑似要求重新登录",
        "completed": True,
    }
    assert debug_log_response.status_code == 200
    assert "login_required" in debug_log_response.text


def test_x_login_start_and_status_are_pollable(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)

    class FakeLoginManager:
        def start_login(self) -> dict[str, object]:
            return {"run_id": "login-run-1", "status": "pending"}

        def get_login_run(self, run_id: str) -> dict[str, object] | None:
            if run_id != "login-run-1":
                return None
            return {
                "run_id": "login-run-1",
                "status": "running",
                "current_phase": "awaiting_login",
                "progress_message": "已打开 X 登录页，请在浏览器中完成登录",
                "progress_json": {
                    "login_url": "https://x.com/i/flow/login",
                    "storage_state_path": "/tmp/x-state.json",
                },
                "error_message": None,
                "completed": False,
            }

    app.state.x_login_manager = FakeLoginManager()

    response = client.post("/api/x/discovery/login/start")
    assert response.status_code == 202
    assert response.json() == {"run_id": "login-run-1", "status": "pending"}

    status_response = client.get("/api/x/discovery/login/runs/login-run-1")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "run_id": "login-run-1",
        "status": "running",
        "current_phase": "awaiting_login",
        "progress_message": "已打开 X 登录页，请在浏览器中完成登录",
        "progress_json": {
            "login_url": "https://x.com/i/flow/login",
            "storage_state_path": "/tmp/x-state.json",
        },
        "error_message": None,
        "completed": False,
    }


def test_x_login_prefers_local_chrome_binary_for_login_browser(monkeypatch) -> None:
    import agent.api.routes_discovery as routes_discovery

    monkeypatch.setattr(routes_discovery, "_find_local_chrome_executable", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    launch_kwargs = routes_discovery._build_login_launch_kwargs()

    assert launch_kwargs["headless"] is False
    assert launch_kwargs["executable_path"] == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert launch_kwargs["ignore_default_args"] == ["--enable-automation"]
    assert "--disable-blink-features=AutomationControlled" in launch_kwargs["args"]


def test_x_login_falls_back_to_playwright_chromium_when_local_chrome_missing(monkeypatch) -> None:
    import agent.api.routes_discovery as routes_discovery

    monkeypatch.setattr(routes_discovery, "_find_local_chrome_executable", lambda: None)

    launch_kwargs = routes_discovery._build_login_launch_kwargs()

    assert launch_kwargs["headless"] is False
    assert "executable_path" not in launch_kwargs
    assert launch_kwargs["ignore_default_args"] == ["--enable-automation"]
    assert "--disable-blink-features=AutomationControlled" in launch_kwargs["args"]


def test_x_login_activation_updates_settings_storage_state_path(tmp_path: Path) -> None:
    import agent.api.routes_discovery as routes_discovery

    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    manager = routes_discovery.XLoginManager(settings=settings)
    state_path = tmp_path / "_auth" / "x-state.json"

    manager._activate_storage_state_path(state_path)

    assert manager.get_active_storage_state_path() == state_path
    assert settings.x_storage_state_path == str(state_path)


def test_resolve_discovery_storage_state_prefers_login_manager_active_path(tmp_path: Path) -> None:
    import agent.api.routes_discovery as routes_discovery

    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))

    class FakeLoginManager:
        def get_active_storage_state_path(self) -> Path | None:
            return tmp_path / "runtime" / "x-state.json"

    resolved = routes_discovery._resolve_discovery_storage_state(
        settings=settings,
        login_manager=FakeLoginManager(),
    )

    assert resolved == str(tmp_path / "runtime" / "x-state.json")


def test_create_app_with_runner_fills_missing_gateway_and_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent.api.main as api_main

    store = JobStore(root_dir=tmp_path)
    runner = PipelineRunner(store=store)
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    gateway_args: dict[str, str] = {}

    class TrackingGateway:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            gateway_args["api_key"] = api_key
            gateway_args["base_url"] = base_url

    monkeypatch.setattr(api_main, "ModelGateway", TrackingGateway)

    app = api_main.create_app(
        runner=runner,
        settings=settings,
    )

    assert app.state.pipeline is runner
    assert app.state.store is store
    assert app.state.settings is settings
    assert runner.settings is settings
    assert isinstance(runner.gateway, TrackingGateway)
    assert gateway_args == {
        "api_key": settings.api_key,
        "base_url": settings.api_base,
    }


def test_create_app_with_complete_runner_skips_default_gateway_construction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent.api.main as api_main

    store = JobStore(root_dir=tmp_path)
    gateway = object()
    settings = Settings(api_key="test-key", artifacts_dir=str(tmp_path))
    runner = PipelineRunner(store=store, gateway=gateway, settings=settings)
    created_gateway = False

    class ExplodingGateway:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal created_gateway
            created_gateway = True
            raise AssertionError("default gateway path should not be used")

    monkeypatch.setattr(api_main, "ModelGateway", ExplodingGateway)

    app = api_main.create_app(runner=runner)

    assert app.state.pipeline is runner
    assert app.state.store is store
    assert app.state.settings is settings
    assert created_gateway is False
