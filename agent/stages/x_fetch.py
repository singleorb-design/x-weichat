from __future__ import annotations

import re
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
    fetch_article_markdown_via_graphql,
    fetch_x_markdown_with_skill,
    fetch_x_page,
    is_article_url,
    normalize_x_url,
    resolve_article_markdown_from_status_url_graphql,
)
from packages.x_fetch.parser import extract_linked_x_urls_from_tweet_html, parse_x_html


_WORDLIKE_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
_CJK_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
_JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30FF]")
_HANGUL_PATTERN = re.compile(r"[\uAC00-\uD7AF]")


def _is_effectively_empty_markdown(markdown: str) -> bool:
    frontmatter, body = extract_frontmatter(markdown)
    _ = frontmatter
    text = (body or "").strip()
    if not text:
        return True
    if re.fullmatch(r"```json\s*\{\s*\}\s*```", text, flags=re.IGNORECASE | re.MULTILINE):
        return True
    # 过滤掉纯 JSON/代码块壳。
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text) < 20


def _is_probably_english_article(markdown: str) -> bool:
    _frontmatter, body = extract_frontmatter(markdown)
    title = extract_markdown_title(markdown) or ""
    sample = f"{title}\n{body}".strip()
    if not sample:
        return False

    kana = len(_JAPANESE_KANA_PATTERN.findall(sample))
    hangul = len(_HANGUL_PATTERN.findall(sample))
    cjk = len(_CJK_PATTERN.findall(sample))
    latin_words = len(_WORDLIKE_PATTERN.findall(sample))
    latin_chars = len(re.findall(r"[A-Za-z]", sample))

    # 明确排除日文/韩文。
    if kana >= 20 or hangul >= 20:
        return False

    # 少量假名/韩文仍可能出现在引用/人名/标签里，但不应“主导”正文。
    if kana > max(5, latin_words // 2):
        return False
    if hangul > max(5, latin_words // 2):
        return False

    # 对短文放宽阈值：只要是纯拉丁脚本且词数达到基本可读长度，就认为是英文。
    # （测试用 fixture/skill 兜底文章往往更短，但仍应被接受。）
    if cjk == 0 and kana == 0 and hangul == 0 and latin_words >= 8 and latin_chars >= 30:
        return True

    # 英文文章不应被 CJK 主导。
    if cjk > max(20, latin_words):
        return False

    # 对中长文使用更稳健的阈值。
    if latin_words >= 30 and latin_words >= cjk and latin_chars >= 80:
        return True
    if latin_words >= 20 and latin_words >= (cjk * 2) and latin_chars >= 60:
        return True

    return False


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
    requested_url = _get_context_value(context, "url")
    storage_state = _get_optional_context_value(context, "storage_state")

    markdown: str
    source_type: str
    effective_url = requested_url
    article_hint_url: str | None = None

    try:
        # 主路径：拿 HTML，再由 parser 把 HTML 转成 markdown。
        html = fetch_x_page(effective_url, storage_state=storage_state)
        parsed = parse_x_html(html, url=effective_url)
        markdown = parsed.markdown
        source_type = parsed.content_type

        # 如果是 tweet，尝试解析其中指向 X Article 的链接（或指向会渲染成 article 的 status）。
        if source_type == "tweet":
            for candidate_url in extract_linked_x_urls_from_tweet_html(html)[:5]:
                if normalize_x_url(candidate_url) == normalize_x_url(effective_url):
                    continue

                # 如果明确是 article URL：优先切换到它，并允许后续走 skill 兜底。
                if is_article_url(candidate_url):
                    article_hint_url = candidate_url
                    effective_url = candidate_url
                    candidate_html = fetch_x_page(candidate_url, storage_state=storage_state)
                    try:
                        candidate_parsed = parse_x_html(candidate_html, url=candidate_url)
                        markdown = candidate_parsed.markdown
                        source_type = candidate_parsed.content_type
                    except Exception:
                        markdown = ""
                        source_type = "unknown"
                    break

                # status URL：仅在 DOM 解析明确拿到 article 且正文非空时才切换。
                try:
                    candidate_html = fetch_x_page(candidate_url, storage_state=storage_state)
                    candidate_parsed = parse_x_html(candidate_html, url=candidate_url)
                except Exception:
                    continue
                if candidate_parsed.content_type != "article":
                    continue
                candidate_markdown = candidate_parsed.markdown
                if not candidate_markdown or _is_effectively_empty_markdown(candidate_markdown):
                    continue
                effective_url = candidate_url
                markdown = candidate_markdown
                source_type = "article"
                break
    except XFetchError:
        markdown = ""
        source_type = "unknown"

    # 如果 status 的 DOM 抓取失败，尝试用 GraphQL(guest) 解析关联的 X Article。
    if (not markdown or _is_effectively_empty_markdown(markdown)) and "/status/" in requested_url:
        resolved = resolve_article_markdown_from_status_url_graphql(requested_url, storage_state=storage_state)
        if resolved is not None:
            resolved_url, resolved_markdown = resolved
            if resolved_markdown and not _is_effectively_empty_markdown(resolved_markdown):
                effective_url = resolved_url
                markdown = resolved_markdown
                source_type = "article"

    # 如果主路径拿到的是“空壳”，对 article 直接尝试 skill 兜底。
    fallback_article_url = effective_url
    if article_hint_url and is_article_url(article_hint_url):
        fallback_article_url = article_hint_url
    if (not markdown or _is_effectively_empty_markdown(markdown)) and is_article_url(fallback_article_url):
        # GraphQL(guest) 优先：无需 Playwright DOM，也不依赖 bun skill。
        graphql_markdown = fetch_article_markdown_via_graphql(fallback_article_url, storage_state=storage_state)
        if graphql_markdown and not _is_effectively_empty_markdown(graphql_markdown):
            markdown = graphql_markdown
            source_type = "article"
            effective_url = fallback_article_url
        else:
            markdown = fetch_x_markdown_with_skill(
                fallback_article_url,
                output_dir=store.get_job_dir(job_id) / "_x_to_markdown",

                # Media landing:
                # - Images/videos are downloaded into the job workspace so they can be previewed and
                #   later localized by overwriting files in place.
                # - Keep the markdown links stable by using a fixed prefix (`01-source.assets`).
                media_output_dir=store.get_job_dir(job_id) / "01-source.assets",
                media_link_prefix="01-source.assets",
            )
            source_type = "article"
            effective_url = fallback_article_url

    # tweet 超时通常意味着真正的抓取失败，不应静默换一套实现。
    if (not markdown or _is_effectively_empty_markdown(markdown)):
        raise XFetchError("原文抓取失败：未解析到有效正文内容")

    # 仅处理英文文章（避免日语/中文等被错误纳入并翻译）。
    if source_type == "article" and not _is_probably_english_article(markdown):
        raise XFetchError("检测到原文不是英文（例如日语/中文等），已跳过")

    frontmatter, _body = extract_frontmatter(markdown)
    metadata = {
        "url": normalize_x_url(effective_url),
        "requestedUrl": requested_url,
        "source_type": source_type,
        "title": extract_markdown_title(markdown),
        "coverImage": frontmatter.get("coverImage")
        or frontmatter.get("heroImage")
        or extract_first_markdown_image(markdown),
    }

    # 给任务列表使用的轻量字段：把原文标题写回 job 记录，避免前端额外拉取 metadata.json。
    store.update_source_title(job_id=job_id, source_title=metadata.get("title"))

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
