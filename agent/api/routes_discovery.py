from __future__ import annotations

import json
import os
import random
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from packages.x_fetch.client import (
    discover_article_candidates_from_home_timeline,
    discover_article_candidates_from_search,
)


router = APIRouter()


SourceKind = Literal["account", "keyword", "recommendation"]
DiscoveryRunStatus = Literal["pending", "running", "succeeded", "failed", "canceled"]
DiscoveryRunPhase = Literal["preparing", "searching", "filtering", "completed"]
TERMINAL_DISCOVERY_STATUSES = {"succeeded", "failed", "canceled"}
DISCOVERY_TARGET_CANDIDATES = 5
DISCOVERY_INTERNAL_MAX_CANDIDATES = 50
DISCOVERY_DEEP_MAX_SCROLLS = 10
DISCOVERY_SEARCH_BUDGET_SECONDS = 300
DISCOVERY_EXPANSION_KEYWORDS = (
    "ai",
    "agent",
    "llm",
    "rag",
    "prompt",
    "openai",
    "claude",
    "gemini",
    "cursor",
    "codex",
)
XLoginRunStatus = Literal["pending", "running", "succeeded", "failed"]
XLoginRunPhase = Literal["starting_browser", "awaiting_login", "saving_state", "completed"]
TERMINAL_X_LOGIN_STATUSES = {"succeeded", "failed"}
CHROME_EXECUTABLE_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/usr/bin/microsoft-edge",
)


class DiscoverySource(BaseModel):
    kind: SourceKind
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source value must not be empty")
        return normalized


class DiscoveryPreviewRequest(BaseModel):
    sources: list[DiscoverySource]

    max_candidates: int = Field(default=DISCOVERY_TARGET_CANDIDATES, ge=1, le=50)
    max_scrolls: int = Field(default=4, ge=0, le=10)
    search_mode: Literal["top", "latest"] = "top"
    min_likes: int = Field(default=100, ge=0, le=1000000)
    required_keywords: list[str] = Field(default_factory=lambda: ["AI", "agent", "LLM", "RAG", "Prompt"])

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[DiscoverySource]) -> list[DiscoverySource]:
        if not value:
            raise ValueError("sources must not be empty")
        return value

    @field_validator("required_keywords")
    @classmethod
    def normalize_keywords(cls, value: list[str]) -> list[str]:
        return [kw.strip() for kw in value if kw and kw.strip()]


class DiscoveryPreviewAcceptedResponse(BaseModel):
    run_id: str
    status: DiscoveryRunStatus


class DiscoveryPreviewItem(BaseModel):
    canonical_url: str
    original_url: str
    likes: int
    source_kind: SourceKind
    source_value: str
    reason: str
    score: float
    already_seen: bool
    already_enqueued: bool
    job_id: str | None = None


class DiscoveryItemsResponse(BaseModel):
    run_id: str
    items: list[DiscoveryPreviewItem]


class DiscoveryRunStatusResponse(BaseModel):
    run_id: str
    status: DiscoveryRunStatus
    current_phase: DiscoveryRunPhase | Literal["searching"] | None = None
    progress_message: str | None = None
    progress_json: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = None
    completed: bool


class DiscoveryArtifactIndexResponse(BaseModel):
    run_id: str
    files: list[str]


class DiscoveryRunCanceled(RuntimeError):
    pass


class XLoginRunAcceptedResponse(BaseModel):
    run_id: str
    status: XLoginRunStatus


class XLoginRunStatusResponse(BaseModel):
    run_id: str
    status: XLoginRunStatus
    current_phase: XLoginRunPhase | None = None
    progress_message: str | None = None
    progress_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    completed: bool


