from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote_plus, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen


CONTENT_READY_SELECTOR = "article[data-testid='tweet'], article[data-testid='article'], div[data-testid='tweetText']"
CONTENT_WAIT_TIMEOUT_MS = 15000
ARTICLE_PATH_PATTERN = re.compile(r"^/(?:(?:i/articles?)|(?:[A-Za-z0-9_]{1,15}/article))/(\d+)/?$")
DISCOVERY_MIN_ARTICLE_LENGTH = 1000
_WORDLIKE_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
X_TO_MARKDOWN_SKILL_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "baoyu-danger-x-to-markdown"
    / "scripts"
    / "main.ts"
)
DEFAULT_SKILL_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "_x_to_markdown"
DEFAULT_X_BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
DEFAULT_X_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
X_GRAPHQL_COOKIE_NAMES = ("auth_token", "ct0", "gt", "twid")
X_GRAPHQL_REQUIRED_COOKIE_NAMES = ("auth_token", "ct0")
X_GUEST_ACTIVATE_ENDPOINTS = (
    "https://api.twitter.com/1.1/guest/activate.json",
    "https://api.x.com/1.1/guest/activate.json",
)
FALLBACK_ARTICLE_QUERY_ID = "id8pHQbQi7eZ6P9mA1th1Q"
FALLBACK_ARTICLE_FEATURE_SWITCHES = [
    "profile_label_improvements_pcf_label_in_post_enabled",
    "responsive_web_profile_redirect_enabled",
    "rweb_tipjar_consumption_enabled",
    "verified_phone_label_enabled",
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
    "responsive_web_graphql_timeline_navigation_enabled",
]
FALLBACK_ARTICLE_FIELD_TOGGLES = ["withPayments", "withAuxiliaryUserLabels"]
FALLBACK_TWEET_QUERY_ID = "HJ9lpOL-ZlOk5CkCw0JW6Q"
FALLBACK_SEARCH_TIMELINE_QUERY_ID = "BqWLX1Tjvgh6eSZWEMH_kw"
FALLBACK_HOME_TIMELINE_QUERY_ID = "jYMvLJJjGjO3aKWY3bP5HA"
FALLBACK_TWEET_FEATURE_SWITCHES = [
    "creator_subscriptions_tweet_preview_api_enabled",
    "premium_content_api_read_enabled",
    "communities_web_enable_tweet_community_results_fetch",
    "c9s_tweet_anatomy_moderator_badge_enabled",
    "responsive_web_grok_analyze_button_fetch_trends_enabled",
    "responsive_web_grok_analyze_post_followups_enabled",
    "responsive_web_jetfuel_frame",
    "responsive_web_grok_share_attachment_enabled",
    "responsive_web_grok_annotations_enabled",
    "articles_preview_enabled",
    "responsive_web_edit_tweet_api_enabled",
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
    "view_counts_everywhere_api_enabled",
    "longform_notetweets_consumption_enabled",
    "responsive_web_twitter_article_tweet_consumption_enabled",
    "tweet_awards_web_tipping_enabled",
    "responsive_web_grok_show_grok_translated_post",
    "responsive_web_grok_analysis_button_from_backend",
    "post_ctas_fetch_enabled",
    "creator_subscriptions_quote_tweet_preview_enabled",
    "freedom_of_speech_not_reach_fetch_enabled",
    "standardized_nudges_misinfo",
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
    "longform_notetweets_rich_text_read_enabled",
    "longform_notetweets_inline_media_enabled",
    "profile_label_improvements_pcf_label_in_post_enabled",
    "responsive_web_profile_redirect_enabled",
    "rweb_tipjar_consumption_enabled",
    "verified_phone_label_enabled",
    "responsive_web_grok_image_annotation_enabled",
    "responsive_web_grok_imagine_annotation_enabled",
    "responsive_web_grok_community_note_auto_translation_is_enabled",
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
    "responsive_web_graphql_timeline_navigation_enabled",
    "responsive_web_enhance_cards_enabled",
]
FALLBACK_TWEET_FIELD_TOGGLES = [
    "withArticleRichContentState",
    "withArticlePlainText",
    "withGrokAnalyze",
    "withDisallowedReplyControls",
    "withPayments",
    "withAuxiliaryUserLabels",
]


class XFetchError(RuntimeError):
    pass


def fetch_article_markdown_via_graphql(
    article_url: str,
    *,
    storage_state: str | Path | dict[str, Any] | None = None,
) -> str | None:
    """用 X GraphQL 拉取 article entity 并转成 markdown。

    说明：这里优先使用 guest token（无需登录），若 storage_state 提供了登录 cookie 也会复用。
    """

    article_id = _parse_article_id_from_url(article_url)
    if not article_id:
        return None

    cookie_map = _ensure_x_guest_cookie_map(storage_state)
    try:
        payload = _fetch_article_entity_by_id_graphql(article_id, cookie_map)
        _raise_if_graphql_payload_has_errors(payload, operation="ArticleEntityResultByRestId")
    except Exception:
        return None

    entity = _coerce_article_entity(_extract_article_entity_from_payload(payload))
    if entity is None or not _has_article_content(entity):
        return None

    title, body = _extract_article_title_and_body_from_entity(entity)
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return None
    return f"# {title}\n\n{body}\n"


def resolve_article_markdown_from_status_url_graphql(
    status_url: str,
    *,
    storage_state: str | Path | dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """从 tweet status URL 解析其关联的 X Article，并返回 (article_url, markdown)。

    目标：当 Playwright DOM 抓取拿不到 tweetText（登录壳/风控/网络抖动）时，仍能抓到完整文章。
    """

    tweet_id = _extract_tweet_id_from_status_url(status_url)
    if not tweet_id:
        return None

    cookie_map = _ensure_x_guest_cookie_map(storage_state)
    try:
        payload = _fetch_tweet_result_graphql(tweet_id, cookie_map)
        _raise_if_graphql_payload_has_errors(payload, operation="TweetResultByRestId")
    except Exception:
        return None

    tweet = _extract_tweet_from_payload(payload)
    if tweet is None:
        return None

    article = _resolve_article_entity_from_tweet_graphql(tweet, cookie_map)
    if article is None or not _has_article_content(article):
        return None

    article_id = str(article.get("rest_id") or _extract_article_id_from_tweet(tweet) or "").strip()
    if not article_id:
        return None

    title, body = _extract_article_title_and_body_from_entity(article)
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return None

    article_url = f"https://x.com/i/article/{article_id}"
    return article_url, f"# {title}\n\n{body}\n"


_X_API_ERROR_CODE_PATTERN = re.compile(r"\((\d{3})\)")


def _classify_x_graphql_failure(exc: Exception) -> tuple[str, str]:
    """将 GraphQL 拉取失败分类成 UI 可消费的 suspected_reason。

    返回：
    - suspected_reason: login_required | rate_limited_or_challenged | graphql_failed
    - detail: 简短可读的诊断信息（用于 debug.log / suspected_detail）
    """

    raw = f"{type(exc).__name__}: {str(exc)}"
    message = str(exc)
    lower = message.lower()
    code: int | None = None
    match = _X_API_ERROR_CODE_PATTERN.search(message)
    if match is not None:
        try:
            code = int(match.group(1))
        except Exception:
            code = None

    # 先用 HTTP code 粗分（403 可能是风控挑战，因此再用关键字细分一下）。
    if code == 401:
        return "login_required", raw[:240]
    if code == 403:
        if any(token in lower for token in ("challenge", "verify", "captcha", "频率", "验证", "挑战")):
            return "rate_limited_or_challenged", raw[:240]
        return "login_required", raw[:240]
    if code == 429:
        return "rate_limited_or_challenged", raw[:240]

    # 再用关键字兜底（不同环境下 X 可能返回 HTML/JSON 混合壳）。
    if any(token in lower for token in ("unauthorized", "forbidden", "csrf", "ct0", "login", "sign in")):
        return "login_required", raw[:240]
    if any(token in lower for token in ("rate limit", "too many requests", "challenge", "verify")):
        return "rate_limited_or_challenged", raw[:240]

    return "graphql_failed", raw[:240]


def _fetch_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    request_headers = {"accept-encoding": "identity", **(headers or {})}
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=20) as response:
            text = response.read().decode(response.headers.get_content_charset("utf-8"), errors="replace")
            status = getattr(response, "status", 200)
            if status >= 400:
                raise XFetchError(f"Request failed ({status}) for {url}: {text[:200]}")
            return text
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise XFetchError(f"Request failed ({exc.code}) for {url}: {body[:200]}") from exc


@lru_cache(maxsize=4)
def _fetch_x_home_html(user_agent: str) -> str:
    return _fetch_text("https://x.com", headers={"user-agent": user_agent})


def _parse_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.replace('"', "").strip() for item in raw.split(",") if item.strip()]


