import sys

import packages.x_fetch.client as x_fetch_client
from packages.x_fetch.client import (
    _extract_article_title_and_body_from_page,
    _build_search_progress_event,
    _extract_article_url_from_hrefs,
    _extract_status_url_from_hrefs,
    _guess_search_failure_reason,
    _is_probably_chinese_article_text,
)


def test_build_search_progress_event_caps_scroll_at_max_and_marks_missing_article_links() -> None:
    event = _build_search_progress_event(
        scroll_index=4,
        max_scrolls=4,
        tweet_count=12,
        raw_hits=3,
        after_likes_filter=3,
        after_keywords_filter=3,
        after_article_entity=0,
        after_article_url_extract=0,
        after_language_length_filter=0,
        duplicate_filtered=0,
        deduped_hits=0,
    )

    assert event == {
        "type": "scroll",
        "scroll": 4,
        "tweet_count": 12,
        "raw_hits": 3,
        "after_likes_filter": 3,
        "after_keywords_filter": 3,
        "after_article_entity": 0,
        "after_article_url_extract": 0,
        "after_language_length_filter": 0,
        "duplicate_filtered": 0,
        "deduped_hits": 0,
        "suspected_reason": "no_article_links_found",
        "sample": [],
    }


def test_build_search_progress_event_marks_filtered_by_min_likes() -> None:
    event = _build_search_progress_event(
        scroll_index=0,
        max_scrolls=4,
        tweet_count=8,
        raw_hits=0,
        after_likes_filter=0,
        after_keywords_filter=0,
        after_article_entity=0,
        after_article_url_extract=0,
        after_language_length_filter=0,
        duplicate_filtered=0,
        deduped_hits=0,
    )

    assert event["scroll"] == 0
    assert event["suspected_reason"] == "filtered_by_min_likes"


def test_build_search_progress_event_marks_filtered_by_language_or_length_when_articles_too_short_or_chinese() -> None:
    event = _build_search_progress_event(
        scroll_index=0,
        max_scrolls=0,
        tweet_count=10,
        raw_hits=0,
        after_likes_filter=3,
        after_keywords_filter=0,
        after_article_entity=3,
        after_article_url_extract=0,
        after_language_length_filter=0,
        duplicate_filtered=0,
        deduped_hits=0,
    )

    assert event["suspected_reason"] == "filtered_by_language_or_length"


def test_guess_search_failure_reason_detects_chinese_login_page() -> None:
    class FakeLocator:
        def __init__(self, text: str) -> None:
            self._text = text

        def inner_text(self, timeout: int = 0) -> str:
            return self._text

    class FakePage:
        url = "https://x.com/i/flow/login"

        def title(self) -> str:
            return "登录 / X"

        def locator(self, selector: str):
            assert selector == "body"
            return FakeLocator("请登录以继续")

    reason, page_url, title = _guess_search_failure_reason(FakePage())
    assert reason == "login_required"
    assert page_url == "https://x.com/i/flow/login"
    assert title == "登录 / X"


def test_extract_article_url_from_hrefs_preserves_author_article_path() -> None:
    article_url = _extract_article_url_from_hrefs(
        [
            "/GoogleAIStudio",
            "/GoogleAIStudio/status/2051421109506228656",
            "/GoogleAIStudio/article/2051421109506228656",
            "/GoogleAIStudio/article/2051421109506228656/media/2051419014849593345",
        ]
    )

    assert article_url == "https://x.com/GoogleAIStudio/article/2051421109506228656"


def test_extract_status_url_from_hrefs_returns_status_permalink() -> None:
    status_url = _extract_status_url_from_hrefs(
        [
            "/GoogleAIStudio",
            "/GoogleAIStudio/status/2051421109506228656",
            "/GoogleAIStudio/status/2051421109506228656/analytics",
        ]
    )

    assert status_url == "https://x.com/GoogleAIStudio/status/2051421109506228656"


def test_is_probably_chinese_article_text_detects_chinese_heavy_content() -> None:
    assert _is_probably_chinese_article_text("这是中文标题", "这是一篇中文文章，主要内容也都是中文。") is True
    assert _is_probably_chinese_article_text("Building Reliable Agents", "This article explains evaluation loops for agents.") is False


def test_article_text_meets_min_length_counts_english_words_for_discovery() -> None:
    assert hasattr(x_fetch_client, "_article_text_meets_min_length")

    short_body = " ".join(f"word{i}" for i in range(999))
    long_body = f"{short_body} word999"

    assert x_fetch_client._article_text_meets_min_length("Long English Article", short_body, min_length=1000) is False
    assert x_fetch_client._article_text_meets_min_length("Long English Article", long_body, min_length=1000) is True


