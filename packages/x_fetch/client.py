from __future__ import annotations

from pathlib import Path
from typing import Any


CONTENT_READY_SELECTOR = "article[data-testid='tweet'], article[data-testid='article'], div[data-testid='tweetText']"
CONTENT_WAIT_TIMEOUT_MS = 15000


class XFetchError(RuntimeError):
    pass


def fetch_x_page(url: str, storage_state: str | Path | dict[str, Any] | None = None) -> str:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    context_kwargs: dict[str, Any] = {}
    if storage_state is not None:
        context_kwargs["storage_state"] = str(storage_state) if isinstance(storage_state, Path) else storage_state

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(CONTENT_READY_SELECTOR, timeout=CONTENT_WAIT_TIMEOUT_MS)
                except PlaywrightTimeoutError as exc:
                    raise XFetchError(
                        "Timed out waiting for X content after DOMContentLoaded; "
                        f"selectors={CONTENT_READY_SELECTOR}, timeout_ms={CONTENT_WAIT_TIMEOUT_MS}, url={url}"
                    ) from exc
                return page.content()
            finally:
                context.close()
        finally:
            browser.close()
