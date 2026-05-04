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


@pytest.mark.parametrize(
    ("filename", "content", "expected_content_type"),
    [
        ("01-source.md", "# source\n", "text/plain"),
        ("02-translation.md", "# translation\n", "text/plain"),
        ("03-reviewed.md", "# reviewed\n", "text/plain"),
        ("04-wechat.md", "# wechat\n", "text/plain"),
        ("05-wechat.html", "<html>ok</html>", "text/html"),
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
    assert second_response.json() == {"detail": "Job must be pending before run"}
    assert calls == [(job.job_id, calls[0][1])]
    assert isinstance(calls[0][1], str)
    assert calls[0][1]


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
