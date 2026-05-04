from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

from packages.x_fetch.types import ParsedXPage


def parse_x_html(html: str, url: str) -> ParsedXPage:
    if _is_article_shape(html=html, url=url):
        return _parse_article_html(html)
    if _is_tweet_shape(html=html, url=url):
        return _parse_tweet_html(html)
    return _parse_article_html(html)


def _is_article_shape(*, html: str, url: str) -> bool:
    return 'data-testid="article"' in html or re.search(r"/(?:i/articles?|[A-Za-z0-9_]{1,15}/article)/\d+", url) is not None


def _is_tweet_shape(*, html: str, url: str) -> bool:
    return 'data-testid="tweet"' in html or "/status/" in url


def _parse_tweet_html(html: str) -> ParsedXPage:
    document = _parse_html_document(html)
    tweet_node = _require_node(
        document,
        lambda node: node.tag == "article" and node.attrs.get("data-testid") == "tweet",
        "Missing required tweet container: article[data-testid='tweet']",
    )
    user_node = _require_node(
        tweet_node,
        lambda node: node.tag == "div" and node.attrs.get("data-testid") == "User-Name",
        "Missing required tweet title container: div[data-testid='User-Name']",
    )
    name, handle = _extract_tweet_author(user_node)
    title = f"{name} ({handle})"

    text_node = _require_node(
        tweet_node,
        lambda node: node.tag == "div" and node.attrs.get("data-testid") == "tweetText",
        "Missing required tweet body: div[data-testid='tweetText']",
    )
    tweet_text = _node_text(text_node)
    if not tweet_text:
        raise ValueError("Missing required tweet body text inside div[data-testid='tweetText']")

    return ParsedXPage(
        title=title,
        markdown=f"# {title}\n\n{tweet_text}\n",
        content_type="tweet",
    )


def _parse_article_html(html: str) -> ParsedXPage:
    metadata = _MetadataHTMLParser()
    metadata.feed(html)
    document = _parse_html_document(html)
    article_node = _require_node(
        document,
        lambda node: node.tag == "article" and node.attrs.get("data-testid") == "article",
        "Missing required article container: article[data-testid='article']",
    )
    title_node = _find_first_node(article_node, lambda node: node.tag == "h1")
    title = _normalize_whitespace(
        _node_text(title_node)
        or unescape(metadata.meta_properties.get("og:title", ""))
        or metadata.title
    )
    if not title:
        raise ValueError("Missing required article title: h1, meta[property='og:title'], or <title>")

    body_blocks = _collect_article_blocks(article_node)
    if not body_blocks:
        raise ValueError("Missing required article body: expected paragraph or list content inside article[data-testid='article']")

    sections = [f"# {title}"]
    sections.extend(body_blocks)

    return ParsedXPage(
        title=title,
        markdown="\n\n".join(sections) + "\n",
        content_type="article",
    )


def _extract_meta(html: str, property_name: str) -> str:
    parser = _MetadataHTMLParser()
    parser.feed(html)
    return _normalize_whitespace(unescape(parser.meta_properties.get(property_name, "")))


@dataclass
class _HTMLNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_HTMLNode | str] = field(default_factory=list)


class _TreeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = _HTMLNode(tag="document")
        self._stack: list[_HTMLNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HTMLNode(
            tag=tag.lower(),
            attrs={key.lower(): value or "" for key, value in attrs},
        )
        self._stack[-1].children.append(node)
        self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HTMLNode(
            tag=tag.lower(),
            attrs={key.lower(): value or "" for key, value in attrs},
        )
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag_name:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


class _MetadataHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_properties: dict[str, str] = {}
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            property_name = attributes.get("property") or attributes.get("name")
            content = attributes.get("content", "")
            if property_name and content and property_name not in self.meta_properties:
                self.meta_properties[property_name] = content
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._title_parts)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_html_document(html: str) -> _HTMLNode:
    parser = _TreeHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.root