def _resolve_feature_value(html: str, key: str) -> bool | None:
    key_pattern = re.escape(key)
    unescaped = re.search(rf'"{key_pattern}"\s*:\s*\{{"value"\s*:\s*(true|false)', html)
    escaped = re.search(rf'\\"{key_pattern}\\"\s*:\s*\\\{{\\"value\\"\s*:\s*(true|false)', html)
    match = unescaped or escaped
    if match is None:
        return None
    return match.group(1) == "true"


def _build_feature_map(
    html: str,
    keys: list[str],
    *,
    defaults: dict[str, bool] | None = None,
) -> dict[str, bool]:
    features: dict[str, bool] = {}
    for key in keys:
        value = _resolve_feature_value(html, key)
        if value is not None:
            features[key] = value
        elif defaults and key in defaults:
            features[key] = bool(defaults[key])
        else:
            features[key] = True
    features.setdefault("responsive_web_graphql_exclude_directive_enabled", True)
    return features


def _build_field_toggle_map(keys: list[str]) -> dict[str, bool]:
    return {key: True for key in keys}


def _build_tweet_field_toggle_map(keys: list[str]) -> dict[str, bool]:
    toggles: dict[str, bool] = {}
    for key in keys:
        toggles[key] = key not in {"withGrokAnalyze", "withDisallowedReplyControls"}
    return toggles


@lru_cache(maxsize=4)
def _resolve_tweet_query_info(user_agent: str) -> tuple[str, list[str], list[str], str]:
    html = _fetch_x_home_html(user_agent)
    main_hash_match = re.search(r"main\\.([a-z0-9]+)\\.js", html)
    if main_hash_match is None:
        return FALLBACK_TWEET_QUERY_ID, FALLBACK_TWEET_FEATURE_SWITCHES, FALLBACK_TWEET_FIELD_TOGGLES, html

    chunk = _fetch_text(
        f"https://abs.twimg.com/responsive-web/client-web/main.{main_hash_match.group(1)}.js",
        headers={"user-agent": user_agent},
    )
    query_id_match = re.search(r'queryId:"([^"]+)",operationName:"TweetResultByRestId"', chunk)
    feature_match = re.search(
        r'operationName:"TweetResultByRestId"[\s\S]*?featureSwitches:\[(.*?)\]',
        chunk,
    )
    field_toggle_match = re.search(
        r'operationName:"TweetResultByRestId"[\s\S]*?fieldToggles:\[(.*?)\]',
        chunk,
    )
    feature_switches = _parse_string_list(feature_match.group(1) if feature_match else None)
    field_toggles = _parse_string_list(field_toggle_match.group(1) if field_toggle_match else None)
    return (
        query_id_match.group(1) if query_id_match else FALLBACK_TWEET_QUERY_ID,
        feature_switches or FALLBACK_TWEET_FEATURE_SWITCHES,
        field_toggles or FALLBACK_TWEET_FIELD_TOGGLES,
        html,
    )


@lru_cache(maxsize=4)
def _resolve_article_query_info(user_agent: str) -> tuple[str, list[str], list[str], str]:
    html = _fetch_x_home_html(user_agent)
    bundle_match = re.search(r'"bundle\\.TwitterArticles":"([a-z0-9]+)"', html)
    if bundle_match is None:
        return FALLBACK_ARTICLE_QUERY_ID, FALLBACK_ARTICLE_FEATURE_SWITCHES, FALLBACK_ARTICLE_FIELD_TOGGLES, html

    chunk = _fetch_text(
        f"https://abs.twimg.com/responsive-web/client-web/bundle.TwitterArticles.{bundle_match.group(1)}a.js",
        headers={"user-agent": user_agent},
    )
    query_id_match = re.search(r'queryId:"([^"]+)",operationName:"ArticleEntityResultByRestId"', chunk)
    feature_match = re.search(
        r'operationName:"ArticleEntityResultByRestId"[\s\S]*?featureSwitches:\[(.*?)\]',
        chunk,
    )
    field_toggle_match = re.search(
        r'operationName:"ArticleEntityResultByRestId"[\s\S]*?fieldToggles:\[(.*?)\]',
        chunk,
    )
    feature_switches = _parse_string_list(feature_match.group(1) if feature_match else None)
    field_toggles = _parse_string_list(field_toggle_match.group(1) if field_toggle_match else None)
    return (
        query_id_match.group(1) if query_id_match else FALLBACK_ARTICLE_QUERY_ID,
        feature_switches or FALLBACK_ARTICLE_FEATURE_SWITCHES,
        field_toggles or FALLBACK_ARTICLE_FIELD_TOGGLES,
        html,
    )


def _resolve_cookie_domain(cookie: dict[str, Any]) -> str | None:
    raw_domain = str(cookie.get("domain") or "").strip()
    if raw_domain:
        return raw_domain[1:] if raw_domain.startswith(".") else raw_domain
    raw_url = str(cookie.get("url") or "").strip()
    if not raw_url:
        return None
    try:
        return urlparse(raw_url).hostname
    except Exception:
        return None


def _pick_cookie_value(cookies: list[dict[str, Any]], name: str) -> str | None:
    matches = [cookie for cookie in cookies if cookie.get("name") == name and isinstance(cookie.get("value"), str)]
    if not matches:
        return None

    def _matches(cookie: dict[str, Any], *, domain_suffix: str | None = None, exact_x_root: bool = False) -> bool:
        domain = _resolve_cookie_domain(cookie) or ""
        if exact_x_root:
            return domain == "x.com" and str(cookie.get("path") or "/") == "/"
        if domain_suffix is None:
            return False
        return domain.endswith(domain_suffix)

    preferred = next((cookie for cookie in matches if _matches(cookie, exact_x_root=True)), None)
    x_domain = next((cookie for cookie in matches if _matches(cookie, domain_suffix="x.com")), None)
    twitter_domain = next((cookie for cookie in matches if _matches(cookie, domain_suffix="twitter.com")), None)
    chosen = preferred or x_domain or twitter_domain or matches[0]
    value = chosen.get("value")
    return str(value) if isinstance(value, str) else None


def _load_x_graphql_cookie_map(storage_state: str | Path | dict[str, Any] | None) -> dict[str, str]:
    if storage_state is None:
        return {}

    if isinstance(storage_state, dict):
        if "cookies" in storage_state and isinstance(storage_state.get("cookies"), list):
            cookie_items = [cookie for cookie in storage_state.get("cookies", []) if isinstance(cookie, dict)]
        else:
            return {
                name: str(value)
                for name, value in storage_state.items()
                if name in X_GRAPHQL_COOKIE_NAMES and isinstance(value, str) and value
            }
    else:
        path = Path(storage_state)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        cookie_items = [cookie for cookie in payload.get("cookies", []) if isinstance(cookie, dict)]

    cookie_map: dict[str, str] = {}
    for name in X_GRAPHQL_COOKIE_NAMES:
        value = _pick_cookie_value(cookie_items, name)
        if value:
            cookie_map[name] = value
    return cookie_map


def _has_required_x_graphql_cookies(cookie_map: dict[str, str]) -> bool:
    return all(cookie_map.get(name) for name in X_GRAPHQL_REQUIRED_COOKIE_NAMES)


def _build_x_graphql_headers(cookie_map: dict[str, str], *, user_agent: str, bearer_token: str) -> dict[str, str]:
    headers = {
        "authorization": bearer_token,
        "user-agent": user_agent,
        "accept": "application/json",
        "accept-language": "en",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
    }
    if cookie_map.get("auth_token"):
        headers["x-twitter-auth-type"] = "OAuth2Session"
    # 无登录时可使用 guest token（通常在 cookie `gt` 中）。
    if cookie_map.get("gt") and not cookie_map.get("auth_token"):
        headers["x-guest-token"] = cookie_map["gt"]
    if cookie_map:
        headers["cookie"] = "; ".join(f"{name}={value}" for name, value in cookie_map.items() if value)
    if cookie_map.get("ct0"):
        headers["x-csrf-token"] = cookie_map["ct0"]
    client_transaction_id = os.environ.get("X_CLIENT_TRANSACTION_ID", "").strip()
    if client_transaction_id:
        headers["x-client-transaction-id"] = client_transaction_id
    return headers


