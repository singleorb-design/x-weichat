import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.jobs.store import JobStore  # noqa: E402
from agent.stages.x_fetch import run_x_fetch  # noqa: E402
from packages.x_fetch.client import (  # noqa: E402
    XFetchError,
    X_TO_MARKDOWN_SKILL_SCRIPT,
    fetch_x_markdown_with_skill,
    fetch_x_page,
)
from packages.x_fetch.parser import parse_x_html  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeContext:
    def __init__(self, *, job_id: str, url: str, storage_state: str | None = None) -> None:
        self.job_id = job_id
        self.url = url
        self.storage_state = storage_state


def test_x_to_markdown_skill_script_is_vendored_inside_repo() -> None:
    assert str(X_TO_MARKDOWN_SKILL_SCRIPT).startswith(str(REPO_ROOT))
    assert X_TO_MARKDOWN_SKILL_SCRIPT.is_file()


def test_parse_tweet_html_to_markdown() -> None:
    html = (FIXTURES_DIR / "x_tweet.html").read_text(encoding="utf-8")

    parsed = parse_x_html(html, url="https://x.com/alice/status/1234567890")

    assert parsed.content_type == "tweet"
    assert parsed.title == "Alice (@alice)"
    assert parsed.markdown == "# Alice (@alice)\n\nShipping v1 today. Docs tomorrow.\n"


def test_parse_article_html_to_markdown() -> None:
    html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")

    parsed = parse_x_html(html, url="https://x.com/i/articles/987654321")

    assert parsed.content_type == "article"
    assert parsed.title == "X Article: Shipping AI Agents"
    assert parsed.markdown == (
        "# X Article: Shipping AI Agents\n\n"
        "Opening paragraph.\n\n"
        "Second paragraph with more detail.\n\n"
        "- First point\n"
        "- Second point\n"
    )


def test_parse_singular_i_article_url_html_to_markdown() -> None:
    html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")

    parsed = parse_x_html(html, url="https://x.com/i/article/987654321")

    assert parsed.content_type == "article"
    assert parsed.title == "X Article: Shipping AI Agents"
    assert parsed.markdown.startswith("# X Article: Shipping AI Agents")


def test_parse_user_article_url_html_to_markdown() -> None:
    html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")

    parsed = parse_x_html(html, url="https://x.com/hooeem/article/2050332284675362853")

    assert parsed.content_type == "article"
    assert parsed.title == "X Article: Shipping AI Agents"
    assert parsed.markdown.startswith("# X Article: Shipping AI Agents")


