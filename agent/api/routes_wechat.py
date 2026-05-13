from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field


router = APIRouter()

WECHAT_MP_HOME_URL = "https://mp.weixin.qq.com/"

CHROME_EXECUTABLE_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


WeChatPublishRunStatus = Literal["pending", "running", "succeeded", "failed"]
WeChatPublishRunPhase = Literal[
    "starting_browser",
    "awaiting_login",
    "opening_editor",
    "filling_content",
    "saving_draft",
    "completed",
]


class WeChatPublishAcceptedResponse(BaseModel):
    run_id: str
    status: WeChatPublishRunStatus


class WeChatPublishRunProgress(BaseModel):
    login_url: str | None = None
    storage_state_path: str | None = None
    current_url: str | None = None
    job_id: str | None = None
    title: str | None = None


class WeChatPublishRunStatusResponse(BaseModel):
    run_id: str
    status: WeChatPublishRunStatus
    current_phase: WeChatPublishRunPhase | None = None
    progress_message: str | None = None
    progress_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    completed: bool


class StartWeChatPublishRequest(BaseModel):
    job_id: str
    title: str | None = None
    html_artifact: str = "11-wechat.html"


class WeChatPublishManager:
    """Browser-based WeChat MP draft publishing.

    Notes:
    - We intentionally use a real, non-headless browser to let users complete login.
    - We persist Playwright `storage_state` so later publishes can skip login.
    """

    def __init__(self, *, settings: Any) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}

    def start_publish(
        self,
        *,
        store: Any,
        job_id: str,
        title: str | None,
        html_artifact: str,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        state_path = self._resolve_storage_state_path()

        normalized_title = _normalize_title(title)
        if not normalized_title:
            try:
                record = store.read_job(job_id)
                normalized_title = _normalize_title(getattr(record, "source_title", None))
            except Exception:
                normalized_title = None
        if not normalized_title:
            normalized_title = "未命名文章"

        # Validate job & artifact early for a clear error.
        try:
            store.read_job(job_id)
            store.read_artifact(job_id=job_id, relative_path=html_artifact)
        except FileNotFoundError as exc:
            raise
        except ValueError as exc:
            raise

        initial_run = {
            "run_id": run_id,
            "status": "pending",
            "current_phase": None,
            "progress_message": "正在准备打开公众号后台",
            "progress_json": {
                "login_url": WECHAT_MP_HOME_URL,
                "storage_state_path": str(state_path),
                "current_url": None,
                "job_id": job_id,
                "title": normalized_title,
            },
            "error_message": None,
            "completed": False,
        }
        with self._lock:
            self._runs[run_id] = initial_run

        worker = threading.Thread(
            target=self._run_publish,
            args=(run_id, job_id, normalized_title, html_artifact, state_path, store),
            name=f"wechat-publish-{run_id[:8]}",
            daemon=True,
        )
        worker.start()
        return {"run_id": run_id, "status": "pending"}

    def get_publish_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            return {
                **record,
                "progress_json": dict(record.get("progress_json") or {}),
            }

    def _resolve_storage_state_path(self) -> Path:
        configured = getattr(self._settings, "wechat_mp_storage_state_path", None)
        if configured:
            return Path(str(configured)).expanduser()
        artifacts_dir = Path(str(getattr(self._settings, "artifacts_dir", "artifacts")))
        return artifacts_dir / "_auth" / "wechat-mp-state.json"

    def _update_run(
        self,
        run_id: str,
        *,
        status: str,
        current_phase: str | None,
        progress_message: str | None,
        progress_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return
            merged_progress = {
                **(current.get("progress_json") or {}),
                **(progress_json or {}),
            }
            self._runs[run_id] = {
                **current,
                "status": status,
                "current_phase": current_phase,
                "progress_message": progress_message,
                "progress_json": merged_progress,
                "error_message": error_message,
                "completed": status in {"succeeded", "failed"},
            }

    def _run_publish(
        self,
        run_id: str,
        job_id: str,
        title: str,
        html_artifact: str,
        state_path: Path,
        store: Any,
    ) -> None:
        launch_kwargs = _build_wechat_launch_kwargs(settings=self._settings)
        browser_kind = "本机 Chrome" if launch_kwargs.get("executable_path") else "Playwright Chromium"
        self._update_run(
            run_id,
            status="running",
            current_phase="starting_browser",
            progress_message=f"正在打开公众号后台（{browser_kind}）",
            progress_json={
                "login_url": WECHAT_MP_HOME_URL,
                "storage_state_path": str(state_path),
                "current_url": WECHAT_MP_HOME_URL,
                "job_id": job_id,
                "title": title,
                "browser_kind": browser_kind,
            },
        )

        browser = None
        context = None
        try:
            from playwright.sync_api import sync_playwright

            html_raw = store.read_artifact(job_id=job_id, relative_path=html_artifact)
            html_fragment = _extract_body_inner_html(html_raw)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**launch_kwargs)
                context_kwargs: dict[str, Any] = {}
                if state_path.is_file():
                    context_kwargs["storage_state"] = str(state_path)
                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                page.goto(WECHAT_MP_HOME_URL, wait_until="domcontentloaded")

                deadline = time.monotonic() + 6 * 60
                while time.monotonic() < deadline:
                    current_url = page.url
                    if _is_wechat_mp_logged_in(page):
                        state_path.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(state_path))
                        break

                    self._update_run(
                        run_id,
                        status="running",
                        current_phase="awaiting_login",
                        progress_message="请在浏览器中登录公众号后台（扫码/确认后会自动继续）",
                        progress_json={
                            "current_url": current_url,
                            "login_url": WECHAT_MP_HOME_URL,
                            "storage_state_path": str(state_path),
                        },
                    )
                    time.sleep(1)

                if not _is_wechat_mp_logged_in(page):
                    raise RuntimeError("等待登录超时，请重试")

                self._update_run(
                    run_id,
                    status="running",
                    current_phase="opening_editor",
                    progress_message="登录成功，正在打开新建图文编辑器",
                    progress_json={
                        "current_url": page.url,
                    },
                )

                # Best-effort navigation: try direct editor URL first, fallback to UI clicks.
                try:
                    page.goto(
                        "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&lang=zh_CN",
                        wait_until="domcontentloaded",
                    )
                except Exception:
                    page.goto(WECHAT_MP_HOME_URL, wait_until="domcontentloaded")

                if not _wait_for_editor_ready(page, timeout_ms=30_000):
                    _navigate_to_editor_via_sidebar(page)
                    if not _wait_for_editor_ready(page, timeout_ms=60_000):
                        raise RuntimeError("未能打开图文编辑器页面；请确认账号有发文权限")

                self._update_run(
                    run_id,
                    status="running",
                    current_phase="filling_content",
                    progress_message="正在填充标题与正文",
                    progress_json={"current_url": page.url},
                )

                _fill_wechat_editor(page, title=title, html_fragment=html_fragment)

                self._update_run(
                    run_id,
                    status="running",
                    current_phase="saving_draft",
                    progress_message="正在保存草稿",
                    progress_json={"current_url": page.url},
                )

                _click_save_draft(page)
                # Give the UI a moment to finish network requests & show a toast.
                time.sleep(2)

                self._update_run(
                    run_id,
                    status="succeeded",
                    current_phase="completed",
                    progress_message="已保存为草稿（请在公众号后台『草稿箱』查看）",
                    progress_json={
                        "current_url": page.url,
                        "storage_state_path": str(state_path),
                    },
                )
        except Exception as exc:
            self._update_run(
                run_id,
                status="failed",
                current_phase="completed",
                progress_message="发布失败",
                progress_json={
                    "login_url": WECHAT_MP_HOME_URL,
                    "storage_state_path": str(state_path),
                    "job_id": job_id,
                    "title": title,
                },
                error_message=str(exc),
            )
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def _normalize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized[:64]


