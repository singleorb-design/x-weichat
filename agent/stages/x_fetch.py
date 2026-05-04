from __future__ import annotations

from typing import Any

from agent.jobs.store import JobStore
from agent.stages.helpers import (
    dump_json,
    extract_first_markdown_image,
    extract_frontmatter,
    extract_markdown_title,
)
from packages.x_fetch.client import (
    XFetchError,
    fetch_x_markdown_with_skill,
    fetch_x_page,
    is_article_url,
    normalize_x_url,
)
from packages.x_fetch.parser import parse_x_html


def run_x_fetch(context: Any, store: JobStore) -> str:
    """执行 x-fetch 阶段并把结果落成 `01-source.md`。

    当前阶段分两条路径：
    - 主路径：`fetch_x_page()` → `parse_x_html()`
    - article 兜底：如果主路径抛出 `XFetchError`，且 URL 属于 article，
      就改走 `fetch_x_markdown_with_skill()`

    这样 tweet 仍然使用我们自己的轻量 DOM 抓取；
    article 在 DOM 方案不稳定时则对齐参考 skill 的 GraphQL 方案。
    """
    job_id = _get_context_value(context, "job_id")
    url = _get_context_value(context, "url")
    storage_state = _get_optional_context_value(context, "storage_state")

    try:
        # 主路径：拿 HTML，再由 parser 把 HTML 转成 markdown。
        html = fetch_x_page(url, storage_state=storage_state)
        parsed = parse_x_html(html, url=url)
        markdown = parsed.markdown
        source_type = parsed.content_type
    except XFetchError:
        # 只对 article 做 fallback。
        # tweet 超时通常意味着真正的抓取失败，不应静默换一套实现。
        if not is_article_url(url):
            raise
        markdown = fetch_x_markdown_with_skill(
            url,
            output_dir=store.get_job_dir(job_id) / "_x_to_markdown",
            media_output_dir=store.get_job_dir(job_id) / "01-source.assets",
            media_link_prefix="01-source.assets",
        )
        source_type = "article"

    frontmatter, _body = extract_frontmatter(markdown)
    metadata = {
        "url": normalize_x_url(url),
        "requestedUrl": url,
        "source_type": source_type,
        "title": extract_markdown_title(markdown),
        "coverImage": frontmatter.get("coverImage")
        or frontmatter.get("heroImage")
        or extract_first_markdown_image(markdown),
    }

    # x-fetch 阶段的标准产物始终是 `01-source.md`。
    store.write_artifact(
        job_id=job_id,
        relative_path="01-source.md",
        content=markdown,
    )
    store.write_artifact(
        job_id=job_id,
        relative_path="metadata.json",
        content=dump_json(metadata),
    )
    return markdown


def _get_context_value(context: Any, key: str) -> Any:
    if isinstance(context, dict):
        return context[key]
    return getattr(context, key)


def _get_optional_context_value(context: Any, key: str) -> Any:
    if isinstance(context, dict):
        return context.get(key)
    return getattr(context, key, None)