class XLoginManager:
    def __init__(self, *, settings: Any) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._active_storage_state_path: Path | None = None

    def start_login(self) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        state_path = self._resolve_storage_state_path()
        initial_run = {
            "run_id": run_id,
            "status": "pending",
            "current_phase": None,
            "progress_message": "正在准备打开 X 登录页",
            "progress_json": {
                "login_url": "https://x.com/i/flow/login",
                "storage_state_path": str(state_path),
                "current_url": None,
            },
            "error_message": None,
            "completed": False,
        }
        with self._lock:
            self._runs[run_id] = initial_run

        worker = threading.Thread(
            target=self._run_login,
            args=(run_id, state_path),
            name=f"x-login-{run_id[:8]}",
            daemon=True,
        )
        worker.start()
        return {"run_id": run_id, "status": "pending"}

    def get_login_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            return {
                **record,
                "progress_json": dict(record.get("progress_json") or {}),
            }

    def get_active_storage_state_path(self) -> Path | None:
        with self._lock:
            return self._active_storage_state_path

    def _activate_storage_state_path(self, state_path: Path) -> None:
        resolved = state_path.expanduser().resolve()
        with self._lock:
            self._active_storage_state_path = resolved
        self._settings.x_storage_state_path = str(resolved)

    def _resolve_storage_state_path(self) -> Path:
        configured = getattr(self._settings, "x_storage_state_path", None)
        if configured:
            return Path(str(configured)).expanduser()
        artifacts_dir = Path(str(getattr(self._settings, "artifacts_dir", "artifacts")))
        return artifacts_dir / "_auth" / "x-state.json"

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
                "completed": status in TERMINAL_X_LOGIN_STATUSES,
            }

    def _run_login(self, run_id: str, state_path: Path) -> None:
        login_url = "https://x.com/i/flow/login"
        launch_kwargs = _build_login_launch_kwargs()
        browser_kind = "本机 Chrome" if launch_kwargs.get("executable_path") else "Playwright Chromium"
        self._update_run(
            run_id,
            status="running",
            current_phase="starting_browser",
            progress_message=f"正在打开 X 登录页（{browser_kind}）",
            progress_json={
                "login_url": login_url,
                "storage_state_path": str(state_path),
                "current_url": login_url,
                "browser_kind": browser_kind,
            },
        )

        browser = None
        context = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**launch_kwargs)
                context = browser.new_context()
                page = context.new_page()
                page.goto(login_url, wait_until="domcontentloaded")
                self._update_run(
                    run_id,
                    status="running",
                    current_phase="awaiting_login",
                    progress_message="已打开 X 登录页，请在浏览器中完成登录",
                    progress_json={
                        "login_url": login_url,
                        "storage_state_path": str(state_path),
                        "current_url": page.url,
                        "browser_kind": browser_kind,
                    },
                )

                deadline = time.monotonic() + 5 * 60
                while time.monotonic() < deadline:
                    cookies = context.cookies("https://x.com")
                    cookie_names = {str(item.get("name") or "") for item in cookies}
                    current_url = page.url
                    if {"auth_token", "ct0"}.issubset(cookie_names):
                        self._update_run(
                            run_id,
                            status="running",
                            current_phase="saving_state",
                            progress_message="检测到登录成功，正在保存登录态",
                            progress_json={
                                "login_url": login_url,
                                "storage_state_path": str(state_path),
                                "current_url": current_url,
                                "browser_kind": browser_kind,
                            },
                        )
                        state_path.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(state_path))
                        self._activate_storage_state_path(state_path)
                        self._update_run(
                            run_id,
                            status="succeeded",
                            current_phase="completed",
                            progress_message="登录态已保存，可重新预览候选",
                            progress_json={
                                "login_url": login_url,
                                "storage_state_path": str(state_path),
                                "current_url": current_url,
                                "browser_kind": browser_kind,
                            },
                        )
                        return

                    self._update_run(
                        run_id,
                        status="running",
                        current_phase="awaiting_login",
                        progress_message="已打开 X 登录页，请在浏览器中完成登录",
                        progress_json={
                            "login_url": login_url,
                            "storage_state_path": str(state_path),
                            "current_url": current_url,
                            "browser_kind": browser_kind,
                        },
                    )
                    time.sleep(1)

                self._update_run(
                    run_id,
                    status="failed",
                    current_phase="awaiting_login",
                    progress_message="等待登录超时",
                    progress_json={
                        "login_url": login_url,
                        "storage_state_path": str(state_path),
                        "browser_kind": browser_kind,
                    },
                    error_message="等待用户在页面内完成 X 登录超时，请重试。",
                )
        except Exception as exc:
            self._update_run(
                run_id,
                status="failed",
                current_phase="starting_browser",
                progress_message="打开 X 登录页失败",
                progress_json={
                    "login_url": login_url,
                    "storage_state_path": str(state_path),
                    "browser_kind": browser_kind,
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


def _find_local_chrome_executable() -> str | None:
    for env_name in ("X2W_X_LOGIN_BROWSER_PATH", "X_CHROME_PATH"):
        override = os.environ.get(env_name)
        if override:
            normalized = override.strip()
            if normalized and Path(normalized).exists():
                return normalized

    for candidate in CHROME_EXECUTABLE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for command in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def _build_login_launch_kwargs() -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {
        "headless": False,
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-popup-blocking",
        ],
    }
    executable_path = _find_local_chrome_executable()
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    return launch_kwargs


def _resolve_discovery_storage_state(*, settings: Any, login_manager: Any | None) -> str | None:
    if login_manager is not None:
        try:
            active_path = login_manager.get_active_storage_state_path()
        except Exception:
            active_path = None
        if active_path is not None:
            return str(active_path)
    configured = getattr(settings, "x_storage_state_path", None)
    if configured:
        return str(configured)

    artifacts_dir = Path(str(getattr(settings, "artifacts_dir", "artifacts")))
    default_state_path = artifacts_dir / "_auth" / "x-state.json"
    if default_state_path.is_file():
        return str(default_state_path)

    return None


def _build_query(payload: DiscoveryPreviewRequest, source: DiscoverySource) -> tuple[str, list[str]]:
    if source.kind == "recommendation":
        return "home:for_you", []
    if source.kind == "account":
        return f"from:{source.value}", payload.required_keywords
    # keyword
    return source.value, []


def _build_discovery_attempts(request_model: DiscoveryPreviewRequest) -> list[tuple[DiscoverySource, str]]:
    sources: list[DiscoverySource] = list(request_model.sources)
    seen_sources = {(source.kind, source.value.lower()) for source in sources}

    for keyword in DISCOVERY_EXPANSION_KEYWORDS:
        key = ("keyword", keyword.lower())
        if key not in seen_sources:
            sources.append(DiscoverySource(kind="keyword", value=keyword))
            seen_sources.add(key)

    if ("recommendation", "for_you") not in seen_sources:
        sources.append(DiscoverySource(kind="recommendation", value="for_you"))

    attempts: list[tuple[DiscoverySource, str]] = []
    for source in sources:
        if source.kind == "recommendation":
            attempts.append((source, "home"))
            continue

        preferred_mode = request_model.search_mode
        alternate_mode = "latest" if preferred_mode == "top" else "top"
        attempts.append((source, preferred_mode))
        attempts.append((source, alternate_mode))

    random.shuffle(attempts)
    return attempts


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _debug_line(store: Any, lines: list[str], message: str) -> None:
    lines.append(f"{store._now().isoformat()} {message}")


def _progress_message(progress: dict[str, Any]) -> str:
    source_index = progress.get("source_index") or 0
    source_total = progress.get("source_total") or 0
    current_scroll = progress.get("current_scroll")
    max_scrolls = progress.get("max_scrolls")
    if current_scroll is None or max_scrolls is None:
        return f"正在搜索第 {source_index} / {source_total} 个来源"
    return f"正在搜索第 {source_index} / {source_total} 个来源（滚动 {current_scroll} / {max_scrolls}）"


def _discovery_run_status_response(run_id: str, run: dict[str, Any]) -> DiscoveryRunStatusResponse:
    status = str(run.get("status") or "pending")
    return DiscoveryRunStatusResponse(
        run_id=run_id,
        status=status,
        current_phase=run.get("current_phase"),
        progress_message=run.get("progress_message"),
        progress_json=run.get("progress_json") or {},
        stats=run.get("result_json") or {},
        error_message=run.get("error_message"),
        completed=status in TERMINAL_DISCOVERY_STATUSES,
    )


def _raise_if_discovery_canceled(*, store: Any, run_id: str) -> None:
    run = store.get_x_discovery_run(run_id=run_id)
    if run is not None and str(run.get("status") or "") == "canceled":
        raise DiscoveryRunCanceled(run_id)


def run_discovery_preview(
    run_id: str,
    payload: dict[str, Any],
    *,
    store: Any,
    settings: Any,
    storage_state_path: str | None = None,
) -> None:
    request_model = DiscoveryPreviewRequest.model_validate(payload)
    target_candidates = int(request_model.max_candidates)
    internal_max_candidates = min(DISCOVERY_INTERNAL_MAX_CANDIDATES, max(target_candidates * 10, target_candidates))
    effective_max_scrolls = max(int(request_model.max_scrolls), DISCOVERY_DEEP_MAX_SCROLLS)
    attempts = _build_discovery_attempts(request_model)
    deadline = time.monotonic() + DISCOVERY_SEARCH_BUDGET_SECONDS
    progress: dict[str, Any] = {
        "source_total": len(attempts),
        "source_index": 0,
        "current_source_kind": None,
        "current_source_value": None,
        "current_query": None,
        "current_scroll": 0,
        "max_scrolls": effective_max_scrolls,
        "raw_hits": 0,
        "after_likes_filter": 0,
        "after_keywords_filter": 0,
        "after_article_entity": 0,
        "after_article_url_extract": 0,
        "after_language_length_filter": 0,
        "duplicate_filtered": 0,
        "deduped_hits": 0,
        "suspected_reason": None,
        "sample": [],
    }
    request_sources: list[dict[str, Any]] = []
    debug_lines: list[str] = []
    response_summary_sources: list[dict[str, Any]] = []
    deduped: dict[str, dict[str, Any]] = {}
    total_found = 0
    already_seen_count = 0
    already_enqueued_count = 0
    filtered_seen_count = 0
    filtered_enqueued_count = 0
    search_rounds = 0
    budget_exhausted = False
    current_phase: str | None = "preparing"

    for source, attempt_mode in attempts:
        query, required_keywords = _build_query(request_model, source)
        request_sources.append(
            {
                "kind": source.kind,
                "value": source.value,
                "query": query,
                "search_mode": attempt_mode,
                "required_keywords": required_keywords,
            }
        )

    request_summary = {
        "sources": request_sources,
        "search_mode": request_model.search_mode,
        "min_likes": request_model.min_likes,
        "max_scrolls": effective_max_scrolls,
        "max_candidates": target_candidates,
        "internal_max_candidates": internal_max_candidates,
        "budget_seconds": DISCOVERY_SEARCH_BUDGET_SECONDS,
        "required_keywords": request_model.required_keywords,
    }

    store.write_x_discovery_artifact(
        run_id=run_id,
        relative_path="request.json",
        content=_json_text(request_summary),
    )
    store.update_x_discovery_run(
        run_id=run_id,
        status="running",
        current_phase="preparing",
        progress_message="正在准备 discovery 请求",
        progress_payload=progress,
    )
    _debug_line(
        store,
        debug_lines,
        (
            f"[preparing] run_id={run_id} source_total={len(attempts)} "
            f"target={target_candidates} internal_max={internal_max_candidates} max_scrolls={effective_max_scrolls}"
        ),
    )

    try:
        for source_index, (source, attempt_mode) in enumerate(attempts, start=1):
            _raise_if_discovery_canceled(store=store, run_id=run_id)
            if len(deduped) >= target_candidates:
                break
            if time.monotonic() >= deadline:
                budget_exhausted = True
                _debug_line(store, debug_lines, "[searching] budget exhausted before next source")
                break

            search_rounds += 1
            current_phase = "searching"
            query, required_keywords = _build_query(request_model, source)
            progress.update(
                {
                    "source_index": source_index,
                    "current_source_kind": source.kind,
                    "current_source_value": source.value,
                    "current_query": query,
                    "current_scroll": 0,
                    "target_candidates": target_candidates,
                    "raw_hits": 0,
                    "after_likes_filter": 0,
                    "after_keywords_filter": 0,
                    "after_article_entity": 0,
                    "after_article_url_extract": 0,
                    "after_language_length_filter": 0,
                    "duplicate_filtered": 0,
                    "deduped_hits": len(deduped),
                    "suspected_reason": None,
                    "sample": [],
                }
            )
            store.update_x_discovery_run(
                run_id=run_id,
                status="running",
                current_phase="searching",
                progress_message=_progress_message(progress),
                progress_payload=progress,
            )
            _debug_line(
                store,
                debug_lines,
                f"[searching] source={source.kind}:{source.value} mode={attempt_mode} query={query}",
            )

            source_summary: dict[str, Any] = {
                "source_kind": source.kind,
                "source_value": source.value,
                "search_mode": attempt_mode,
                "query": query,
                "page_url": None,
                "page_title": None,
                "scrolls": 0,
                "scroll_scan_counts": [],
                "raw_hits": 0,
                "after_likes_filter": 0,
                "after_keywords_filter": 0,
                "after_article_entity": 0,
                "after_article_url_extract": 0,
                "after_language_length_filter": 0,
                "duplicate_filtered": 0,
                "deduped_hits": 0,
                "accepted_hits": 0,
                "suspected_reason": None,
                "sample": [],
            }

            def progress_callback(event: dict[str, Any]) -> None:
                event_type = str(event.get("type") or "")
                if event_type == "page":
                    _raise_if_discovery_canceled(store=store, run_id=run_id)
                    source_summary["page_url"] = event.get("page_url")
                    source_summary["page_title"] = event.get("page_title")
                    _debug_line(
                        store,
                        debug_lines,
                        f"[searching] opened page url={event.get('page_url')} title={event.get('page_title')}",
                    )
                    return

                if event_type == "graphql_request":
                    _raise_if_discovery_canceled(store=store, run_id=run_id)
                    operation = event.get("operation")
                    query_id = event.get("query_id")
                    url = event.get("url")
                    note = event.get("note")
                    _debug_line(
                        store,
                        debug_lines,
                        f"[searching] graphql_request op={operation} query_id={query_id} url={url} note={note}",
                    )
                    return

                if event_type == "graphql_response":
                    _raise_if_discovery_canceled(store=store, run_id=run_id)
                    operation = event.get("operation")
                    ok = event.get("ok")
                    suspected_reason = event.get("suspected_reason")
                    detail = event.get("detail")
                    _debug_line(
                        store,
                        debug_lines,
                        f"[searching] graphql_response op={operation} ok={ok} suspected_reason={suspected_reason}",
                    )
                    if detail:
                        _debug_line(store, debug_lines, f"[searching] graphql_detail={detail}")
                    return

                if event_type == "scroll":
                    _raise_if_discovery_canceled(store=store, run_id=run_id)
                    source_summary["scrolls"] = int(event.get("scroll") or 0)
                    source_summary["raw_hits"] = int(event.get("raw_hits") or 0)
                    source_summary["after_likes_filter"] = int(event.get("after_likes_filter") or 0)
                    source_summary["after_keywords_filter"] = int(event.get("after_keywords_filter") or 0)
                    source_summary["after_article_entity"] = int(event.get("after_article_entity") or 0)
                    source_summary["after_article_url_extract"] = int(event.get("after_article_url_extract") or 0)
                    source_summary["after_language_length_filter"] = int(event.get("after_language_length_filter") or 0)
                    source_summary["duplicate_filtered"] = int(event.get("duplicate_filtered") or 0)
                    source_summary["deduped_hits"] = int(event.get("deduped_hits") or 0)
                    source_summary["sample"] = event.get("sample") or []
                    source_summary["scroll_scan_counts"].append(
                        {
                            "scroll": int(event.get("scroll") or 0),
                            "tweet_count": int(event.get("tweet_count") or 0),
                            "raw_hits": int(event.get("raw_hits") or 0),
                            "after_likes_filter": int(event.get("after_likes_filter") or 0),
                            "after_keywords_filter": int(event.get("after_keywords_filter") or 0),
                            "after_article_entity": int(event.get("after_article_entity") or 0),
                            "after_article_url_extract": int(event.get("after_article_url_extract") or 0),
                            "after_language_length_filter": int(event.get("after_language_length_filter") or 0),
                            "duplicate_filtered": int(event.get("duplicate_filtered") or 0),
                            "deduped_hits": int(event.get("deduped_hits") or 0),
                        }
                    )
                    progress.update(
                        {
                            "current_scroll": int(event.get("scroll") or 0),
                            "raw_hits": int(event.get("raw_hits") or 0),
                            "after_likes_filter": int(event.get("after_likes_filter") or 0),
                            "after_keywords_filter": int(event.get("after_keywords_filter") or 0),
                            "after_article_entity": int(event.get("after_article_entity") or 0),
                            "after_article_url_extract": int(event.get("after_article_url_extract") or 0),
                            "after_language_length_filter": int(event.get("after_language_length_filter") or 0),
                            "duplicate_filtered": int(event.get("duplicate_filtered") or 0),
                            "deduped_hits": len(deduped) + int(event.get("deduped_hits") or 0),
                            "sample": event.get("sample") or [],
                        }
                    )
                    store.update_x_discovery_run(
                        run_id=run_id,
                        status="running",
                        current_phase="searching",
                        progress_message=_progress_message(progress),
                        progress_payload=progress,
                    )
                    _debug_line(
                        store,
                        debug_lines,
                        (
                            "[searching] "
                            f"source={source.value} scroll={event.get('scroll')} tweet_count={event.get('tweet_count')} "
                            f"raw_hits={event.get('raw_hits')} after_likes_filter={event.get('after_likes_filter')} "
                            f"after_keywords_filter={event.get('after_keywords_filter')} "
                            f"after_article_entity={event.get('after_article_entity')} after_article_url_extract={event.get('after_article_url_extract')} "
                            f"after_language_length_filter={event.get('after_language_length_filter')} duplicate_filtered={event.get('duplicate_filtered')} "
                            f"deduped_hits={event.get('deduped_hits')}"
                        ),
                    )

                    sample_items = event.get("sample")
                    if sample_items:
                        for item in list(sample_items)[:5]:
                            _debug_line(store, debug_lines, f"[searching] sample={item}")
                    return

                if event_type == "hint":
                    _raise_if_discovery_canceled(store=store, run_id=run_id)
                    suspected_reason = event.get("suspected_reason")
                    source_summary["suspected_reason"] = suspected_reason
                    progress["suspected_reason"] = suspected_reason
                    detail = event.get("detail")
                    if detail:
                        source_summary["suspected_detail"] = detail
                    store.update_x_discovery_run(
                        run_id=run_id,
                        status="running",
                        current_phase="searching",
                        progress_message=_progress_message(progress),
                        progress_payload=progress,
                    )
                    _debug_line(store, debug_lines, f"[searching] suspected_reason={suspected_reason}")
                    if detail:
                        _debug_line(store, debug_lines, f"[searching] suspected_detail={detail}")

            effective_storage_state = storage_state_path or getattr(settings, "x_storage_state_path", None)

            # recommendation（For You）必须有登录态，否则首页 feed 基本不可扫描。
            if source.kind == "recommendation" and not effective_storage_state:
                source_summary["suspected_reason"] = "login_required"
                progress["suspected_reason"] = "login_required"
                store.update_x_discovery_run(
                    run_id=run_id,
                    status="running",
                    current_phase="searching",
                    progress_message="推荐流需要登录态，已跳过（请先点击“打开登录页”完成登录后重试）",
                    progress_payload=progress,
                )
                _debug_line(store, debug_lines, "[searching] skip recommendation: missing storage_state")
                response_summary_sources.append(source_summary)
                continue

            if source.kind == "recommendation":
                candidates = discover_article_candidates_from_home_timeline(
                    storage_state=effective_storage_state,
                    max_scrolls=effective_max_scrolls,
                    max_candidates=internal_max_candidates,
                    min_likes=request_model.min_likes,
                    required_keywords=required_keywords,
                    progress_callback=progress_callback,
                )
            else:
                candidates = discover_article_candidates_from_search(
                    query,
                    storage_state=effective_storage_state,
                    search_mode=attempt_mode,
                    max_scrolls=effective_max_scrolls,
                    max_candidates=internal_max_candidates,
                    min_likes=request_model.min_likes,
                    required_keywords=required_keywords,
                    progress_callback=progress_callback,
                )
            _raise_if_discovery_canceled(store=store, run_id=run_id)
            total_found += len(candidates)
            random.shuffle(candidates)

            for candidate in candidates:
                if len(deduped) >= target_candidates:
                    break
                canonical_url = str(candidate.get("canonical_url") or "").strip()
                if not canonical_url:
                    continue
                if canonical_url in deduped:
                    continue
                already_seen = store.get_x_discovery_seen(canonical_url=canonical_url) is not None
                if already_seen:
                    already_seen_count += 1
                    filtered_seen_count += 1
                    continue
                job_id = store.get_x_discovery_enqueued_job(canonical_url=canonical_url)
                if job_id is not None:
                    already_enqueued_count += 1
                    filtered_enqueued_count += 1
                    continue

                likes = int(candidate.get("likes") or 0)
                deduped[canonical_url] = {
                    **candidate,
                    "canonical_url": canonical_url,
                    "original_url": str(candidate.get("original_url") or canonical_url),
                    "likes": likes,
                    "source_kind": source.kind,
                    "source_value": source.value,
                    "reason": str(candidate.get("reason") or ""),
                    "score": float(candidate.get("score") or likes),
                }

            source_summary["deduped_hits"] = len(candidates)
            source_summary["accepted_hits"] = len(deduped)
            response_summary_sources.append(source_summary)

        _raise_if_discovery_canceled(store=store, run_id=run_id)
        if len(deduped) < target_candidates and time.monotonic() >= deadline:
            budget_exhausted = True
        current_phase = "filtering"
        progress["deduped_hits"] = len(deduped)
        store.update_x_discovery_run(
            run_id=run_id,
            status="running",
            current_phase="filtering",
            progress_message=f"正在整理 {len(deduped)} 条候选",
            progress_payload=progress,
        )
        _debug_line(store, debug_lines, f"[filtering] deduped_hits={len(deduped)}")

        sorted_items = list(deduped.values())[:target_candidates]

        persisted_items: list[dict[str, Any]] = []
        response_items: list[DiscoveryPreviewItem] = []
        for item in sorted_items:
            canonical_url = str(item["canonical_url"])
            already_seen = store.get_x_discovery_seen(canonical_url=canonical_url) is not None
            if already_seen:
                already_seen_count += 1
                filtered_seen_count += 1
                continue

            job_id = store.get_x_discovery_enqueued_job(canonical_url=canonical_url)
            already_enqueued = job_id is not None
            if already_enqueued:
                already_enqueued_count += 1
                filtered_enqueued_count += 1
                continue

            store.upsert_x_discovery_seen(canonical_url=canonical_url)
            persisted_items.append(
                {
                    **item,
                    "discovered_at": store._now().isoformat(),
                    "already_seen": already_seen,
                    "already_enqueued": already_enqueued,
                    "job_id": job_id,
                }
            )
            response_items.append(
                DiscoveryPreviewItem(
                    canonical_url=canonical_url,
                    original_url=str(item.get("original_url") or canonical_url),
                    likes=int(item.get("likes") or 0),
                    source_kind=item.get("source_kind"),
                    source_value=str(item.get("source_value") or ""),
                    reason=str(item.get("reason") or ""),
                    score=float(item.get("score") or 0),
                    already_seen=already_seen,
                    already_enqueued=already_enqueued,
                    job_id=job_id,
                )
            )

        store.save_x_discovery_items(run_id=run_id, items=persisted_items)
        enqueueable_count = len(response_items)
        stats = {
            "found": total_found,
            "returned": len(response_items),
            "target": target_candidates,
            "already_seen": already_seen_count,
            "already_enqueued": already_enqueued_count,
            "filtered_seen": filtered_seen_count,
            "filtered_enqueued": filtered_enqueued_count,
            "search_rounds": search_rounds,
            "budget_exhausted": 1 if budget_exhausted else 0,
            # 便于 UI 直接展示“这次还有多少是可入队的新条目”。
            "enqueueable": enqueueable_count,
        }
        response_summary = {
            "sources": response_summary_sources,
            "stats": stats,
        }
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="response-summary.json",
            content=_json_text(response_summary),
        )
        _debug_line(store, debug_lines, f"[completed] found={total_found} returned={len(response_items)}")
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="debug.log",
            content="\n".join(debug_lines) + "\n",
        )
        _raise_if_discovery_canceled(store=store, run_id=run_id)
        progress["deduped_hits"] = len(response_items)
        store.finish_x_discovery_run(
            run_id=run_id,
            result_payload=stats,
            status="succeeded",
            current_phase="completed",
            progress_message=f"本次找到 {len(response_items)} / {target_candidates} 篇合格新文章",
            progress_payload=progress,
        )
    except DiscoveryRunCanceled:
        response_summary = {
            "sources": response_summary_sources,
            "stats": {
                "found": total_found,
                "returned": 0,
                "target": target_candidates,
                "already_seen": already_seen_count,
                "already_enqueued": already_enqueued_count,
                "filtered_seen": filtered_seen_count,
                "filtered_enqueued": filtered_enqueued_count,
                "search_rounds": search_rounds,
                "budget_exhausted": 1 if budget_exhausted else 0,
            },
        }
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="response-summary.json",
            content=_json_text(response_summary),
        )
        _debug_line(store, debug_lines, "[canceled] stopped_by_user")
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="debug.log",
            content="\n".join(debug_lines) + "\n",
        )
    except Exception as exc:
        response_summary = {
            "sources": response_summary_sources,
            "stats": {
                "found": total_found,
                "returned": 0,
                "target": target_candidates,
                "already_seen": already_seen_count,
                "already_enqueued": already_enqueued_count,
                "filtered_seen": filtered_seen_count,
                "filtered_enqueued": filtered_enqueued_count,
                "search_rounds": search_rounds,
                "budget_exhausted": 1 if budget_exhausted else 0,
            },
        }
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="response-summary.json",
            content=_json_text(response_summary),
        )
        _debug_line(store, debug_lines, f"[failed] {exc}")
        store.write_x_discovery_artifact(
            run_id=run_id,
            relative_path="debug.log",
            content="\n".join(debug_lines) + "\n",
        )
        store.finish_x_discovery_run(
            run_id=run_id,
            result_payload={
                "found": total_found,
                "returned": 0,
                "target": target_candidates,
                "already_seen": already_seen_count,
                "already_enqueued": already_enqueued_count,
                "filtered_seen": filtered_seen_count,
                "filtered_enqueued": filtered_enqueued_count,
                "search_rounds": search_rounds,
                "budget_exhausted": 1 if budget_exhausted else 0,
            },
            status="failed",
            current_phase=current_phase,
            progress_message="搜索失败",
            progress_payload=progress,
            error_message=str(exc),
        )