def test_extract_article_title_and_body_from_page_uses_modern_x_article_selectors(monkeypatch) -> None:
    class FakeNode:
        def __init__(self, text: str) -> None:
            self._text = text

        def inner_text(self) -> str:
            return self._text

    class FakePage:
        def __init__(self) -> None:
            self._nodes = {
                "[data-testid='twitter-article-title']": FakeNode("The 170-Line SOUL.md That Made My Hermes Agent Dangerous"),
                "[data-testid='twitterArticleRichTextView']": FakeNode("People keep asking me the same question about Hermes."),
            }

        def content(self) -> str:
            return "<html></html>"

        def query_selector(self, selector: str):
            return self._nodes.get(selector)

        def title(self) -> str:
            return "(21) X"

    import packages.x_fetch.parser as x_parser

    def fake_parse_x_html(_html: str, _url: str):
        raise ValueError("Missing required article container")

    monkeypatch.setattr(x_parser, "parse_x_html", fake_parse_x_html)

    title, body = _extract_article_title_and_body_from_page(
        FakePage(),
        "https://x.com/tonysimons_/article/2051473178682118241",
    )

    assert title == "The 170-Line SOUL.md That Made My Hermes Agent Dangerous"
    assert body == "People keep asking me the same question about Hermes."


def test_extract_article_title_and_body_from_entity_prefers_structured_blocks_over_plain_text() -> None:
    title, body = x_fetch_client._extract_article_title_and_body_from_entity(
        {
            "title": "Model-Harness-Fit",
            "plain_text": "Flattened body without markdown structure.",
            "content_state": {
                "blocks": [
                    {"type": "header-two", "text": "The Evidence", "entityRanges": []},
                    {"type": "unstyled", "text": "Harness fit matters.", "entityRanges": []},
                    {"type": "unordered-list-item", "text": "tool surface", "entityRanges": []},
                    {"type": "ordered-list-item", "text": "measure it", "entityRanges": []},
                    {"type": "blockquote", "text": "Same weights, different harness.", "entityRanges": []},
                    {"type": "code-block", "text": "print('hello')", "entityRanges": []},
                    {
                        "type": "atomic",
                        "text": " ",
                        "entityRanges": [{"key": 0, "offset": 0, "length": 1}],
                    },
                ],
                "entityMap": {
                    "0": {
                        "key": "5",
                        "value": {
                            "type": "MARKDOWN",
                            "mutability": "Mutable",
                            "data": {
                                "markdown": "```python\nprint('from entity')\n```\n",
                            },
                        },
                    }
                },
            },
        }
    )

    assert title == "Model-Harness-Fit"
    assert body == (
        "## The Evidence\n\n"
        "Harness fit matters.\n\n"
        "- tool surface\n"
        "1. measure it\n\n"
        "> Same weights, different harness.\n\n"
        "```\n"
        "print('hello')\n"
        "```\n\n"
        "```python\n"
        "print('from entity')\n"
        "```"
    )


def test_resolve_graphql_candidate_from_status_url_uses_tweet_payload_article_entity(monkeypatch) -> None:
    tweet = {
        "core": {
            "user_results": {
                "result": {
                    "legacy": {
                        "screen_name": "GoogleAIStudio",
                    }
                }
            }
        },
        "article": {
            "article_results": {
                "result": {
                    "rest_id": "2051421109506228656",
                    "title": "Gemini 2.5 Pro Is Here",
                    "plain_text": " ".join(f"word{i}" for i in range(1005)),
                }
            }
        },
        "legacy": {
            "entities": {
                "urls": [
                    {"expanded_url": "https://x.com/GoogleAIStudio/article/2051421109506228656"},
                ]
            }
        },
    }

    monkeypatch.setattr(
        x_fetch_client,
        "_fetch_tweet_result_graphql",
        lambda *_args, **_kwargs: {"data": {"tweetResult": {"result": tweet}}},
        raising=False,
    )

    candidate = x_fetch_client._resolve_graphql_candidate_from_status_url(
        "https://x.com/GoogleAIStudio/status/2051421109506228656",
        cookie_map={"auth_token": "token", "ct0": "csrf"},
        likes=4321,
        tweet_text="Gemini article teaser",
        reason="search_like_threshold",
    )

    assert candidate == {
        "canonical_url": "https://x.com/i/article/2051421109506228656",
        "original_url": "https://x.com/GoogleAIStudio/article/2051421109506228656",
        "likes": 4321,
        "tweet_text": "Gemini article teaser",
        "score": 4321.0,
        "reason": "search_like_threshold",
    }