def _extract_body_inner_html(html: str) -> str:
    match = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", html, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return html.strip()


def _is_wechat_mp_logged_in(page: Any) -> bool:
    # Best-effort heuristics: the logged-in console has a sidebar with specific sections.
    candidates = [
        'a:has-text("内容与互动")',
        'a:has-text("内容管理")',
        'a:has-text("图文")',
        '#menuBar',
    ]
    for selector in candidates:
        try:
            if page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _wait_for_editor_ready(page: Any, *, timeout_ms: int) -> bool:
    # Title input is the most stable signal for the editor page.
    selectors = [
        'input[placeholder*="标题"]',
        'input#title',
        '#title',
    ]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _navigate_to_editor_via_sidebar(page: Any) -> None:
    # Sidebar labels change across WeChat UI iterations; try common variants.
    def click_first(selectors: list[str]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=1500):
                    locator.click()
                    return True
            except Exception:
                continue
        return False

    click_first(['a:has-text("内容与互动")', 'a:has-text("内容管理")'])
    time.sleep(0.5)
    click_first(['a:has-text("图文消息")', 'a:has-text("图文")', 'a:has-text("发表")'])
    time.sleep(0.5)
    click_first(['button:has-text("新建")', 'a:has-text("新建")', 'button:has-text("新建图文")'])


