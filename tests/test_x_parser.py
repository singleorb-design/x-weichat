import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.jobs.store import JobStore  # noqa: E402
from agent.stages.x_fetch import run_x_fetch  # noqa: E402
from packages.x_fetch.client import XFetchError, fetch_x_page  # noqa: E402
from packages.x_fetch.parser import parse_x_html  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeContext:
    def __init__(self, *, job_id: str, url: str, storage_state: str | None = None) -> None:
        self.job_id = job_id
        self.url = url
        self.storage_state = storage_state


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
    assert markdown.startswith("# X Article: Shipping AI Agents")


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