def test_discover_article_candidates_from_search_uses_graphql_status_resolution_when_dom_has_no_article_links(monkeypatch) -> None:
    candidate = {
        "canonical_url": "https://x.com/i/article/2051421109506228656",
        "original_url": "https://x.com/GoogleAIStudio/article/2051421109506228656",
        "likes": 987,
        "tweet_text": "Gemini article teaser",
        "score": 987.0,
        "reason": "search_like_threshold",
    }

    monkeypatch.setattr(
        x_fetch_client,
        "_resolve_graphql_candidate_from_status_url",
        lambda status_url, **_kwargs: candidate if status_url.endswith("/status/2051421109506228656") else None,
        raising=False,
    )

    class FakeLikeNode:
        def get_attribute(self, name: str) -> str:
            return "987 Likes" if name == "aria-label" else ""

        def inner_text(self) -> str:
            return "987"

        def query_selector(self, selector: str):
            return None

    class FakeTextNode:
        def inner_text(self) -> str:
            return "Gemini article teaser"

    class FakeAnchor:
        def __init__(self, href: str) -> None:
            self._href = href

        def get_attribute(self, name: str) -> str:
            return self._href if name == "href" else ""

    class FakeTweetArticle:
        def query_selector_all(self, selector: str):
            if selector in {"[data-testid='like']", "[data-testid='unlike']"}:
                return [FakeLikeNode()]
            if selector == "div[data-testid='tweetText']":
                return [FakeTextNode()]
            if selector == "a[href]":
                return [
                    FakeAnchor("/GoogleAIStudio"),
                    FakeAnchor("/GoogleAIStudio/status/2051421109506228656"),
                ]
            return []

    class FakeStatusPage:
        def goto(self, url: str, wait_until: str) -> None:
            self.url = url
            self.wait_until = wait_until

        def wait_for_selector(self, selector: str, timeout: int) -> None:
            return None

        def wait_for_timeout(self, timeout: int) -> None:
            return None

        def query_selector_all(self, selector: str):
            return []

        def close(self) -> None:
            return None

    class FakeSearchPage:
        def __init__(self) -> None:
            self.url = "https://x.com/search?q=ai&src=typed_query&f=top"
            self.mouse = type("FakeMouse", (), {"wheel": staticmethod(lambda *_args, **_kwargs: None)})()

        def goto(self, url: str, wait_until: str) -> None:
            self.url = url
            self.wait_until = wait_until

        def title(self) -> str:
            return "Search / X"

        def wait_for_selector(self, selector: str, timeout: int) -> None:
            return None

        def query_selector_all(self, selector: str):
            if selector == "article[data-testid='tweet']":
                return [FakeTweetArticle()]
            return []

        def wait_for_timeout(self, timeout: int) -> None:
            return None

    class FakeContext:
        def __init__(self) -> None:
            self._count = 0

        def new_page(self):
            self._count += 1
            if self._count == 1:
                return FakeSearchPage()
            return FakeStatusPage()

        def close(self) -> None:
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, headless: bool):
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

    results = x_fetch_client.discover_article_candidates_from_search(
        "ai",
        max_scrolls=0,
        max_candidates=5,
        min_likes=100,
    )

    assert results == [candidate]


def test_discover_article_candidates_from_search_prefers_graphql_timeline_results(monkeypatch) -> None:
    candidate = {
        "canonical_url": "https://x.com/i/article/2051192927460667392",
        "original_url": "https://x.com/i/article/2051192927460667392",
        "likes": 167,
        "tweet_text": "https://t.co/WQbNyZaIra",
        "score": 167.0,
        "reason": "search_like_threshold",
    }

    monkeypatch.setattr(
        x_fetch_client,
        "_discover_article_candidates_from_search_graphql",
        lambda *args, **kwargs: [candidate],
        raising=False,
    )

    def explode(**_kwargs):
        raise AssertionError("DOM fallback should not run when GraphQL search discovery succeeds")

    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_feed_url", explode)

    results = x_fetch_client.discover_article_candidates_from_search(
        "ai",
        storage_state="/tmp/x-state.json",
        max_scrolls=1,
        max_candidates=5,
        min_likes=100,
    )

    assert results == [candidate]


