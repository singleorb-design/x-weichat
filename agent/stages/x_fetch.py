from __future__ import annotations

from typing import Any

from agent.jobs.store import JobStore
from packages.x_fetch.client import fetch_x_page
from packages.x_fetch.parser import parse_x_html


def run_x_fetch(context: Any, store: JobStore) -> str:
    job_id = _get_context_value(context, "job_id")
    url = _get_context_value(context, "url")
    storage_state = _get_optional_context_value(context, "storage_state")

    html = fetch_x_page(url, storage_state=storage_state)
    parsed = parse_x_html(html, url=url)
    store.write_artifact(
        job_id=job_id,
        relative_path="01-source.md",
        content=parsed.markdown,
    )
    return parsed.markdown


def _get_context_value(context: Any, key: str) -> Any:
    if isinstance(context, dict):
        return context[key]
    return getattr(context, key)


def _get_optional_context_value(context: Any, key: str) -> Any:
    if isinstance(context, dict):
        return context.get(key)
    return getattr(context, key, None)