@router.post("/x/discovery/preview", status_code=202)
def preview_discovery(
    payload: DiscoveryPreviewRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DiscoveryPreviewAcceptedResponse:
    store = request.app.state.store
    settings = request.app.state.settings
    login_manager = getattr(request.app.state, "x_login_manager", None)
    request_payload = payload.model_dump(mode="json")
    storage_state_path = _resolve_discovery_storage_state(settings=settings, login_manager=login_manager)
    run_id = store.create_x_discovery_run(trigger="api", request_payload=request_payload)
    background_tasks.add_task(
        run_discovery_preview,
        run_id,
        request_payload,
        store=store,
        settings=settings,
        storage_state_path=storage_state_path,
    )
    return DiscoveryPreviewAcceptedResponse(run_id=run_id, status="pending")


@router.get("/x/discovery/runs/{run_id}")
def get_discovery_run_status(run_id: str, request: Request) -> DiscoveryRunStatusResponse:
    store = request.app.state.store
    run = store.get_x_discovery_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return _discovery_run_status_response(run_id, run)


@router.post("/x/discovery/runs/{run_id}/stop")
def stop_discovery_run(run_id: str, request: Request) -> DiscoveryRunStatusResponse:
    store = request.app.state.store
    run = store.get_x_discovery_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")

    status = str(run.get("status") or "pending")
    if status in TERMINAL_DISCOVERY_STATUSES:
        return _discovery_run_status_response(run_id, run)

    progress_payload = dict(run.get("progress_json") or {})
    progress_payload["stopped_by_user"] = True
    result_payload = dict(run.get("result_json") or {})
    result_payload.setdefault("found", 0)
    result_payload.setdefault("returned", 0)
    result_payload.setdefault("already_seen", 0)
    result_payload.setdefault("already_enqueued", 0)
    store.finish_x_discovery_run(
        run_id=run_id,
        result_payload=result_payload,
        status="canceled",
        current_phase=run.get("current_phase") or "completed",
        progress_message="预览已停止，可调整关键词后重新预览",
        progress_payload=progress_payload,
        error_message=None,
    )
    updated = store.get_x_discovery_run(run_id=run_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return _discovery_run_status_response(run_id, updated)


@router.get("/x/discovery/runs/{run_id}/items")
def get_discovery_run_items(run_id: str, request: Request) -> DiscoveryItemsResponse:
    store = request.app.state.store
    run = store.get_x_discovery_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    if run.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="Discovery run is not completed yet")
    items = [DiscoveryPreviewItem.model_validate(item) for item in store.list_x_discovery_items(run_id=run_id)]
    return DiscoveryItemsResponse(run_id=run_id, items=items)


@router.get("/x/discovery/runs/{run_id}/artifacts")
def list_discovery_artifacts(run_id: str, request: Request) -> DiscoveryArtifactIndexResponse:
    store = request.app.state.store
    try:
        files = store.list_x_discovery_artifacts(run_id=run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Discovery run not found") from exc
    return DiscoveryArtifactIndexResponse(run_id=run_id, files=files)


@router.get("/x/discovery/runs/{run_id}/artifacts/{artifact_path}")
def get_discovery_artifact(run_id: str, artifact_path: str, request: Request) -> PlainTextResponse:
    store = request.app.state.store
    try:
        file_path = store.resolve_x_discovery_artifact_path(
            run_id=run_id,
            relative_path=artifact_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Discovery artifact not found") from exc
    media_type = "application/json" if artifact_path.endswith(".json") else "text/plain"
    return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type=media_type)


@router.post("/x/discovery/login/start", status_code=202)
def start_discovery_login(request: Request) -> XLoginRunAcceptedResponse:
    manager = request.app.state.x_login_manager
    result = manager.start_login()
    return XLoginRunAcceptedResponse.model_validate(result)


@router.get("/x/discovery/login/runs/{run_id}")
def get_discovery_login_run(run_id: str, request: Request) -> XLoginRunStatusResponse:
    manager = request.app.state.x_login_manager
    run = manager.get_login_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="X login run not found")
    return XLoginRunStatusResponse.model_validate(run)


class DiscoveryEnqueueRequest(BaseModel):
    run_id: str
    selected_urls: list[str]
    max_enqueue: int = Field(default=10, ge=1, le=50)
    auto_run: bool = False
    auto_run_limit: int = Field(default=0, ge=0, le=3)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("run_id must not be empty")
        return normalized

    @field_validator("selected_urls")
    @classmethod
    def validate_selected_urls(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("selected_urls must not be empty")
        return cleaned


@router.post("/x/discovery/enqueue")
def enqueue_discovery(payload: DiscoveryEnqueueRequest, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    store = request.app.state.store
    pipeline = request.app.state.pipeline

    items = store.list_x_discovery_items(run_id=payload.run_id)
    allowed_urls = {item["canonical_url"] for item in items}
    selected = [url for url in payload.selected_urls if url in allowed_urls]
    if not selected:
        raise HTTPException(status_code=400, detail="No selected_urls matched the preview run_id")

    enqueued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    started = 0

    for canonical_url in selected[: payload.max_enqueue]:
        existing_job_id = store.get_x_discovery_enqueued_job(canonical_url=canonical_url)
        if existing_job_id is not None:
            skipped.append({"canonical_url": canonical_url, "reason": "already_enqueued", "job_id": existing_job_id})
            continue

        job = pipeline.create_job(canonical_url)
        store.record_x_discovery_enqueued(canonical_url=canonical_url, job_id=job.job_id)
        enqueued.append({"canonical_url": canonical_url, "job_id": job.job_id, "status": job.status, "action": "created"})

    if payload.auto_run:
        auto_run_count = len(enqueued) if payload.auto_run_limit <= 0 else min(payload.auto_run_limit, len(enqueued))
        for item in enqueued[:auto_run_count]:
            try:
                claim_token = store.claim_run(job_id=str(item["job_id"]))
            except (FileNotFoundError, FileExistsError, ValueError):
                continue
            background_tasks.add_task(pipeline.run, str(item["job_id"]), claim_token)
            item["status"] = "accepted"
            item["action"] = "created_and_started"
            started += 1

    return {
        "run_id": payload.run_id,
        "enqueued": enqueued,
        "skipped": skipped,
        "auto_run": {
            "requested": bool(payload.auto_run),
            "started": started,
            "skipped_due_to_limit": max(0, len(enqueued) - started) if payload.auto_run and payload.auto_run_limit > 0 else 0,
        },
    }