def test_discover_article_candidates_from_home_timeline_prefers_graphql_timeline_results(monkeypatch) -> None:
    candidate = {
        "canonical_url": "https://x.com/i/article/2051192927460667392",
        "original_url": "https://x.com/i/article/2051192927460667392",
        "likes": 167,
        "tweet_text": "https://t.co/WQbNyZaIra",
        "score": 167.0,
        "reason": "search_like_threshold",
    }

    monkeypatch.setattr(
        x_fetch_client,
        "_discover_article_candidates_from_home_timeline_graphql",
        lambda *args, **kwargs: [candidate],
        raising=False,
    )

    def explode(**_kwargs):
        raise AssertionError("DOM fallback should not run when GraphQL home discovery succeeds")

    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_feed_url", explode)

    results = x_fetch_client.discover_article_candidates_from_home_timeline(
        storage_state={"auth_token": "x", "ct0": "y"},
        max_scrolls=1,
        max_candidates=5,
        min_likes=100,
    )

    assert results == [candidate]


def test_discover_article_candidates_from_home_timeline_does_not_fallback_to_dom_when_graphql_throws(monkeypatch) -> None:
    import packages.x_fetch.client as x_fetch_client

    def fake_graphql(**_kwargs):
        raise x_fetch_client.XFetchError("X API error (403): {\"errors\":[{\"message\":\"Forbidden\"}]}")

    def explode(**_kwargs):
        raise AssertionError("DOM fallback should not run when HomeTimeline GraphQL fails")

    events: list[dict[str, object]] = []

    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_home_timeline_graphql", fake_graphql)
    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_feed_url", explode)

    results = x_fetch_client.discover_article_candidates_from_home_timeline(
        storage_state={"auth_token": "x", "ct0": "y"},
        max_scrolls=1,
        max_candidates=5,
        min_likes=100,
        progress_callback=lambda event: events.append(event),
    )

    assert results == []
    assert any(
        isinstance(event, dict) and event.get("type") == "hint" and event.get("suspected_reason") == "login_required"
        for event in events
    )


def test_search_graphql_uses_guest_token_when_no_login_cookies(monkeypatch) -> None:
    import packages.x_fetch.client as x_fetch_client

    candidate = {
        "canonical_url": "https://x.com/i/article/2051192927460667392",
        "original_url": "https://x.com/i/article/2051192927460667392",
        "likes": 167,
        "tweet_text": "https://t.co/WQbNyZaIra",
        "score": 167.0,
        "reason": "search_like_threshold",
    }

    monkeypatch.setattr(x_fetch_client, "_activate_x_guest_token", lambda **_kwargs: "guest", raising=False)
    monkeypatch.setattr(x_fetch_client, "_resolve_graphql_operation_query_id", lambda *_args, **_kwargs: "qid", raising=False)

    captured: dict[str, object] = {}

    def fake_post(url: str, *, headers: dict[str, str], payload: dict[str, object]):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"data": {"home": {"home_timeline_urt": {"instructions": []}}}}

    monkeypatch.setattr(x_fetch_client, "_post_x_graphql_json", fake_post, raising=False)
    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_timeline_payload", lambda *_args, **_kwargs: [candidate], raising=False)

    results = x_fetch_client._discover_article_candidates_from_search_graphql(
        "ai",
        storage_state=None,
        search_mode="latest",
        max_candidates=5,
        min_likes=100,
        required_keywords=None,
        progress_callback=None,
    )

    assert results == [candidate]
    assert str(captured.get("url") or "").endswith("/SearchTimeline")
    payload = captured.get("payload") or {}
    assert isinstance(payload, dict)
    variables = payload.get("variables") or {}
    assert isinstance(variables, dict)
    assert variables.get("product") == "Latest"
    headers = captured.get("headers") or {}
    assert isinstance(headers, dict)
    assert headers.get("x-guest-token") == "guest"


def test_discover_article_candidates_from_search_emits_hint_on_graphql_failure(monkeypatch) -> None:
    import packages.x_fetch.client as x_fetch_client

    def boom(*_args, **_kwargs):
        raise x_fetch_client.XFetchError("X API error (429): Too Many Requests")

    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_search_graphql", boom, raising=False)
    monkeypatch.setattr(x_fetch_client, "_discover_article_candidates_from_feed_url", lambda **_kwargs: [], raising=False)

    events: list[dict[str, object]] = []
    results = x_fetch_client.discover_article_candidates_from_search(
        "ai",
        storage_state=None,
        max_scrolls=0,
        max_candidates=5,
        min_likes=100,
        progress_callback=lambda event: events.append(event),
    )
    assert results == []
    assert any(
        isinstance(event, dict) and event.get("type") == "hint" and event.get("suspected_reason") == "rate_limited_or_challenged"
        for event in events
    )
