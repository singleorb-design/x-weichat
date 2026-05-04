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


@pytest.mark.parametrize(
    ("filename", "content", "expected_content_type"),
    [
        ("01-source.md", "# source\n", "text/plain"),
        ("02-translation.md", "# translation\n", "text/plain"),
        ("03-reviewed.md", "# reviewed\n", "text/plain"),
        ("05-polished.md", "# polished\n", "text/plain"),
        ("06-rewritten.md", "# rewritten\n", "text/plain"),
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
