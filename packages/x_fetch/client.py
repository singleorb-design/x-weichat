from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit


CONTENT_READY_SELECTOR = "article[data-testid='tweet'], article[data-testid='article'], div[data-testid='tweetText']"
CONTENT_WAIT_TIMEOUT_MS = 15000
ARTICLE_PATH_PATTERN = re.compile(r"^/(?:(?:i/articles?)|(?:[A-Za-z0-9_]{1,15}/article))/(\d+)/?$")
X_TO_MARKDOWN_SKILL_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "baoyu-danger-x-to-markdown"
    / "scripts"
    / "main.ts"
)
DEFAULT_SKILL_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "_x_to_markdown"


class XFetchError(RuntimeError):
    pass


def normalize_x_url(url: str) -> str:
    """把多种 X article URL 形态归一成 `/i/article/<id>`。

    背景：同一篇 X Article 可能同时存在
    - `https://x.com/i/article/<id>`
    - `https://x.com/i/articles/<id>`
    - `https://x.com/<user>/article/<id>`

    DOM 抓取、日志和后续 fallback 都希望只面对一种 canonical URL，
    所以这里统一收敛到 `/i/article/<id>`。
    """
    parsed = urlsplit(url)
    if parsed.netloc not in {"x.com", "www.x.com"}:
        return url

    article_match = ARTICLE_PATH_PATTERN.match(parsed.path)
    if article_match is None:
        return url

    normalized_path = f"/i/article/{article_match.group(1)}"
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))


def is_article_url(url: str) -> bool:
    """判断一个 URL 在归一化后是否属于 X Article。"""
    parsed = urlsplit(normalize_x_url(url))
    return parsed.netloc in {"x.com", "www.x.com"} and bool(
        re.match(r"^/i/article/\d+/?$", parsed.path)
    )


def fetch_x_markdown_with_skill(
    url: str,
    *,
    output_dir: str | Path | None = None,
    media_output_dir: str | Path | None = None,
    media_link_prefix: str | None = None,
) -> str:
    """调用 `baoyu-danger-x-to-markdown` 作为 article 抓取兜底。

    我们自己的第一优先级仍然是 Playwright + DOM：
    - 对 tweet 足够直接
    - 对不需要登录的页面也更轻量

    但某些 X Article 页面在当前环境下会只返回登录壳或错误壳，
    这时 DOM 永远等不到 `article[data-testid='article']`。

    `baoyu-danger-x-to-markdown` 走的是带 cookie 的反向工程 GraphQL 链路，
    对 article 更稳定，所以这里把它作为 article 专用 fallback。
    """
    normalized_url = normalize_x_url(url)
    script_path = X_TO_MARKDOWN_SKILL_SCRIPT
    script_dir = script_path.parent
    target_output_dir = _resolve_skill_output_dir(normalized_url, output_dir=output_dir)
    if not script_path.is_file():
        raise XFetchError(f"x-to-markdown skill script not found: {script_path}")

    # 尽量直接使用本机 bun；没有 bun 时再退回 `npx -y bun`。
    bun = shutil.which("bun")
    runner = [bun] if bun else ["npx", "-y", "bun"]

    # skill 支持 `--json`，stdout 会返回包含 `markdownPath` 的结构化结果；
    # 现在把它写到项目内相对目录，既保留调试产物，也避免落到系统临时目录。
    command = [
        *runner,
        str(script_path),
        normalized_url,
        "--json",
        "--download-media",
        "-o",
        str(target_output_dir),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=script_dir,
        env=os.environ.copy(),
    )

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise XFetchError(f"x-to-markdown skill failed for {normalized_url}: {detail}")

    try:
        # 这里要求 skill 的 stdout 必须是纯 JSON，便于程序化接管结果。
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise XFetchError(
            f"x-to-markdown skill returned invalid JSON for {normalized_url}: {completed.stdout.strip()}"
        ) from exc

    markdown_path = payload.get("markdownPath")
    if not isinstance(markdown_path, str) or not markdown_path:
        raise XFetchError(
            f"x-to-markdown skill did not return markdownPath for {normalized_url}"
        )

    resolved_markdown_path = _resolve_skill_markdown_path(markdown_path, output_dir=target_output_dir)
    markdown = resolved_markdown_path.read_text(encoding="utf-8")
    markdown = _materialize_skill_media(
        markdown,
        markdown_path=resolved_markdown_path,
        media_output_dir=media_output_dir,
        media_link_prefix=media_link_prefix,
    )
    return _rewrite_requested_url(markdown, requested_url=url)


def _resolve_skill_output_dir(url: str, *, output_dir: str | Path | None) -> Path:
    if output_dir is None:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        target = DEFAULT_SKILL_OUTPUT_ROOT / digest
    else:
        target = Path(output_dir)

    target.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_skill_markdown_path(markdown_path: str, *, output_dir: Path) -> Path:
    candidate = Path(markdown_path)
    if candidate.is_absolute():
        return candidate

    output_relative = output_dir / candidate
    if output_relative.is_file():
        return output_relative

    return candidate