def _fill_wechat_editor(*, page: Any, title: str, html_fragment: str) -> None:
    # Title
    title_locators = [
        'input[placeholder*="标题"]',
        'input#title',
        '#title',
    ]
    for selector in title_locators:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1000):
                locator.fill(title)
                break
        except Exception:
            continue

    # Body: prefer editor iframe.
    try:
        iframe = page.locator('iframe[id*="ueditor"], iframe[name*="ueditor"], iframe[src*="ueditor"]').first
        frame = iframe.content_frame()
    except Exception:
        frame = None

    if frame is not None:
        try:
            frame.wait_for_selector("body", timeout=10_000)
            frame.evaluate(
                "(html) => { document.body.innerHTML = html; }",
                html_fragment,
            )
            return
        except Exception:
            pass

    # Fallback: a contenteditable root.
    candidates = [
        'div[contenteditable="true"]',
        '[contenteditable="true"]',
    ]
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1000):
                locator.evaluate("(el, html) => { el.innerHTML = html; }", html_fragment)
                return
        except Exception:
            continue

    raise RuntimeError("未找到正文编辑区域（iframe/contenteditable）")


def _click_save_draft(page: Any) -> None:
    selectors = [
        'button:has-text("保存为草稿")',
        'a:has-text("保存为草稿")',
        'button:has-text("保存")',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1500):
                locator.click()
                return
        except Exception:
            continue
    raise RuntimeError("未找到『保存为草稿』按钮")


def _find_local_chrome_executable(*, settings: Any) -> str | None:
    # Allow WeChat-specific override, then fall back to the shared env used by X login.
    for env_name in ("X2W_WECHAT_LOGIN_BROWSER_PATH", "X2W_X_LOGIN_BROWSER_PATH", "X_CHROME_PATH"):
        override = os.environ.get(env_name)
        if override:
            normalized = override.strip()
            if normalized and Path(normalized).exists():
                return normalized

    configured = getattr(settings, "wechat_mp_login_browser_path", None)
    if isinstance(configured, str) and configured.strip() and Path(configured).expanduser().exists():
        return str(Path(configured).expanduser())

    for candidate in CHROME_EXECUTABLE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for command in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
    ):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def _build_wechat_launch_kwargs(*, settings: Any) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {
        "headless": False,
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-popup-blocking",
        ],
    }
    executable_path = _find_local_chrome_executable(settings=settings)
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    return launch_kwargs


@router.post("/wechat/publish/start", status_code=status.HTTP_202_ACCEPTED)
def start_wechat_publish(payload: StartWeChatPublishRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    manager = request.app.state.wechat_publish_manager

    try:
        result = manager.start_publish(
            store=store,
            job_id=payload.job_id,
            title=payload.title,
            html_artifact=payload.html_artifact,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return result


@router.get("/wechat/publish/runs/{run_id}")
def get_wechat_publish_run(run_id: str, request: Request) -> dict[str, Any]:
    manager = request.app.state.wechat_publish_manager
    record = manager.get_publish_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    status_value = str(record.get("status") or "pending")
    return WeChatPublishRunStatusResponse(
        run_id=run_id,
        status=status_value,
        current_phase=record.get("current_phase"),
        progress_message=record.get("progress_message"),
        progress_json=record.get("progress_json") or {},
        error_message=record.get("error_message"),
        completed=status_value in {"succeeded", "failed"},
    ).model_dump(mode="json")
