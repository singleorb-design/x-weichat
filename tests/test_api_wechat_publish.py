import time
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


def test_wechat_publish_start_and_poll_succeeds_with_mocked_worker(app_bundle, monkeypatch) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)

    job = store.create_job(url="https://x.com/a/status/1")
    store.write_artifact(job_id=job.job_id, relative_path="11-wechat.html", content="<html><body><p>ok</p></body></html>")

    manager = app.state.wechat_publish_manager

    def fake_run_publish(run_id: str, job_id: str, title: str, html_artifact: str, state_path: Path, store_obj):
        manager._update_run(
            run_id,
            status="succeeded",
            current_phase="completed",
            progress_message="mock ok",
            progress_json={"job_id": job_id, "title": title, "storage_state_path": str(state_path)},
        )

    monkeypatch.setattr(manager, "_run_publish", fake_run_publish)

    response = client.post("/api/wechat/publish/start", json={"job_id": job.job_id, "html_artifact": "11-wechat.html"})
    assert response.status_code == 202
    payload = response.json()
    assert payload["run_id"]

    run_id = payload["run_id"]
    deadline = time.monotonic() + 2
    last = None
    while time.monotonic() < deadline:
        status_resp = client.get(f"/api/wechat/publish/runs/{run_id}")
        assert status_resp.status_code == 200
        last = status_resp.json()
        if last.get("completed"):
            break
        time.sleep(0.05)

    assert last is not None
    assert last["status"] == "succeeded"
    assert last["completed"] is True


def test_wechat_publish_rejects_missing_job(app_bundle) -> None:
    app, _store, _runner = app_bundle
    client = TestClient(app)
    response = client.post("/api/wechat/publish/start", json={"job_id": "missing", "html_artifact": "11-wechat.html"})
    assert response.status_code == 404


def test_wechat_publish_rejects_missing_html_artifact(app_bundle) -> None:
    app, store, _runner = app_bundle
    client = TestClient(app)
    job = store.create_job(url="https://x.com/a/status/1")
    response = client.post("/api/wechat/publish/start", json={"job_id": job.job_id, "html_artifact": "11-wechat.html"})
    assert response.status_code == 404