def _materialize_skill_media(
    markdown: str,
    *,
    markdown_path: Path,
    media_output_dir: str | Path | None,
    media_link_prefix: str | None,
) -> str:
    if media_output_dir is None or not media_link_prefix:
        return markdown

    rewritten_markdown = markdown
    destination_root = Path(media_output_dir)
    destination_root.mkdir(parents=True, exist_ok=True)

    for directory_name in ("imgs", "videos"):
        source_dir = markdown_path.parent / directory_name
        if not source_dir.is_dir():
            continue

        destination_dir = destination_root / directory_name
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        shutil.copytree(source_dir, destination_dir)
        rewritten_markdown = _rewrite_local_media_paths(
            rewritten_markdown,
            source_prefix=f"{directory_name}/",
            target_prefix=f"{media_link_prefix}/{directory_name}/",
        )

    return rewritten_markdown


def _rewrite_local_media_paths(markdown: str, *, source_prefix: str, target_prefix: str) -> str:
    """重写 skill 下载出的相对媒体路径。

    需要同时覆盖：
    - Markdown 图片/链接：`![](imgs/x.jpg)`、`[demo](videos/x.mp4)`
    - YAML frontmatter：`coverImage: "imgs/x.jpg"`、`heroImage:    imgs/x.jpg`
    - HTML 属性：`src="imgs/x.jpg"`
    """

    rewritten = markdown
    # Markdown 链接/autolink 形态。
    rewritten = re.sub(
        rf'([(<]){re.escape(source_prefix)}',
        rf'\g<1>{target_prefix}',
        rewritten,
    )
    # 引号包裹的 YAML/HTML 属性值。
    rewritten = re.sub(
        rf'(["\']){re.escape(source_prefix)}',
        rf'\g<1>{target_prefix}',
        rewritten,
    )
    # 未加引号但在 YAML 冒号后出现的路径，允许多个空格。
    rewritten = re.sub(
        rf'(:\s*["\']?){re.escape(source_prefix)}',
        rf'\g<1>{target_prefix}',
        rewritten,
    )
    return rewritten


def _rewrite_requested_url(markdown: str, *, requested_url: str) -> str:
    """把 skill 产物里的 `requestedUrl` 改回用户原始输入。

    skill 内部通常会使用 canonical article URL（`/i/article/<id>`），
    但我们在本系统里希望保留“用户实际提交了什么 URL”，方便：
    - UI 展示
    - 排查问题
    - 和任务原始输入保持一致
    """
    serialized_url = json.dumps(requested_url, ensure_ascii=False)
    if re.search(r"^requestedUrl:\s*.+$", markdown, flags=re.MULTILINE):
        return re.sub(
            r"^requestedUrl:\s*.+$",
            f"requestedUrl: {serialized_url}",
            markdown,
            count=1,
            flags=re.MULTILINE,
        )

    if markdown.startswith("---\n"):
        return markdown.replace("---\n", f"---\nrequestedUrl: {serialized_url}\n", 1)

    return markdown


def fetch_x_page(url: str, storage_state: str | Path | dict[str, Any] | None = None) -> str:
    """使用 Playwright 抓取页面 HTML。

    这是 x-fetch 的“主路径”：
    1. 先把 article URL 归一化
    2. 用浏览器打开页面
    3. 等内容节点出现
    4. 返回整页 HTML 给 parser

    注意：这里只负责“拿到 HTML”，不负责把 HTML 解析成 markdown。
    解析逻辑在 `packages/x_fetch/parser.py`。
    """
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    normalized_url = normalize_x_url(url)
    context_kwargs: dict[str, Any] = {}
    if storage_state is not None:
        # storage_state 允许传入登录态，兼容 path / dict 两种形态。
        context_kwargs["storage_state"] = str(storage_state) if isinstance(storage_state, Path) else storage_state

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                page.goto(normalized_url, wait_until="domcontentloaded")
                try:
                    # 我们不等整页网络空闲，而是等“内容节点可见”：
                    # tweet 看 `tweet` / `tweetText`，article 看 `article[data-testid='article']`。
                    page.wait_for_selector(CONTENT_READY_SELECTOR, timeout=CONTENT_WAIT_TIMEOUT_MS)
                except PlaywrightTimeoutError as exc:
                    raise XFetchError(
                        "Timed out waiting for X content after DOMContentLoaded; "
                        f"selectors={CONTENT_READY_SELECTOR}, timeout_ms={CONTENT_WAIT_TIMEOUT_MS}, url={normalized_url}"
                    ) from exc
                return page.content()
            finally:
                context.close()
        finally:
            browser.close()