def _fetch_x_graphql_json(url: str, *, headers: dict[str, str]) -> Any:
    request = Request(url, headers={"accept-encoding": "identity", **headers})
    try:
        with urlopen(request, timeout=20) as response:
            text = response.read().decode(response.headers.get_content_charset("utf-8"), errors="replace")
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise XFetchError(f"X API error ({exc.code}): {text[:400]}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise XFetchError(f"Failed to parse response JSON: {exc}") from exc


def _post_x_graphql_json(url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> Any:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"accept-encoding": "identity", "content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            text = response.read().decode(response.headers.get_content_charset("utf-8"), errors="replace")
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise XFetchError(f"X API error ({exc.code}): {text[:400]}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise XFetchError(f"Failed to parse response JSON: {exc}") from exc


@lru_cache(maxsize=4)
def _activate_x_guest_token(*, user_agent: str, bearer_token: str) -> str:
    """获取 X guest token（无需登录）。

    X 的 GraphQL SearchTimeline 在部分地区/环境允许 guest token 访问；
    推荐流 HomeTimeline 则仍然需要登录态。
    """

    for endpoint in X_GUEST_ACTIVATE_ENDPOINTS:
        request = Request(
            endpoint,
            headers={
                "accept-encoding": "identity",
                "authorization": bearer_token,
                "user-agent": user_agent,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                text = response.read().decode(response.headers.get_content_charset("utf-8"), errors="replace")
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            # 换下一个 endpoint
            continue

        try:
            payload = json.loads(text)
        except Exception:
            continue

        token = payload.get("guest_token") if isinstance(payload, dict) else None
        if isinstance(token, str) and token.strip():
            return token.strip()

    raise XFetchError("Failed to activate X guest token")


def _ensure_x_guest_cookie_map(storage_state: str | Path | dict[str, Any] | None) -> dict[str, str]:
    """确保返回至少包含 `gt` 的 cookie_map（不包含敏感值日志）。"""

    cookie_map = _load_x_graphql_cookie_map(storage_state)
    if cookie_map.get("gt"):
        return cookie_map

    user_agent = (os.environ.get("X_USER_AGENT") or DEFAULT_X_USER_AGENT).strip()
    bearer_token = (os.environ.get("X_BEARER_TOKEN") or DEFAULT_X_BEARER_TOKEN).strip()
    guest_token = _activate_x_guest_token(user_agent=user_agent, bearer_token=bearer_token)
    cookie_map = {**cookie_map, "gt": guest_token}
    return cookie_map


def _raise_if_graphql_payload_has_errors(payload: Any, *, operation: str) -> None:
    if not isinstance(payload, dict):
        return
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return
    first = errors[0]
    if isinstance(first, dict):
        message = str(first.get("message") or first.get("code") or first)[:240]
    else:
        message = str(first)[:240]
    raise XFetchError(f"X GraphQL returned errors for {operation}: {message}")


@lru_cache(maxsize=4)
def _resolve_main_chunk_path(user_agent: str) -> str | None:
    html = _fetch_x_home_html(user_agent)
    matches = re.findall(r'client-web/[^"\']*main[^"\']*\.js', html)
    return matches[0] if matches else None


@lru_cache(maxsize=16)
def _resolve_graphql_operation_query_id(operation_name: str, fallback_query_id: str, user_agent: str) -> str:
    main_chunk_path = _resolve_main_chunk_path(user_agent)
    if not main_chunk_path:
        return fallback_query_id
    chunk = _fetch_text(f"https://abs.twimg.com/responsive-web/{main_chunk_path.split('responsive-web/')[-1]}", headers={"user-agent": user_agent})
    match = re.search(rf'queryId:"([^\"]+)",operationName:"{re.escape(operation_name)}"', chunk)
    return match.group(1) if match else fallback_query_id


def _fetch_tweet_result_graphql(
    tweet_id: str,
    cookie_map: dict[str, str],
    *,
    user_agent: str | None = None,
    bearer_token: str | None = None,
) -> Any:
    resolved_user_agent = (user_agent or os.environ.get("X_USER_AGENT") or DEFAULT_X_USER_AGENT).strip()
    resolved_bearer_token = (bearer_token or os.environ.get("X_BEARER_TOKEN") or DEFAULT_X_BEARER_TOKEN).strip()
    query_id, feature_switches, field_toggles, html = _resolve_tweet_query_info(resolved_user_agent)
    query_params = {
        "variables": json.dumps(
            {
                "tweetId": tweet_id,
                "withCommunity": False,
                "includePromotedContent": False,
                "withVoice": True,
            },
            separators=(",", ":"),
        ),
        "features": json.dumps(_build_feature_map(html, feature_switches), separators=(",", ":")),
        "fieldToggles": json.dumps(_build_tweet_field_toggle_map(field_toggles), separators=(",", ":")),
    }
    url = f"https://x.com/i/api/graphql/{query_id}/TweetResultByRestId?{urlencode(query_params)}"
    return _fetch_x_graphql_json(
        url,
        headers=_build_x_graphql_headers(cookie_map, user_agent=resolved_user_agent, bearer_token=resolved_bearer_token),
    )


def _fetch_article_entity_by_id_graphql(
    article_entity_id: str,
    cookie_map: dict[str, str],
    *,
    user_agent: str | None = None,
    bearer_token: str | None = None,
) -> Any:
    resolved_user_agent = (user_agent or os.environ.get("X_USER_AGENT") or DEFAULT_X_USER_AGENT).strip()
    resolved_bearer_token = (bearer_token or os.environ.get("X_BEARER_TOKEN") or DEFAULT_X_BEARER_TOKEN).strip()
    query_id, feature_switches, field_toggles, html = _resolve_article_query_info(resolved_user_agent)
    query_params = {
        "variables": json.dumps({"articleEntityId": article_entity_id}, separators=(",", ":")),
        "features": json.dumps(_build_feature_map(html, feature_switches), separators=(",", ":")),
        "fieldToggles": json.dumps(_build_field_toggle_map(field_toggles), separators=(",", ":")),
    }
    url = f"https://x.com/i/api/graphql/{query_id}/ArticleEntityResultByRestId?{urlencode(query_params)}"
    return _fetch_x_graphql_json(
        url,
        headers=_build_x_graphql_headers(cookie_map, user_agent=resolved_user_agent, bearer_token=resolved_bearer_token),
    )


def _unwrap_tweet_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults" and isinstance(result.get("tweet"), dict):
        return result.get("tweet")
    return result


def _extract_tweet_from_payload(payload: Any) -> dict[str, Any] | None:
    root = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(root, dict):
        return None
    result = (
        root.get("tweetResult", {}).get("result")
        or root.get("tweet_result", {}).get("result")
        or root.get("tweet_result")
    )
    return _unwrap_tweet_result(result)


def _extract_article_entity_from_tweet(tweet: dict[str, Any]) -> Any:
    return (
        tweet.get("article", {}).get("article_results", {}).get("result")
        or tweet.get("article", {}).get("result")
        or tweet.get("legacy", {}).get("article", {}).get("article_results", {}).get("result")
        or tweet.get("legacy", {}).get("article", {}).get("result")
        or tweet.get("article_results", {}).get("result")
    )


def _coerce_article_entity(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if any(isinstance(value.get(key), str) and value.get(key).strip() for key in ("title", "plain_text", "preview_text")):
        return value
    if isinstance(value.get("content_state"), dict):
        return value
    return None


def _has_article_content(article: dict[str, Any]) -> bool:
    blocks = article.get("content_state", {}).get("blocks")
    if isinstance(blocks, list) and any(isinstance(block, dict) for block in blocks):
        return True
    return any(isinstance(article.get(key), str) and article.get(key).strip() for key in ("plain_text", "preview_text"))


def _parse_article_id_from_url(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    match = re.search(r"/(?:i/)?article/(\d+)", parsed.path)
    return match.group(1) if match else None


def _extract_article_url_from_url_entities(urls: Any) -> str | None:
    if not isinstance(urls, list):
        return None
    for url_entity in urls:
        if not isinstance(url_entity, dict):
            continue
        candidate = url_entity.get("expanded_url") or url_entity.get("url")
        if not candidate and url_entity.get("display_url"):
            candidate = f"https://{url_entity['display_url']}"
        if isinstance(candidate, str) and _parse_article_id_from_url(candidate):
            return candidate
    return None


def _extract_article_id_from_tweet(tweet: dict[str, Any]) -> str | None:
    embedded = _extract_article_entity_from_tweet(tweet)
    if isinstance(embedded, dict) and isinstance(embedded.get("rest_id"), str) and embedded.get("rest_id"):
        return str(embedded["rest_id"])
    note_urls = (
        tweet.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("entity_set", {})
        .get("urls")
    )
    legacy_urls = tweet.get("legacy", {}).get("entities", {}).get("urls")
    return _parse_article_id_from_url(_extract_article_url_from_url_entities(note_urls)) or _parse_article_id_from_url(
        _extract_article_url_from_url_entities(legacy_urls)
    )


def _extract_article_original_url_from_tweet(tweet: dict[str, Any], article_id: str, username: str | None) -> str:
    note_urls = (
        tweet.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("entity_set", {})
        .get("urls")
    )
    legacy_urls = tweet.get("legacy", {}).get("entities", {}).get("urls")
    extracted = _extract_article_url_from_url_entities(note_urls) or _extract_article_url_from_url_entities(legacy_urls)
    if isinstance(extracted, str) and extracted:
        return extracted
    if username:
        return f"https://x.com/{username}/article/{article_id}"
    return f"https://x.com/i/article/{article_id}"


def _extract_tweet_username(tweet: dict[str, Any]) -> str | None:
    user = tweet.get("core", {}).get("user_results", {}).get("result")
    if isinstance(user, dict):
        legacy = user.get("legacy")
        if isinstance(legacy, dict) and isinstance(legacy.get("screen_name"), str) and legacy.get("screen_name"):
            return str(legacy["screen_name"])
        if isinstance(user.get("screen_name"), str) and user.get("screen_name"):
            return str(user["screen_name"])
    return None


def _extract_article_title_and_body_from_entity(article: dict[str, Any]) -> tuple[str, str]:
    title = str(article.get("title") or "").strip()
    plain_text = str(article.get("plain_text") or "").strip()
    preview_text = str(article.get("preview_text") or "").strip()

    blocks = article.get("content_state", {}).get("blocks")
    entity_map = article.get("content_state", {}).get("entityMap")
    if isinstance(blocks, list):
        body = _render_article_content_state(blocks, entity_map)
        if body:
            return title, body

    if plain_text:
        return title, plain_text
    return title, preview_text


def _render_article_content_state(blocks: list[Any], entity_map: Any) -> str:
    lines: list[str] = []
    previous_kind: str | None = None
    list_kind: str | None = None
    ordered_index = 0
    in_code_block = False

    def push_block(block_lines: list[str], kind: str) -> None:
        nonlocal previous_kind
        normalized = [line.rstrip() for line in block_lines]
        if not normalized:
            return
        if lines and previous_kind and not (previous_kind == kind and kind in {"list", "quote", "media"}):
            lines.append("")
        lines.extend(normalized)
        previous_kind = kind

    def collect_atomic_markdown(block: dict[str, Any]) -> list[str]:
        rendered: list[str] = []
        for entity_value in _iter_block_entity_values(block, entity_map):
            if not isinstance(entity_value, dict):
                continue
            entity_type = str(entity_value.get("type") or "").upper()
            if entity_type != "MARKDOWN":
                continue
            markdown = entity_value.get("data", {}).get("markdown")
            if isinstance(markdown, str) and markdown.strip():
                rendered.extend(markdown.strip().splitlines())
        return rendered

    for raw_block in blocks:
        if not isinstance(raw_block, dict):
            continue

        block_type = str(raw_block.get("type") or "unstyled")
        text = str(raw_block.get("text") or "")

        if block_type == "code-block":
            if not in_code_block:
                if lines:
                    lines.append("")
                lines.append("```")
                in_code_block = True
            lines.append(text.rstrip())
            previous_kind = "code"
            list_kind = None
            ordered_index = 0
            continue

        if in_code_block:
            lines.append("```")
            in_code_block = False
            previous_kind = "code"

        if block_type == "atomic":
            list_kind = None
            ordered_index = 0
            markdown_lines = collect_atomic_markdown(raw_block)
            if markdown_lines:
                push_block(markdown_lines, "text")
            continue

        stripped_text = text.strip()
        if not stripped_text:
            list_kind = None
            ordered_index = 0
            continue

        if block_type == "unordered-list-item":
            list_kind = "unordered"
            ordered_index = 0
            push_block([f"- {stripped_text}"], "list")
            continue

        if block_type == "ordered-list-item":
            if list_kind != "ordered":
                ordered_index = 0
            list_kind = "ordered"
            ordered_index += 1
            push_block([f"{ordered_index}. {stripped_text}"], "list")
            continue

        list_kind = None
        ordered_index = 0

        if block_type == "header-one":
            push_block([f"# {stripped_text}"], "heading")
            continue
        if block_type == "header-two":
            push_block([f"## {stripped_text}"], "heading")
            continue
        if block_type == "header-three":
            push_block([f"### {stripped_text}"], "heading")
            continue
        if block_type == "header-four":
            push_block([f"#### {stripped_text}"], "heading")
            continue
        if block_type == "header-five":
            push_block([f"##### {stripped_text}"], "heading")
            continue
        if block_type == "header-six":
            push_block([f"###### {stripped_text}"], "heading")
            continue
        if block_type == "blockquote":
            push_block([f"> {line}" for line in stripped_text.splitlines()], "quote")
            continue

        push_block([stripped_text], "text")

    if in_code_block:
        lines.append("```")

    return "\n".join(lines).strip()


def _iter_block_entity_values(block: dict[str, Any], entity_map: Any) -> list[dict[str, Any]]:
    if not isinstance(entity_map, dict):
        return []

    values: list[dict[str, Any]] = []
    ranges = block.get("entityRanges")
    if not isinstance(ranges, list):
        return values

    for raw_range in ranges:
        if not isinstance(raw_range, dict):
            continue
        key = raw_range.get("key")
        if isinstance(key, int):
            lookup_keys = [str(key), key]
        else:
            lookup_keys = [key]
        entry = None
        for lookup_key in lookup_keys:
            if lookup_key in entity_map:
                entry = entity_map[lookup_key]
                break
        if not isinstance(entry, dict):
            continue
        value = entry.get("value") if isinstance(entry.get("value"), dict) else entry
        if isinstance(value, dict):
            values.append(value)

    return values


def _extract_article_entity_from_payload(payload: Any) -> dict[str, Any] | None:
    root = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(root, dict):
        return None
    result = (
        root.get("article_result_by_rest_id", {}).get("result")
        or root.get("article_result_by_rest_id")
        or root.get("article_entity_result", {}).get("result")
    )
    return result if isinstance(result, dict) else None


def _resolve_article_entity_from_tweet_graphql(tweet: dict[str, Any], cookie_map: dict[str, str]) -> dict[str, Any] | None:
    embedded = _coerce_article_entity(_extract_article_entity_from_tweet(tweet))
    if embedded and _has_article_content(embedded):
        return embedded

    article_id = _extract_article_id_from_tweet(tweet)
    if not article_id:
        return embedded

    try:
        fetched_payload = _fetch_article_entity_by_id_graphql(article_id, cookie_map)
    except Exception:
        return embedded

    fetched_entity = _coerce_article_entity(_extract_article_entity_from_payload(fetched_payload))
    return fetched_entity or embedded


def _extract_tweet_id_from_status_url(status_url: str) -> str | None:
    try:
        parsed = urlparse(status_url)
    except Exception:
        return None
    match = re.search(r"/status/(\d+)", parsed.path)
    return match.group(1) if match else None


def _resolve_graphql_candidate_from_status_url(
    status_url: str,
    *,
    cookie_map: dict[str, str],
    likes: int,
    tweet_text: str,
    reason: str,
) -> dict[str, Any] | None:
    if not _has_required_x_graphql_cookies(cookie_map):
        return None

    tweet_id = _extract_tweet_id_from_status_url(status_url)
    if not tweet_id:
        return None

    try:
        payload = _fetch_tweet_result_graphql(tweet_id, cookie_map)
    except Exception:
        return None

    tweet = _extract_tweet_from_payload(payload)
    if tweet is None:
        return None

    article = _resolve_article_entity_from_tweet_graphql(tweet, cookie_map)
    if article is None:
        return None

    article_id = str(article.get("rest_id") or _extract_article_id_from_tweet(tweet) or "").strip()
    if not article_id:
        return None

    title, body = _extract_article_title_and_body_from_entity(article)
    if _is_probably_chinese_article_text(title, body) or not _article_text_meets_min_length(title, body):
        return None

    username = _extract_tweet_username(tweet)
    canonical_url = f"https://x.com/i/article/{article_id}"
    original_url = _extract_article_original_url_from_tweet(tweet, article_id, username)
    return {
        "canonical_url": canonical_url,
        "original_url": original_url,
        "likes": int(likes),
        "tweet_text": tweet_text,
        "score": float(likes),
        "reason": reason,
    }


def _extract_timeline_tweets_from_payload(payload: Any) -> list[dict[str, Any]]:
    tweets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            tweet_results = node.get("tweet_results")
            if isinstance(tweet_results, dict):
                tweet = _unwrap_tweet_result(tweet_results.get("result"))
                if isinstance(tweet, dict):
                    rest_id = str(tweet.get("rest_id") or tweet.get("legacy", {}).get("id_str") or "").strip()
                    if rest_id and rest_id not in seen:
                        seen.add(rest_id)
                        tweets.append(tweet)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return tweets


def _extract_tweet_text_from_graphql_tweet(tweet: dict[str, Any]) -> str:
    note_text = (
        tweet.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("text")
    )
    if isinstance(note_text, str) and note_text.strip():
        return note_text.strip()
    full_text = tweet.get("legacy", {}).get("full_text")
    if isinstance(full_text, str) and full_text.strip():
        return full_text.strip()
    return ""


def _build_graphql_candidate_from_tweet(
    tweet: dict[str, Any],
    *,
    cookie_map: dict[str, str],
    min_likes: int,
    keyword_patterns: list[re.Pattern[str]],
    reason: str,
) -> dict[str, Any] | None:
    likes = int(tweet.get("legacy", {}).get("favorite_count") or 0)
    if likes < int(min_likes):
        return None

    tweet_text = _extract_tweet_text_from_graphql_tweet(tweet)
    article = _resolve_article_entity_from_tweet_graphql(tweet, cookie_map)
    if article is None:
        return None

    article_id = str(article.get("rest_id") or _extract_article_id_from_tweet(tweet) or "").strip()
    if not article_id:
        return None

    title, body = _extract_article_title_and_body_from_entity(article)
    if _is_probably_chinese_article_text(title, body) or not _article_text_meets_min_length(title, body):
        return None

    if keyword_patterns:
        searchable_text = "\n".join(part for part in (tweet_text, title, body) if part).strip()
        if not searchable_text or not any(pattern.search(searchable_text) for pattern in keyword_patterns):
            return None

    username = _extract_tweet_username(tweet)
    return {
        "canonical_url": f"https://x.com/i/article/{article_id}",
        "original_url": _extract_article_original_url_from_tweet(tweet, article_id, username),
        "likes": likes,
        "tweet_text": tweet_text,
        "score": float(likes),
        "reason": reason,
    }


def _discover_article_candidates_from_timeline_payload(
    payload: Any,
    *,
    cookie_map: dict[str, str],
    max_candidates: int,
    min_likes: int,
    required_keywords: list[str] | None,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    keyword_patterns = [re.compile(re.escape(keyword), re.IGNORECASE) for keyword in (required_keywords or []) if keyword.strip()]
    tweets = _extract_timeline_tweets_from_payload(payload)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_hits = 0
    after_likes_filter = 0
    after_article_entity = 0
    after_language_length_filter = 0
    after_keywords_filter = 0
    duplicate_filtered = 0

    for tweet in tweets:
        likes = int(tweet.get("legacy", {}).get("favorite_count") or 0)
        if likes < int(min_likes):
            continue
        after_likes_filter += 1

        tweet_text = _extract_tweet_text_from_graphql_tweet(tweet)
        article = _resolve_article_entity_from_tweet_graphql(tweet, cookie_map)
        if article is None:
            continue

        after_article_entity += 1

        title, body = _extract_article_title_and_body_from_entity(article)
        if _is_probably_chinese_article_text(title, body) or not _article_text_meets_min_length(title, body):
            continue
        after_language_length_filter += 1

        searchable_text = "\n".join(part for part in (tweet_text, title, body) if part).strip()
        if keyword_patterns and (not searchable_text or not any(pattern.search(searchable_text) for pattern in keyword_patterns)):
            continue
        after_keywords_filter += 1
        raw_hits += 1

        candidate = _build_graphql_candidate_from_tweet(
            tweet,
            cookie_map=cookie_map,
            min_likes=min_likes,
            keyword_patterns=[],
            reason="search_like_threshold",
        )
        if candidate is None:
            continue

        canonical = str(candidate.get("canonical_url") or "").strip()
        if not canonical or canonical in seen:
            if canonical and canonical in seen:
                duplicate_filtered += 1
            continue
        seen.add(canonical)
        results.append(candidate)
        if len(results) >= int(max_candidates):
            break

    if progress_callback is not None:
        try:
            progress_event = _build_search_progress_event(
                scroll_index=0,
                max_scrolls=0,
                tweet_count=len(tweets),
                raw_hits=raw_hits,
                after_likes_filter=after_likes_filter,
                after_keywords_filter=after_keywords_filter,
                after_article_entity=after_article_entity,
                after_article_url_extract=0,
                after_language_length_filter=after_language_length_filter,
                duplicate_filtered=duplicate_filtered,
                deduped_hits=len(results),
            )
            progress_callback(progress_event)
            suspected_reason = progress_event.get("suspected_reason")
            if suspected_reason is not None:
                progress_callback({"type": "hint", "suspected_reason": suspected_reason})
        except Exception:
            pass

    return results


def _discover_article_candidates_from_search_graphql(
    query: str,
    *,
    storage_state: str | Path | dict[str, Any] | None,
    search_mode: str,
    max_candidates: int,
    min_likes: int,
    required_keywords: list[str] | None,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    # SearchTimeline 允许 guest token（无需登录）；优先使用登录 cookie，其次尝试 guest token。
    cookie_map = _load_x_graphql_cookie_map(storage_state)
    if not _has_required_x_graphql_cookies(cookie_map):
        try:
            cookie_map = _ensure_x_guest_cookie_map(storage_state)
        except Exception as exc:
            if progress_callback is not None:
                try:
                    reason, detail = _classify_x_graphql_failure(exc)
                    progress_callback(
                        {
                            "type": "hint",
                            "suspected_reason": reason,
                            "detail": detail,
                        }
                    )
                except Exception:
                    pass
            return []

    user_agent = (os.environ.get("X_USER_AGENT") or DEFAULT_X_USER_AGENT).strip()
    bearer_token = (os.environ.get("X_BEARER_TOKEN") or DEFAULT_X_BEARER_TOKEN).strip()
    query_id = _resolve_graphql_operation_query_id("SearchTimeline", FALLBACK_SEARCH_TIMELINE_QUERY_ID, user_agent)
    if progress_callback is not None:
        try:
            mode_param = "live" if (search_mode or "top").lower() in {"latest", "live"} else "top"
            progress_callback({
                "type": "page",
                "page_url": f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f={mode_param}",
                "page_title": None,
            })
        except Exception:
            pass

    if progress_callback is not None:
        try:
            progress_callback(
                {
                    "type": "graphql_request",
                    "operation": "SearchTimeline",
                    "url": f"https://x.com/i/api/graphql/{query_id}/SearchTimeline",
                    "query_id": query_id,
                    "has_auth_token": bool(cookie_map.get("auth_token")),
                    "has_ct0": bool(cookie_map.get("ct0")),
                    "has_guest_token": bool(cookie_map.get("gt")),
                }
            )
        except Exception:
            pass

    payload = _post_x_graphql_json(
        f"https://x.com/i/api/graphql/{query_id}/SearchTimeline",
        headers=_build_x_graphql_headers(cookie_map, user_agent=user_agent, bearer_token=bearer_token),
        payload={
            "variables": {
                "rawQuery": query,
                "count": max(20, int(max_candidates) * 4),
                "querySource": "typed_query",
                "product": "Latest" if (search_mode or "top").lower() in {"latest", "live"} else "Top",
            },
            "features": {"responsive_web_graphql_exclude_directive_enabled": True},
        },
    )
    _raise_if_graphql_payload_has_errors(payload, operation="SearchTimeline")

    if progress_callback is not None:
        try:
            progress_callback(
                {
                    "type": "graphql_response",
                    "operation": "SearchTimeline",
                    "ok": True,
                    "has_data": isinstance(payload, dict) and isinstance(payload.get("data"), dict),
                    "has_errors": isinstance(payload, dict) and bool(payload.get("errors")),
                    "top_level_keys": list(payload.keys())[:10] if isinstance(payload, dict) else [],
                }
            )
        except Exception:
            pass
    return _discover_article_candidates_from_timeline_payload(
        payload,
        cookie_map=cookie_map,
        max_candidates=max_candidates,
        min_likes=min_likes,
        required_keywords=required_keywords,
        progress_callback=progress_callback,
    )


def _discover_article_candidates_from_home_timeline_graphql(
    *,
    storage_state: str | Path | dict[str, Any] | None,
    max_candidates: int,
    min_likes: int,
    required_keywords: list[str] | None,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    cookie_map = _load_x_graphql_cookie_map(storage_state)
    if not _has_required_x_graphql_cookies(cookie_map):
        return []

    user_agent = (os.environ.get("X_USER_AGENT") or DEFAULT_X_USER_AGENT).strip()
    bearer_token = (os.environ.get("X_BEARER_TOKEN") or DEFAULT_X_BEARER_TOKEN).strip()
    query_id = _resolve_graphql_operation_query_id("HomeTimeline", FALLBACK_HOME_TIMELINE_QUERY_ID, user_agent)
    if progress_callback is not None:
        try:
            progress_callback({"type": "page", "page_url": "https://x.com/home", "page_title": None})
        except Exception:
            pass

    variables = {
        "count": max(20, int(max_candidates) * 4),
        "seenTweetIds": [],
        "includePromotedContent": False,
        "latestControlAvailable": True,
    }
    features = {"responsive_web_graphql_exclude_directive_enabled": True}
    params = {
        "variables": json.dumps(
            variables,
            separators=(",", ":"),
        ),
        "features": json.dumps(features, separators=(",", ":")),
    }
    url = f"https://x.com/i/api/graphql/{query_id}/HomeTimeline?{urlencode(params)}"
    headers = _build_x_graphql_headers(cookie_map, user_agent=user_agent, bearer_token=bearer_token)

    if progress_callback is not None:
        try:
            progress_callback(
                {
                    "type": "graphql_request",
                    "operation": "HomeTimeline",
                    "url": url,
                    "query_id": query_id,
                    "has_auth_token": bool(cookie_map.get("auth_token")),
                    "has_ct0": bool(cookie_map.get("ct0")),
                    "has_twid": bool(cookie_map.get("twid")),
                    "has_gt": bool(cookie_map.get("gt")),
                    "has_client_transaction_id": bool(os.environ.get("X_CLIENT_TRANSACTION_ID", "").strip()),
                }
            )
        except Exception:
            pass

    def _fetch_once(target_url: str) -> Any:
        payload = _fetch_x_graphql_json(target_url, headers=headers)
        _raise_if_graphql_payload_has_errors(payload, operation="HomeTimeline")
        return payload

    try:
        payload = _fetch_once(url)
    except Exception as exc:
        # queryId 偶尔会失效：遇到 400/404 等明显协议级错误时，尝试强制刷新 queryId 重试一次。
        should_retry = False
        if isinstance(exc, XFetchError):
            msg = str(exc).lower()
            if any(token in msg for token in ("(400)", "(404)", "bad request", "unknown operation", "operation", "not found")):
                should_retry = True
        if should_retry:
            try:
                _resolve_graphql_operation_query_id.cache_clear()
                refreshed = _resolve_graphql_operation_query_id("HomeTimeline", FALLBACK_HOME_TIMELINE_QUERY_ID, user_agent)
                refreshed_url = f"https://x.com/i/api/graphql/{refreshed}/HomeTimeline?{urlencode(params)}"
                if progress_callback is not None:
                    try:
                        progress_callback(
                            {
                                "type": "graphql_request",
                                "operation": "HomeTimeline",
                                "url": refreshed_url,
                                "query_id": refreshed,
                                "note": "retry_after_query_id_refresh",
                            }
                        )
                    except Exception:
                        pass
                payload = _fetch_once(refreshed_url)
            except Exception:
                payload = None
        else:
            payload = None

        if payload is None:
            if progress_callback is not None:
                try:
                    reason, detail = _classify_x_graphql_failure(exc)
                    progress_callback(
                        {
                            "type": "graphql_response",
                            "operation": "HomeTimeline",
                            "ok": False,
                            "suspected_reason": reason,
                            "detail": detail,
                        }
                    )
                except Exception:
                    pass
            raise

    if progress_callback is not None:
        try:
            progress_callback(
                {
                    "type": "graphql_response",
                    "operation": "HomeTimeline",
                    "ok": True,
                    "has_data": isinstance(payload, dict) and isinstance(payload.get("data"), dict),
                    "has_errors": isinstance(payload, dict) and bool(payload.get("errors")),
                    "top_level_keys": list(payload.keys())[:10] if isinstance(payload, dict) else [],
                }
            )
        except Exception:
            pass

    return _discover_article_candidates_from_timeline_payload(
        payload,
        cookie_map=cookie_map,
        max_candidates=max_candidates,
        min_likes=min_likes,
        required_keywords=required_keywords,
        progress_callback=progress_callback,
    )


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


_ARTICLE_HREF_PATTERN = re.compile(
    r"(?:(?:^|/)i/articles?/\d+)|(?:/[A-Za-z0-9_]{1,15}/article/\d+)"
)
_STATUS_HREF_PATTERN = re.compile(r"^/[A-Za-z0-9_]{1,15}/status/\d+(?:/|$)")
_CJK_CHARACTER_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
_LATIN_CHARACTER_PATTERN = re.compile(r"[A-Za-z]")
_JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30FF]")
_HANGUL_CHARACTER_PATTERN = re.compile(r"[\uAC00-\uD7AF]")


def _absolutize_x_href(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://x.com" + href
    return None


def _extract_article_url_from_hrefs(hrefs: list[str]) -> str | None:
    for href in hrefs:
        absolute = _absolutize_x_href(href)
        if not absolute or not _ARTICLE_HREF_PATTERN.search(href):
            continue
        if is_article_url(absolute):
            return absolute
    return None


def _extract_status_url_from_hrefs(hrefs: list[str]) -> str | None:
    for href in hrefs:
        if not href or not _STATUS_HREF_PATTERN.match(href):
            continue
        if href.endswith("/analytics"):
            continue
        absolute = _absolutize_x_href(href)
        if absolute:
            return absolute
    return None


def _resolve_article_url_from_status_page(context, status_url: str, cache: dict[str, str | None]) -> str | None:
    if status_url in cache:
        return cache[status_url]

    page = context.new_page()
    try:
        page.goto(status_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("a[href*='/article/'], a[href*='/i/article/'], a[href*='/i/articles/']", timeout=5000)
        except Exception:
            page.wait_for_timeout(1000)
        hrefs = []
        for anchor in page.query_selector_all("a[href]")[:200]:
            href = anchor.get_attribute("href") or ""
            if href:
                hrefs.append(href)
        resolved = _extract_article_url_from_hrefs(hrefs)
        cache[status_url] = resolved
        return resolved
    finally:
        page.close()


def _inner_text_or_empty(node) -> str:
    if node is None:
        return ""
    try:
        return (node.inner_text() or "").strip()
    except Exception:
        return ""


def _first_non_empty_selector_text(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            node = page.query_selector(selector)
        except Exception:
            node = None
        text = _inner_text_or_empty(node)
        if text:
            return text
    return ""


def _extract_article_title_and_body_from_page(page, article_url: str) -> tuple[str, str]:
    title = ""
    body = ""
    try:
        from packages.x_fetch.parser import parse_x_html

        parsed = parse_x_html(page.content(), article_url)
        title = parsed.title.strip()
        body = parsed.markdown.strip()
    except Exception:
        title = ""
        body = ""

    if title and body:
        return title, body

    if not title:
        title = _first_non_empty_selector_text(
            page,
            [
                "[data-testid='twitter-article-title']",
                "meta[property='og:title']",
            ],
        )
        if not title:
            try:
                title = (page.title() or "").strip()
            except Exception:
                title = ""

    if not body:
        body = _first_non_empty_selector_text(
            page,
            [
                "[data-testid='twitterArticleRichTextView']",
                "[data-testid='longformRichTextComponent']",
                "[data-testid='twitterArticleReadView']",
                "main",
                "body",
            ],
        )

    return title, body


def _is_probably_chinese_article_text(title: str, body: str) -> bool:
    sample = f"{title}\n{body}".strip()
    if not sample:
        return False

    cjk_count = len(_CJK_CHARACTER_PATTERN.findall(sample))
    if cjk_count < 12:
        return False

    latin_count = len(_LATIN_CHARACTER_PATTERN.findall(sample))
    if latin_count == 0:
        return True

    return cjk_count >= latin_count


def _article_text_meets_min_length(title: str, body: str, *, min_length: int = DISCOVERY_MIN_ARTICLE_LENGTH) -> bool:
    sample = body.strip() or title.strip()
    if not sample:
        return False

    normalized = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r" \1 ", sample)
    normalized = re.sub(r"\[([^\]]+)\]\([^)]*\)", r" \1 ", normalized)
    normalized = re.sub(r"https?://\S+", " ", normalized)

    cjk_units = len(_CJK_CHARACTER_PATTERN.findall(normalized))
    latin_units = len(_WORDLIKE_PATTERN.findall(normalized))
    return cjk_units + latin_units >= int(min_length)


def _is_non_chinese_article_url(
    context,
    article_url: str,
    cache: dict[str, bool],
) -> bool:
    canonical_url = normalize_x_url(article_url)
    cached = cache.get(canonical_url)
    if cached is not None:
        return cached

    page = context.new_page()
    try:
        page.goto(article_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                "article[data-testid='article'], [data-testid='twitterArticleRichTextView'], [data-testid='longformRichTextComponent']",
                timeout=5000,
            )
        except Exception:
            page.wait_for_timeout(1000)

        title, body = _extract_article_title_and_body_from_page(page, article_url)

        # 只保留“足够长且以英文为主”的文章。
        # 目标：排除中文/日文/韩文等，避免后续翻译质量不可控。
        sample = f"{title}\n{body}".strip()
        kana = len(_JAPANESE_KANA_PATTERN.findall(sample))
        hangul = len(_HANGUL_CHARACTER_PATTERN.findall(sample))
        latin_units = len(_WORDLIKE_PATTERN.findall(sample))
        cjk_units = len(_CJK_CHARACTER_PATTERN.findall(sample))

        is_probably_english = kana < 20 and hangul < 20 and latin_units >= 120 and cjk_units <= latin_units
        allowed = (
            is_probably_english
            and not _is_probably_chinese_article_text(title, body)
            and _article_text_meets_min_length(title, body)
        )
        cache[canonical_url] = allowed
        return allowed
    finally:
        page.close()


def _parse_compact_number(text: str) -> int | None:
    """解析 X 常见的点赞/转发数字格式。

    支持：
    - 123
    - 1,234
    - 1.2K / 3K / 0.8M
    - 1.2万 / 3万

    返回 None 表示无法解析。
    """

    normalized = text.strip().replace(",", "")
    if not normalized:
        return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*([KkMm万]?)", normalized)
    if not match:
        return None

    try:
        value = float(match.group(1))
    except ValueError:
        return None

    unit = match.group(2)
    if unit in {"K", "k"}:
        return int(value * 1000)
    if unit in {"M", "m"}:
        return int(value * 1_000_000)
    if unit == "万":
        return int(value * 10_000)
    return int(value)


def _extract_like_count_from_tweet_article(tweet_article) -> int | None:
    """从 tweet card DOM 中提取点赞数。

    依赖尽量少：优先按 data-testid=like/unlike 找 aria-label/text；
    若找不到则返回 None。
    """

    candidates = []
    try:
        candidates.extend(tweet_article.query_selector_all("[data-testid='like']"))
        candidates.extend(tweet_article.query_selector_all("[data-testid='unlike']"))
    except Exception:
        candidates = []

    for node in candidates:
        for attr in ("aria-label", "title"):
            try:
                value = (node.get_attribute(attr) or "").strip()
            except Exception:
                value = ""
            parsed = _parse_compact_number(value)
            if parsed is not None:
                return parsed

        # fallback to visible text
        try:
            text = (node.inner_text() or "").strip()
        except Exception:
            text = ""
        parsed = _parse_compact_number(text)
        if parsed is not None:
            return parsed

        # 有些结构会把数字放在子节点 span 里。
        try:
            span = node.query_selector("span")
        except Exception:
            span = None
        if span is not None:
            try:
                span_text = (span.inner_text() or "").strip()
            except Exception:
                span_text = ""
            parsed = _parse_compact_number(span_text)
            if parsed is not None:
                return parsed

    return None


def _extract_tweet_text(tweet_article) -> str:
    try:
        nodes = tweet_article.query_selector_all("div[data-testid='tweetText']")
    except Exception:
        nodes = []
    chunks: list[str] = []
    for node in nodes:
        try:
            text = (node.inner_text() or "").strip()
        except Exception:
            text = ""
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _guess_search_failure_reason(page) -> tuple[str, str | None, str | None]:
    try:
        page_title = (page.title() or "").strip()
    except Exception:
        page_title = ""

    try:
        page_url = str(getattr(page, "url", "") or "").strip()
    except Exception:
        page_url = ""
    try:
        body_text = (page.locator("body").inner_text(timeout=1000) or "").strip()
    except Exception:
        body_text = ""

    body_text_lower = body_text.lower()
    title_lower = page_title.lower()

    # 先用 URL 兜底：即使页面文案是中文/多语言，也能识别登录跳转。
    if page_url:
        lowered_url = page_url.lower()
        if "/i/flow/login" in lowered_url or lowered_url.endswith("/login") or "/login" in lowered_url:
            return "login_required", page_url, page_title or None

    login_tokens = {
        "sign in",
        "log in",
        "signup",
        "login",
        "join x",
        "create account",
        # 中文常见文案
        "登录",
        "登入",
        "注册",
        "创建账号",
        "加入 x",
        "加入x",
        "立即加入",
    }
    if any(token in body_text_lower or token in title_lower or token in body_text or token in page_title for token in login_tokens):
        return "login_required", page_url or getattr(page, "url", None), page_title or None

    rate_limit_tokens = {
        "rate limit",
        "something went wrong",
        "challenge",
        # 中文常见文案
        "出了点问题",
        "出错了",
        "请稍后再试",
        "验证",
        "挑战",
        "频率限制",
    }
    if any(token in body_text_lower or token in title_lower or token in body_text or token in page_title for token in rate_limit_tokens):
        return "rate_limited_or_challenged", page_url or getattr(page, "url", None), page_title or None
    if body_text:
        return "page_structure_unmatched", page_url or getattr(page, "url", None), page_title or None
    return "no_search_results", page_url or getattr(page, "url", None), page_title or None


def _build_search_progress_event(
    *,
    scroll_index: int,
    max_scrolls: int,
    tweet_count: int,
    raw_hits: int,
    after_likes_filter: int,
    after_keywords_filter: int,
    after_article_entity: int,
    after_article_url_extract: int,
    after_language_length_filter: int,
    duplicate_filtered: int,
    deduped_hits: int,
    sample: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_scroll = max(0, min(int(scroll_index), max(0, int(max_scrolls))))
    suspected_reason = None
    if raw_hits == 0:
        if tweet_count == 0:
            suspected_reason = "no_search_results"
        elif after_likes_filter == 0:
            suspected_reason = "filtered_by_min_likes"
        elif after_article_entity == 0:
            suspected_reason = "no_article_links_found"
        elif after_language_length_filter == 0:
            suspected_reason = "filtered_by_language_or_length"
        elif after_keywords_filter == 0 and after_likes_filter > 0:
            suspected_reason = "filtered_by_keywords"
    elif deduped_hits == 0:
        # raw_hits > 0 但没有任何返回：区分“没有 article”与“被语言/长度过滤”与“全是重复”。
        if (after_article_entity + after_article_url_extract) == 0:
            suspected_reason = "no_article_links_found"
        elif after_language_length_filter == 0:
            suspected_reason = "filtered_by_language_or_length"
        elif duplicate_filtered >= max(0, int(after_language_length_filter)):
            suspected_reason = "all_duplicates"
        else:
            suspected_reason = "no_article_links_found"

    return {
        "type": "scroll",
        "scroll": normalized_scroll,
        "tweet_count": int(tweet_count),
        "raw_hits": int(raw_hits),
        "after_likes_filter": int(after_likes_filter),
        "after_keywords_filter": int(after_keywords_filter),
        "after_article_entity": int(after_article_entity),
        "after_article_url_extract": int(after_article_url_extract),
        "after_language_length_filter": int(after_language_length_filter),
        "duplicate_filtered": int(duplicate_filtered),
        "deduped_hits": int(deduped_hits),
        "suspected_reason": suspected_reason,
        "sample": sample or [],
    }


def discover_article_candidates_from_search(
    query: str,
    *,
    storage_state: str | Path | dict[str, Any] | None = None,
    search_mode: str = "top",
    max_scrolls: int = 4,
    max_candidates: int = 20,
    min_likes: int = 200,
    required_keywords: list[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """从 X 搜索页发现“可能的精品文章”。"""
    try:
        graphql_results = _discover_article_candidates_from_search_graphql(
            query,
            storage_state=storage_state,
            search_mode=search_mode,
            max_candidates=max_candidates,
            min_likes=min_likes,
            required_keywords=required_keywords,
            progress_callback=progress_callback,
        )
        if graphql_results:
            return graphql_results
    except Exception as exc:
        if progress_callback is not None:
            try:
                suspected_reason, detail = _classify_x_graphql_failure(exc)
                progress_callback(
                    {
                        "type": "hint",
                        "suspected_reason": suspected_reason,
                        "detail": detail,
                    }
                )
            except Exception:
                pass

    mode = (search_mode or "top").lower()
    mode_param = "top" if mode not in {"latest", "live"} else "live"
    search_url = (
        "https://x.com/search?"
        f"q={quote_plus(query)}&src=typed_query&f={mode_param}"
    )
    return _discover_article_candidates_from_feed_url(
        start_url=search_url,
        storage_state=storage_state,
        max_scrolls=max_scrolls,
        max_candidates=max_candidates,
        min_likes=min_likes,
        required_keywords=required_keywords,
        progress_callback=progress_callback,
    )


def discover_article_candidates_from_home_timeline(
    *,
    storage_state: str | Path | dict[str, Any] | None = None,
    max_scrolls: int = 4,
    max_candidates: int = 20,
    min_likes: int = 200,
    required_keywords: list[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """从登录用户的首页推荐流发现可能的 X Article。"""
    # Home Timeline 的 DOM 扫描在 headless 下非常不稳定（经常触发结构不匹配/风控）。
    # 只要具备 GraphQL 所需 cookie，就只走 GraphQL，并且即使结果为空也不要再 fallback 到 DOM。
    cookie_map = _load_x_graphql_cookie_map(storage_state)
    if _has_required_x_graphql_cookies(cookie_map):
        try:
            return _discover_article_candidates_from_home_timeline_graphql(
                storage_state=storage_state,
                max_candidates=max_candidates,
                min_likes=min_likes,
                required_keywords=required_keywords,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            if progress_callback is not None:
                try:
                    suspected_reason, detail = _classify_x_graphql_failure(exc)
                    progress_callback(
                        {
                            "type": "hint",
                            "suspected_reason": suspected_reason,
                            "detail": detail,
                        }
                    )
                except Exception:
                    pass
            # 推荐流 GraphQL 失败时不要退回 DOM（太不稳定），返回空结果并让上层 UI 给出明确提示。
            return []

    return _discover_article_candidates_from_feed_url(
        start_url="https://x.com/home",
        storage_state=storage_state,
        max_scrolls=max_scrolls,
        max_candidates=max_candidates,
        min_likes=min_likes,
        required_keywords=required_keywords,
        progress_callback=progress_callback,
    )


def _discover_article_candidates_from_feed_url(
    *,
    start_url: str,
    storage_state: str | Path | dict[str, Any] | None = None,
    max_scrolls: int = 4,
    max_candidates: int = 20,
    min_likes: int = 200,
    required_keywords: list[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    required_keywords = [kw.strip() for kw in (required_keywords or []) if kw.strip()]
    keyword_patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in required_keywords]

    context_kwargs: dict[str, Any] = {}
    if storage_state is not None:
        context_kwargs["storage_state"] = str(storage_state) if isinstance(storage_state, Path) else storage_state

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    resolved_status_articles: dict[str, str | None] = {}
    article_language_cache: dict[str, bool] = {}
    graphql_status_candidates: dict[str, dict[str, Any] | None] = {}
    cookie_map = _load_x_graphql_cookie_map(storage_state)

    # 自适应提前停止：连续多轮滚动都没有新增推文/候选时提前结束，减少无效等待。
    no_progress_rounds = 0
    prev_tweet_count = 0
    prev_result_count = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                page.goto(start_url, wait_until="domcontentloaded")
                if progress_callback is not None:
                    try:
                        progress_callback(
                            {
                                "type": "page",
                                "page_url": page.url,
                                "page_title": (page.title() or "").strip() or None,
                            }
                        )
                    except Exception:
                        pass

                try:
                    page.wait_for_selector("article[data-testid='tweet']", timeout=8000)
                except Exception:
                    if progress_callback is not None:
                        suspected_reason, page_url, page_title = _guess_search_failure_reason(page)
                        try:
                            progress_callback(
                                {
                                    "type": "page",
                                    "page_url": page_url,
                                    "page_title": page_title,
                                }
                            )
                            progress_callback(
                                {
                                    "type": "hint",
                                    "suspected_reason": suspected_reason,
                                }
                            )
                        except Exception:
                            pass
                    return []

                for _scroll in range(max(0, int(max_scrolls)) + 1):
                    tweet_articles = page.query_selector_all("article[data-testid='tweet']")
                    raw_hits = 0
                    after_likes_filter = 0
                    after_keywords_filter = 0
                    after_article_url_extract = 0
                    after_language_length_filter = 0
                    duplicate_filtered = 0
                    deduped_hits = 0
                    samples: list[dict[str, Any]] = []
                    for tweet_article in tweet_articles:
                        likes = _extract_like_count_from_tweet_article(tweet_article)
                        if likes is None or likes < int(min_likes):
                            continue
                        after_likes_filter += 1

                        tweet_text = _extract_tweet_text(tweet_article)
                        if keyword_patterns:
                            if not tweet_text or not any(p.search(tweet_text) for p in keyword_patterns):
                                continue
                        after_keywords_filter += 1
                        raw_hits += 1

                        hrefs = []
                        for anchor in tweet_article.query_selector_all("a[href]"):
                            href = anchor.get_attribute("href") or ""
                            if href:
                                hrefs.append(href)

                        article_urls: list[str] = []
                        reason = "search_like_threshold"
                        status_url = _extract_status_url_from_hrefs(hrefs)
                        graphql_candidate = None
                        if status_url:
                            if status_url in graphql_status_candidates:
                                graphql_candidate = graphql_status_candidates[status_url]
                            else:
                                graphql_candidate = _resolve_graphql_candidate_from_status_url(
                                    status_url,
                                    cookie_map=cookie_map,
                                    likes=likes,
                                    tweet_text=tweet_text,
                                    reason=reason,
                                )
                                graphql_status_candidates[status_url] = graphql_candidate

                        if graphql_candidate is not None:
                            canonical = str(graphql_candidate.get("canonical_url") or "").strip()
                            if canonical and is_article_url(canonical):
                                after_article_url_extract += 1
                            if canonical and is_article_url(canonical) and canonical not in seen:
                                seen.add(canonical)
                                deduped_hits += 1
                                results.append(graphql_candidate)
                                if len(results) >= int(max_candidates):
                                    if progress_callback is not None:
                                        try:
                                            progress_callback(
                                                _build_search_progress_event(
                                                    scroll_index=_scroll,
                                                    max_scrolls=max_scrolls,
                                                    tweet_count=len(tweet_articles),
                                                    raw_hits=raw_hits,
                                                    after_likes_filter=after_likes_filter,
                                                    after_keywords_filter=after_keywords_filter,
                                                    after_article_entity=0,
                                                    after_article_url_extract=after_article_url_extract,
                                                    after_language_length_filter=after_language_length_filter,
                                                    duplicate_filtered=duplicate_filtered,
                                                    deduped_hits=deduped_hits,
                                                    sample=samples,
                                                )
                                            )
                                        except Exception:
                                            pass
                                    return results

                                # 这个 tweet 已经通过 GraphQL 找到 article，无需再开 status 页/扫描其他链接。
                                continue

                        direct_article_url = _extract_article_url_from_hrefs(hrefs)
                        if direct_article_url:
                            article_urls.append(direct_article_url)
                        else:
                            if status_url:
                                resolved_article_url = _resolve_article_url_from_status_page(
                                    context,
                                    status_url,
                                    resolved_status_articles,
                                )
                                if resolved_article_url:
                                    article_urls.append(resolved_article_url)

                        if article_urls:
                            after_article_url_extract += len(article_urls)
                        elif len(samples) < 5:
                            samples.append(
                                {
                                    "status_url": status_url,
                                    "likes": int(likes),
                                    "reason": "no_article_url",
                                    "tweet_excerpt": (tweet_text[:120] + "…") if len(tweet_text) > 120 else tweet_text,
                                }
                            )

                        for article_url in article_urls:
                            canonical = normalize_x_url(article_url)
                            if not is_article_url(canonical) or canonical in seen:
                                if canonical and canonical in seen:
                                    duplicate_filtered += 1
                                continue
                            if not _is_non_chinese_article_url(context, article_url, article_language_cache):
                                if len(samples) < 5:
                                    samples.append(
                                        {
                                            "status_url": status_url,
                                            "likes": int(likes),
                                            "reason": "filtered_by_language_or_length",
                                            "article_url": article_url,
                                        }
                                    )
                                continue

                            after_language_length_filter += 1

                            seen.add(canonical)
                            deduped_hits += 1
                            results.append(
                                {
                                    "canonical_url": canonical,
                                    "original_url": article_url,
                                    "likes": likes,
                                    "tweet_text": tweet_text,
                                    "score": float(likes),
                                    "reason": reason,
                                }
                            )
                            if len(results) >= int(max_candidates):
                                if progress_callback is not None:
                                    try:
                                        progress_callback(
                                            _build_search_progress_event(
                                                scroll_index=_scroll,
                                                max_scrolls=max_scrolls,
                                                tweet_count=len(tweet_articles),
                                                raw_hits=raw_hits,
                                                after_likes_filter=after_likes_filter,
                                                after_keywords_filter=after_keywords_filter,
                                                after_article_entity=0,
                                                after_article_url_extract=after_article_url_extract,
                                                after_language_length_filter=after_language_length_filter,
                                                duplicate_filtered=duplicate_filtered,
                                                deduped_hits=deduped_hits,
                                                sample=samples,
                                            )
                                        )
                                    except Exception:
                                        pass
                                return results

                    if progress_callback is not None:
                        try:
                            progress_event = _build_search_progress_event(
                                scroll_index=_scroll,
                                max_scrolls=max_scrolls,
                                tweet_count=len(tweet_articles),
                                raw_hits=raw_hits,
                                after_likes_filter=after_likes_filter,
                                after_keywords_filter=after_keywords_filter,
                                after_article_entity=0,
                                after_article_url_extract=after_article_url_extract,
                                after_language_length_filter=after_language_length_filter,
                                duplicate_filtered=duplicate_filtered,
                                deduped_hits=deduped_hits,
                                sample=samples,
                            )
                            progress_callback(progress_event)
                            suspected_reason = progress_event.get("suspected_reason")
                            if suspected_reason is not None:
                                progress_callback(
                                    {
                                        "type": "hint",
                                        "suspected_reason": suspected_reason,
                                    }
                                )
                        except Exception:
                            pass

                    if _scroll >= max(0, int(max_scrolls)):
                        continue

                    # 提前停止：连续 2 轮滚动都没有任何新增推文或候选。
                    if len(tweet_articles) == prev_tweet_count and len(results) == prev_result_count:
                        no_progress_rounds += 1
                    else:
                        no_progress_rounds = 0
                    prev_tweet_count = len(tweet_articles)
                    prev_result_count = len(results)
                    if no_progress_rounds >= 2:
                        break

                    page.mouse.wheel(0, 2400)
                    page.wait_for_timeout(900)

                return results
            finally:
                context.close()
        finally:
            browser.close()
