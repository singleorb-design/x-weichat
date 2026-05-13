from __future__ import annotations

from fastapi import FastAPI

from agent.api.routes_discovery import XLoginManager
from agent.api.routes_discovery import router as discovery_router
from agent.api.routes_jobs import router as jobs_router
from agent.api.routes_preview import router as preview_router
from agent.api.routes_wechat import WeChatPublishManager
from agent.api.routes_wechat import router as wechat_router
from agent.config import Settings
from agent.core.pipeline import PipelineRunner
from agent.jobs.store import JobStore
from agent.models.gateway import ModelGateway


def create_app(
    *,
    settings: Settings | None = None,
    store: JobStore | None = None,
    gateway: ModelGateway | None = None,
    runner: PipelineRunner | None = None,
) -> FastAPI:
    if runner is not None:
        settings = settings or runner.settings
        if settings is None:
            settings = Settings()

        store = store or runner.store
        if store is None:
            store = JobStore(root_dir=settings.artifacts_dir)

        gateway = gateway or runner.gateway
        if gateway is None:
            gateway = ModelGateway(
                api_key=settings.api_key,
                base_url=settings.api_base,
            )

        runner.store = store
        runner.settings = settings
        runner.gateway = gateway
    else:
        settings = settings or Settings()
        store = store or JobStore(root_dir=settings.artifacts_dir)
        gateway = gateway or ModelGateway(
            api_key=settings.api_key,
            base_url=settings.api_base,
        )
        runner = PipelineRunner(store=store, gateway=gateway, settings=settings)

    app = FastAPI(title="x-to-wechat-agent")
    app.state.settings = settings
    app.state.store = store
    app.state.pipeline = runner
    app.state.x_login_manager = XLoginManager(settings=settings)
    app.state.wechat_publish_manager = WeChatPublishManager(settings=settings)
    app.include_router(jobs_router, prefix="/api")
    app.include_router(discovery_router, prefix="/api")
    app.include_router(preview_router, prefix="/api")
    app.include_router(wechat_router, prefix="/api")
    return app


app = create_app()