def test_parse_article_html_raises_on_login_like_page() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title>Log in to X / X</title>
      </head>
      <body>
        <main>
          <section>
            <h1>Happening now</h1>
            <p>Join today.</p>
          </section>
        </main>
      </body>
    </html>
    """

    with pytest.raises(ValueError, match="Missing required article container"):
        parse_x_html(html, url="https://x.com/i/articles/987654321")


def test_parse_article_html_extracts_title_when_meta_attributes_are_reordered() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta content="Attribute Order Safe Title" property="og:title" />
      </head>
      <body>
        <main>
          <article data-testid="article">
            <p>Body still exists.</p>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/i/articles/987654321")

    assert parsed.title == "Attribute Order Safe Title"
    assert parsed.markdown == "# Attribute Order Safe Title\n\nBody still exists.\n"


def test_parse_article_html_preserves_interleaved_paragraph_and_list_order() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title>Interleaved Content</title>
      </head>
      <body>
        <main>
          <article data-testid="article">
            <h1>Interleaved Content</h1>
            <p>Opening paragraph.</p>
            <ul>
              <li>First bullet</li>
              <li>Second bullet</li>
            </ul>
            <div>
              <p>Paragraph after bullets.</p>
            </div>
            <ol>
              <li>Final numbered point</li>
            </ol>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/i/articles/24680")

    assert parsed.content_type == "article"
    assert parsed.markdown == (
        "# Interleaved Content\n\n"
        "Opening paragraph.\n\n"
        "- First bullet\n"
        "- Second bullet\n\n"
        "Paragraph after bullets.\n\n"
        "- Final numbered point\n"
    )


def test_parse_article_html_with_embedded_tweet_still_prefers_article() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title>Embedded Tweet Article</title>
      </head>
      <body>
        <main>
          <article data-testid="article">
            <h1>Embedded Tweet Article</h1>
            <p>Opening paragraph.</p>
            <section>
              <article data-testid="tweet">
                <div data-testid="User-Name">
                  <span>Embedded Author</span>
                  <span>@embedded</span>
                </div>
                <div data-testid="tweetText">
                  <span>This embedded tweet should not change the page type.</span>
                </div>
              </article>
            </section>
            <p>Closing paragraph.</p>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/i/articles/1122334455")

    assert parsed.content_type == "article"
    assert parsed.title == "Embedded Tweet Article"
    assert parsed.markdown == (
        "# Embedded Tweet Article\n\n"
        "Opening paragraph.\n\n"
        "Closing paragraph.\n"
    )


def test_parse_article_html_excludes_embedded_tweet_and_article_body_content() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title>Embedded Content Exclusion</title>
      </head>
      <body>
        <main>
          <article data-testid="article">
            <h1>Embedded Content Exclusion</h1>
            <p>Outer opening paragraph.</p>
            <section>
              <article data-testid="tweet">
                <div data-testid="tweetText">
                  <span>Embedded tweet paragraph should stay out.</span>
                </div>
                <p>Embedded tweet paragraph fallback should stay out too.</p>
              </article>
            </section>
            <section>
              <article data-testid="article">
                <h1>Nested article title</h1>
                <p>Nested article paragraph should stay out.</p>
              </article>
            </section>
            <p>Outer closing paragraph.</p>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/i/articles/55667788")

    assert parsed.content_type == "article"
    assert parsed.title == "Embedded Content Exclusion"
    assert parsed.markdown == (
        "# Embedded Content Exclusion\n\n"
        "Outer opening paragraph.\n\n"
        "Outer closing paragraph.\n"
    )
    assert "Embedded tweet paragraph should stay out." not in parsed.markdown
    assert "Embedded tweet paragraph fallback should stay out too." not in parsed.markdown
    assert "Nested article paragraph should stay out." not in parsed.markdown


def test_parse_tweet_html_with_nested_div_span_and_anchor_structure() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <body>
        <main>
          <article data-testid="tweet">
            <div data-testid="User-Name">
              <div>
                <a href="/alice">
                  <span>Alice</span>
                </a>
              </div>
              <div>
                <span>
                  <a href="/alice">@alice</a>
                </span>
              </div>
            </div>
            <div data-testid="tweetText">
              <div>
                <span>Nested body</span>
                <span>still parses.</span>
                <a href="https://example.com/docs">
                  <span>Read more</span>
                </a>
              </div>
            </div>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/alice/status/24680")

    assert parsed.content_type == "tweet"
    assert parsed.title == "Alice (@alice)"
    assert parsed.markdown == "# Alice (@alice)\n\nNested body still parses. Read more\n"


def test_parse_tweet_html_with_compact_author_subtree() -> None:
    html = """
    <!DOCTYPE html>
    <html lang="en">
      <body>
        <main>
          <article data-testid="tweet">
            <div data-testid="User-Name">
              <a href="/alice">
                <span>Alice</span>
                <span>@alice</span>
              </a>
            </div>
            <div data-testid="tweetText">
              <span>Compact author subtree still works.</span>
            </div>
          </article>
        </main>
      </body>
    </html>
    """

    parsed = parse_x_html(html, url="https://x.com/alice/status/13579")

    assert parsed.content_type == "tweet"
    assert parsed.title == "Alice (@alice)"
    assert parsed.markdown == "# Alice (@alice)\n\nCompact author subtree still works.\n"


def test_run_x_fetch_writes_source_markdown(monkeypatch, tmp_path: Path) -> None:
    html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/i/articles/987654321")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", lambda url, storage_state=None: html)

    markdown = run_x_fetch(
        FakeContext(job_id=job.job_id, url=job.url),
        store,
    )

    artifact_path = tmp_path / job.job_id / "01-source.md"
    assert markdown == artifact_path.read_text(encoding="utf-8")
    assert "# X Article: Shipping AI Agents" in markdown


def test_run_x_fetch_writes_source_markdown_for_user_article_url(monkeypatch, tmp_path: Path) -> None:
    html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/hooeem/article/2050332284675362853")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", lambda url, storage_state=None: html)

    markdown = run_x_fetch(
        FakeContext(job_id=job.job_id, url=job.url),
        store,
    )

    artifact_path = tmp_path / job.job_id / "01-source.md"
    assert markdown == artifact_path.read_text(encoding="utf-8")
    assert "# X Article: Shipping AI Agents" in markdown


def test_run_x_fetch_redirects_tweet_to_linked_article_status(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/karlmehta/status/2051346282434945129?s=12"
    linked_status_url = "https://x.com/karlmehta/status/2050561514306687291"
    tweet_html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <body>
        <main>
          <article data-testid=\"tweet\">
            <div data-testid=\"User-Name\">
              <a href=\"/karlmehta\">
                <span>Karl</span>
                <span>@karlmehta</span>
              </a>
            </div>
            <div data-testid=\"tweetText\">
              <span>Pointer tweet.</span>
              <a href=\"/karlmehta/status/2050561514306687291?s=12\">{linked_status_url}</a>
            </div>
          </article>
        </main>
      </body>
    </html>
    """
    article_html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)

    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return tweet_html
        if url == linked_status_url:
            return article_html
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)

    markdown = run_x_fetch(
        FakeContext(job_id=job.job_id, url=job.url),
        store,
    )

    assert calls == [tweet_url, linked_status_url]
    assert "# X Article: Shipping AI Agents" in markdown
    metadata_path = tmp_path / job.job_id / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_does_not_redirect_when_only_quote_tweet_has_status_link(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/alice/status/1"
    quote_status_url = "https://x.com/bob/status/2"
    html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <body>
        <main>
          <article data-testid=\"tweet\">
            <div data-testid=\"User-Name\">
              <a href=\"/alice\"><span>Alice</span><span>@alice</span></a>
            </div>
            <div data-testid=\"tweetText\"><span>Main tweet has no links.</span></div>
            <section>
              <article data-testid=\"tweet\">
                <div data-testid=\"User-Name\">
                  <a href=\"/bob\"><span>Bob</span><span>@bob</span></a>
                </div>
                <div data-testid=\"tweetText\">
                  <a href=\"/bob/status/2?s=12\">{quote_status_url}</a>
                </div>
              </article>
            </section>
          </article>
        </main>
      </body>
    </html>
    """
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)
    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return html
        raise AssertionError(f"should not fetch redirect candidate: {url}")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert calls == [tweet_url]
    assert "# Alice (@alice)" in markdown
    assert "Main tweet has no links." in markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "tweet"


def test_run_x_fetch_redirects_tweet_to_article_when_link_is_tco_with_expanded_title(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/alice/status/10"
    linked_status_url = "https://x.com/alice/status/20"
    tweet_html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <body>
        <main>
          <article data-testid=\"tweet\">
            <div data-testid=\"User-Name\">
              <a href=\"/alice\"><span>Alice</span><span>@alice</span></a>
            </div>
            <div data-testid=\"tweetText\">
              <a href=\"https://t.co/abc\" title=\"{linked_status_url}?s=12\">t.co/abc</a>
            </div>
          </article>
        </main>
      </body>
    </html>
    """
    article_html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)
    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return tweet_html
        if url == linked_status_url:
            return article_html
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert calls == [tweet_url, linked_status_url]
    assert "# X Article: Shipping AI Agents" in markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_redirects_tweet_to_article_when_tweettext_contains_spaced_article_url(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/nicbstme/status/2051131906327212298?s=12"
    article_id = "2051116213770883072"
    article_url = f"https://x.com/i/article/{article_id}"
    tweet_html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <body>
        <main>
          <article data-testid=\"tweet\">
            <div data-testid=\"User-Name\">
              <a href=\"/nicbstme\"><span>Nicolas Bustamante</span><span>@nicbstme</span></a>
            </div>
            <div data-testid=\"tweetText\">
              http:// x.com/i/article/{article_id[:4]} {article_id[4:]} …
            </div>
          </article>
        </main>
      </body>
    </html>
    """
    article_html = (FIXTURES_DIR / "x_article.html").read_text(encoding="utf-8")
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)
    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return tweet_html
        if url == article_url:
            return article_html
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert calls == [tweet_url, article_url]
    assert "# X Article: Shipping AI Agents" in markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_falls_back_to_skill_when_redirected_article_dom_fetch_times_out(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/nicbstme/status/2051131906327212298?s=12"
    article_url = "https://x.com/i/article/2051116213770883072"
    tweet_html = """
    <!DOCTYPE html>
    <html lang="en">
      <body>
        <main>
          <article data-testid="tweet">
            <div data-testid="User-Name">
              <a href="/nicbstme"><span>Nicolas Bustamante</span><span>@nicbstme</span></a>
            </div>
            <div data-testid="tweetText">
              http:// x.com/i/article/2051 116213770883072 …
            </div>
          </article>
        </main>
      </body>
    </html>
    """
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)
    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return tweet_html
        if url == article_url:
            raise XFetchError("Timed out waiting for X content after DOMContentLoaded")
        raise AssertionError(f"unexpected url: {url}")

    skill_markdown = (
        "---\nurl: \"https://x.com/i/article/2051116213770883072\"\n---\n\n"
        "# Model-Harness-Fit\n\n"
        "This is a long enough body to pass the empty-markdown heuristic.\n"
    )

    def fake_skill(
        url: str,
        *,
        output_dir: str | Path | None = None,
        media_output_dir: str | Path | None = None,
        media_link_prefix: str | None = None,
    ) -> str:
        assert url == article_url
        return skill_markdown

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)
    # 避免触发 GraphQL 网络兜底，专测 skill fallback。
    monkeypatch.setattr(
        "agent.stages.x_fetch.resolve_article_markdown_from_status_url_graphql",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        "agent.stages.x_fetch.fetch_article_markdown_via_graphql",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_markdown_with_skill", fake_skill, raising=False)

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert calls == [tweet_url, article_url]
    assert markdown == skill_markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_falls_back_to_graphql_article_when_article_dom_fetch_times_out(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/nicbstme/status/2051131906327212298?s=12"
    article_url = "https://x.com/i/article/2051116213770883072"
    tweet_html = """
    <!DOCTYPE html>
    <html lang="en">
      <body>
        <main>
          <article data-testid="tweet">
            <div data-testid="User-Name">
              <a href="/nicbstme"><span>Nicolas Bustamante</span><span>@nicbstme</span></a>
            </div>
            <div data-testid="tweetText">
              http:// x.com/i/article/2051 116213770883072 …
            </div>
          </article>
        </main>
      </body>
    </html>
    """
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)
    calls: list[str] = []

    def fake_fetch(url: str, storage_state=None) -> str:
        calls.append(url)
        if url == tweet_url:
            return tweet_html
        if url == article_url:
            raise XFetchError("Timed out waiting for X content after DOMContentLoaded")
        raise AssertionError(f"unexpected url: {url}")

    graphql_markdown = "# Model-Harness-Fit\n\nGraphQL body is present.\n"

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fake_fetch)
    # 避免触发 status GraphQL 网络兜底，专测 article GraphQL 兜底。
    monkeypatch.setattr(
        "agent.stages.x_fetch.resolve_article_markdown_from_status_url_graphql",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        "agent.stages.x_fetch.fetch_article_markdown_via_graphql",
        lambda url, storage_state=None: graphql_markdown if url == article_url else None,
        raising=False,
    )

    # 不应落到 skill。
    monkeypatch.setattr(
        "agent.stages.x_fetch.fetch_x_markdown_with_skill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("skill should not be called")),
        raising=False,
    )

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert calls == [tweet_url, article_url]
    assert markdown == graphql_markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_falls_back_to_graphql_status_when_tweet_dom_fetch_fails(monkeypatch, tmp_path: Path) -> None:
    tweet_url = "https://x.com/nicbstme/status/2051131906327212298?s=12"
    resolved_article_url = "https://x.com/i/article/2051116213770883072"
    resolved_markdown = "# Model-Harness-Fit\n\nResolved from status via GraphQL.\n"
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url=tweet_url)

    def fail_fetch(_url: str, storage_state=None) -> str:
        raise XFetchError("Timed out waiting for X content")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fail_fetch)
    monkeypatch.setattr(
        "agent.stages.x_fetch.resolve_article_markdown_from_status_url_graphql",
        lambda url, storage_state=None: (resolved_article_url, resolved_markdown) if url == tweet_url else None,
        raising=False,
    )

    markdown = run_x_fetch(FakeContext(job_id=job.job_id, url=job.url), store)

    assert markdown == resolved_markdown
    payload = json.loads((tmp_path / job.job_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["requestedUrl"] == tweet_url
    assert payload["source_type"] == "article"


def test_run_x_fetch_falls_back_to_skill_markdown_for_article_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    store = JobStore(root_dir=tmp_path)
    job = store.create_job(url="https://x.com/hooeem/article/2050332284675362853")
    skill_markdown = (
        "---\n"
        'url: "https://x.com/i/article/2050332284675362853"\n'
        'requestedUrl: "https://x.com/hooeem/article/2050332284675362853"\n'
        'title: "how to find the next 100x idea:"\n'
        "---\n\n"
        "# how to find the next 100x idea:\n\n"
        "Stop wasting your time, build this instead.\n"
    )

    def fail_fetch(_url: str, storage_state=None) -> str:
        raise XFetchError("Timed out waiting for X content after DOMContentLoaded")

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_page", fail_fetch)
    captured: dict[str, Path | str] = {}

    def fake_skill(
        url: str,
        *,
        output_dir: str | Path | None = None,
        media_output_dir: str | Path | None = None,
        media_link_prefix: str | None = None,
    ) -> str:
        assert url == job.url
        captured["output_dir"] = Path(output_dir) if output_dir is not None else Path()
        captured["media_output_dir"] = Path(media_output_dir) if media_output_dir is not None else Path()
        captured["media_link_prefix"] = media_link_prefix or ""
        return skill_markdown

    monkeypatch.setattr("agent.stages.x_fetch.fetch_x_markdown_with_skill", fake_skill, raising=False)

    markdown = run_x_fetch(
        FakeContext(job_id=job.job_id, url=job.url),
        store,
    )

    artifact_path = tmp_path / job.job_id / "01-source.md"
    assert markdown == skill_markdown
    assert markdown == artifact_path.read_text(encoding="utf-8")
    assert markdown.startswith("---\n")
    assert "requestedUrl: \"https://x.com/hooeem/article/2050332284675362853\"" in markdown
    assert captured["output_dir"] == tmp_path / job.job_id / "_x_to_markdown"
    assert captured["media_output_dir"] == tmp_path / job.job_id / "01-source.assets"
    assert captured["media_link_prefix"] == "01-source.assets"


def test_fetch_x_markdown_with_skill_uses_project_output_dir_and_resolves_relative_markdown_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "_x_to_markdown"
    markdown_path = output_dir / "article.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        '---\nrequestedUrl: "https://x.com/i/article/2050332284675362853"\n---\n\n# title\n',
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr("packages.x_fetch.client.shutil.which", lambda _: "/opt/homebrew/bin/bun")

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        cwd: Path,
        env: dict[str, str],
    ) -> object:
        calls["command"] = command
        calls["cwd"] = cwd
        calls["capture_output"] = capture_output
        calls["text"] = text
        calls["env_has_path"] = "PATH" in env
        return type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": '{"markdownPath":"article.md"}', "stderr": ""},
        )()

    monkeypatch.setattr("packages.x_fetch.client.subprocess.run", fake_run)

    markdown = fetch_x_markdown_with_skill(
        "https://x.com/hooeem/article/2050332284675362853",
        output_dir=output_dir,
    )

    assert markdown.startswith('---\nrequestedUrl: "https://x.com/hooeem/article/2050332284675362853"')
    assert calls["command"] == [
        "/opt/homebrew/bin/bun",
        str(X_TO_MARKDOWN_SKILL_SCRIPT),
        "https://x.com/i/article/2050332284675362853",
        "--json",
        "--download-media",
        "-o",
        str(output_dir),
    ]
    assert calls["cwd"] == X_TO_MARKDOWN_SKILL_SCRIPT.parent


def test_fetch_x_page_wait_for_selector_timeout_raises_x_fetch_error(monkeypatch) -> None:
    class FakePlaywrightTimeoutError(Exception):
        pass

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            self.url = url
            self.wait_until = wait_until

        def wait_for_selector(self, selector: str, timeout: int) -> None:
            raise FakePlaywrightTimeoutError("boom")

    class FakeContextForTimeout:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            pass

    class FakeBrowserForTimeout:
        def new_context(self, **kwargs):
            self.kwargs = kwargs
            return FakeContextForTimeout()

        def close(self) -> None:
            pass

    class FakeChromiumForTimeout:
        def launch(self, headless: bool):
            self.headless = headless
            return FakeBrowserForTimeout()

    class FakeSyncPlaywright:
        def __enter__(self):
            return type("FakePlaywright", (), {"chromium": FakeChromiumForTimeout()})()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSyncApiModule:
        TimeoutError = FakePlaywrightTimeoutError

        @staticmethod
        def sync_playwright() -> FakeSyncPlaywright:
            return FakeSyncPlaywright()

    fake_sync_api = FakeSyncApiModule()

    monkeypatch.setitem(sys.modules, "playwright", type("FakePlaywrightPackage", (), {"sync_api": fake_sync_api})())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    with pytest.raises(XFetchError, match=r"Timed out waiting for X content"):
        fetch_x_page("https://x.com/example/status/1")


def test_fetch_x_page_normalizes_path_storage_state_for_new_context(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            captured["goto"] = (url, wait_until)

        def wait_for_selector(self, selector: str, timeout: int) -> None:
            captured["wait_for_selector"] = (selector, timeout)

        def content(self) -> str:
            return "<html><body>ok</body></html>"

    class FakeContextForStorage:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            captured["context_closed"] = True

    class FakeBrowserForStorage:
        def new_context(self, **kwargs):
            captured["new_context_kwargs"] = kwargs
            return FakeContextForStorage()

        def close(self) -> None:
            captured["browser_closed"] = True

    class FakeChromiumForStorage:
        def launch(self, headless: bool):
            captured["headless"] = headless
            return FakeBrowserForStorage()

    class FakeSyncPlaywright:
        def __enter__(self):
            return type("FakePlaywright", (), {"chromium": FakeChromiumForStorage()})()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSyncApiModule:
        TimeoutError = RuntimeError

        @staticmethod
        def sync_playwright() -> FakeSyncPlaywright:
            return FakeSyncPlaywright()

    fake_sync_api = FakeSyncApiModule()

    monkeypatch.setitem(sys.modules, "playwright", type("FakePlaywrightPackage", (), {"sync_api": fake_sync_api})())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    storage_state = tmp_path / "state.json"
    html = fetch_x_page("https://x.com/i/articles/42", storage_state=storage_state)

    assert html == "<html><body>ok</body></html>"
    assert captured["new_context_kwargs"] == {"storage_state": str(storage_state)}


def test_fetch_x_page_normalizes_user_article_url_before_navigation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            captured["goto"] = (url, wait_until)

        def wait_for_selector(self, selector: str, timeout: int) -> None:
            captured["wait_for_selector"] = (selector, timeout)

        def content(self) -> str:
            return "<html><body>ok</body></html>"

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            captured["context_closed"] = True

    class FakeBrowser:
        def new_context(self, **kwargs):
            captured["new_context_kwargs"] = kwargs
            return FakeContext()

        def close(self) -> None:
            captured["browser_closed"] = True

    class FakeChromium:
        def launch(self, headless: bool):
            captured["headless"] = headless
            return FakeBrowser()

    class FakeSyncPlaywright:
        def __enter__(self):
            return type("FakePlaywright", (), {"chromium": FakeChromium()})()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSyncApiModule:
        TimeoutError = RuntimeError

        @staticmethod
        def sync_playwright() -> FakeSyncPlaywright:
            return FakeSyncPlaywright()

    fake_sync_api = FakeSyncApiModule()

    monkeypatch.setitem(sys.modules, "playwright", type("FakePlaywrightPackage", (), {"sync_api": fake_sync_api})())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    html = fetch_x_page("https://x.com/hooeem/article/2050332284675362853")

    assert html == "<html><body>ok</body></html>"
    assert captured["goto"] == (
        "https://x.com/i/article/2050332284675362853",
        "domcontentloaded",
    )