def _require_node(root: _HTMLNode, predicate: Callable[[_HTMLNode], bool], error_message: str) -> _HTMLNode:
    node = _find_first_node(root, predicate)
    if node is None:
        raise ValueError(error_message)
    return node


def _find_first_node(root: _HTMLNode, predicate: Callable[[_HTMLNode], bool]) -> _HTMLNode | None:
    if predicate(root):
        return root
    for child in root.children:
        if isinstance(child, _HTMLNode):
            match = _find_first_node(child, predicate)
            if match is not None:
                return match
    return None


def _collect_article_blocks(article_node: _HTMLNode) -> list[str]:
    blocks: list[str] = []

    def is_embedded_article_container(node: _HTMLNode) -> bool:
        return node.tag == "article" and node is not article_node and node.attrs.get("data-testid") in {"tweet", "article"}

    def visit(node: _HTMLNode) -> None:
        for child in node.children:
            if not isinstance(child, _HTMLNode):
                continue
            if is_embedded_article_container(child):
                continue
            if child.tag == "p":
                text = _node_text(child)
                if text:
                    blocks.append(text)
                continue
            if child.tag in {"ul", "ol"}:
                items = _list_items(child)
                if items:
                    blocks.append("\n".join(f"- {item}" for item in items))
                continue
            if child.tag == "li":
                text = _node_text(child)
                if text:
                    blocks.append(f"- {text}")
                continue
            visit(child)

    visit(article_node)
    return blocks


def _list_items(list_node: _HTMLNode) -> list[str]:
    items = [
        _node_text(child)
        for child in list_node.children
        if isinstance(child, _HTMLNode) and child.tag == "li" and _node_text(child)
    ]
    if items:
        return items
    return [
        _node_text(node)
        for node in _descendant_nodes(list_node)
        if node.tag == "li" and _node_text(node)
    ]


def _descendant_nodes(root: _HTMLNode) -> list[_HTMLNode]:
    nodes: list[_HTMLNode] = []
    for child in root.children:
        if isinstance(child, _HTMLNode):
            nodes.append(child)
            nodes.extend(_descendant_nodes(child))
    return nodes


def _direct_text_chunks(node: _HTMLNode) -> list[str]:
    chunks: list[str] = []
    for child in node.children:
        if isinstance(child, _HTMLNode):
            text = _node_text(child)
        else:
            text = _normalize_whitespace(unescape(child))
        if text:
            chunks.append(text)
    return chunks


def _descendant_text_chunks(node: _HTMLNode) -> list[str]:
    chunks: list[str] = []
    for child in node.children:
        if isinstance(child, _HTMLNode):
            chunks.extend(_descendant_text_chunks(child))
        else:
            text = _normalize_whitespace(unescape(child))
            if text:
                chunks.append(text)
    return chunks


def _extract_tweet_author(user_node: _HTMLNode) -> tuple[str, str]:
    user_parts = _descendant_text_chunks(user_node)
    if not user_parts:
        raise ValueError("Missing required tweet title text inside div[data-testid='User-Name']")

    name = ""
    handle = ""
    for part in user_parts:
        handle_match = re.search(r"@[A-Za-z0-9_]+", part)
        if handle_match and not handle:
            handle = handle_match.group(0)
            remaining = _normalize_whitespace(part.replace(handle, "", 1))
            if remaining and not name:
                name = remaining
            continue
        if not name and not part.startswith("@"):
            name = part

    if not name:
        raise ValueError("Missing required tweet title text inside div[data-testid='User-Name']")
    if not handle:
        raise ValueError("Missing required tweet handle inside div[data-testid='User-Name']")
    return name, handle


def _node_text(node: _HTMLNode | None) -> str:
    if node is None:
        return ""
    return _normalize_whitespace(unescape(" ".join(_text_fragments(node))))


def _text_fragments(node: _HTMLNode) -> list[str]:
    fragments: list[str] = []
    for child in node.children:
        if isinstance(child, _HTMLNode):
            fragments.extend(_text_fragments(child))
        else:
            fragments.append(child)
    return fragments
