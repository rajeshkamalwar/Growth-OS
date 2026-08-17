from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

_MAX_HTML_LENGTH = 1_000_000
_IGNORED_TEXT_TAGS = frozenset({"script", "style", "template", "noscript"})
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class OnPageEvidence:
    source_url: str
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    robots: str | None
    html_lang: str | None
    h1_texts: tuple[str, ...]


@dataclass(slots=True)
class _TextCollector:
    tag: str
    parts: list[str] = field(default_factory=list)


class _TitleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_tags: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in _IGNORED_TEXT_TAGS:
            self.ignored_tags.append(tag.casefold())

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        for index in range(len(self.ignored_tags) - 1, -1, -1):
            if self.ignored_tags[index] == normalized_tag:
                self.ignored_tags.pop(index)
                return

    def handle_data(self, data: str) -> None:
        if not self.ignored_tags:
            self.parts.append(data)


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _WHITESPACE.sub(" ", value).strip()
    return normalized or None


def _parse_http_url(value: str) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if hostname is None or username is not None or password is not None:
        return None
    return parsed


def _without_fragment(parsed: SplitResult) -> str:
    return urlunsplit(parsed._replace(fragment=""))


def _normalize_title(parts: list[str]) -> str | None:
    parser = _TitleTextParser()
    parser.feed("".join(parts))
    parser.close()
    return _normalize("".join(parser.parts))


class _OnPageParser(HTMLParser):
    def __init__(self, *, source_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source_url = source_url
        self.text_collectors: list[_TextCollector] = []
        self.active_collectors: list[_TextCollector] = []
        self.ignored_tags: list[str] = []
        self.meta_description: str | None = None
        self.robots: str | None = None
        self.html_lang: str | None = None
        self.saw_html = False
        self.canonical_candidate: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        attributes = {name.casefold(): value for name, value in attrs}

        if normalized_tag in {"title", "h1"}:
            collector = _TextCollector(tag=normalized_tag)
            self.text_collectors.append(collector)
            self.active_collectors.append(collector)

        if normalized_tag in _IGNORED_TEXT_TAGS:
            self.ignored_tags.append(normalized_tag)

        if normalized_tag == "html" and not self.saw_html:
            self.saw_html = True
            self.html_lang = _normalize(attributes.get("lang"))
        elif normalized_tag == "meta":
            self._record_meta(attributes)
        elif normalized_tag == "link":
            self._record_canonical_candidate(attributes)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _IGNORED_TEXT_TAGS:
            self._close_last(self.ignored_tags, normalized_tag)
        if normalized_tag in {"title", "h1"}:
            for index in range(len(self.active_collectors) - 1, -1, -1):
                if self.active_collectors[index].tag == normalized_tag:
                    self.active_collectors.pop(index)
                    break

    def handle_data(self, data: str) -> None:
        if self.ignored_tags:
            return
        for collector in self.active_collectors:
            collector.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self._record_character_reference(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._record_character_reference(f"&#{name};")

    def _record_character_reference(self, reference: str) -> None:
        if self.ignored_tags:
            return
        for collector in self.active_collectors:
            collector.parts.append(reference if collector.tag == "title" else unescape(reference))

    def _record_meta(self, attributes: dict[str, str | None]) -> None:
        name = _normalize(attributes.get("name"))
        content = _normalize(attributes.get("content"))
        if name is None or content is None:
            return
        if name.casefold() == "description" and self.meta_description is None:
            self.meta_description = content
        elif name.casefold() == "robots" and self.robots is None:
            self.robots = content

    def _record_canonical_candidate(self, attributes: dict[str, str | None]) -> None:
        if self.canonical_candidate is not None:
            return
        rel = attributes.get("rel")
        href = _normalize(attributes.get("href"))
        if rel is None or href is None:
            return
        if "canonical" in {token.casefold() for token in rel.split()}:
            self.canonical_candidate = href

    @staticmethod
    def _close_last(open_tags: list[str], tag: str) -> None:
        for index in range(len(open_tags) - 1, -1, -1):
            if open_tags[index] == tag:
                open_tags.pop(index)
                return

    def evidence(self) -> tuple[str | None, tuple[str, ...], str | None]:
        titles = [
            text
            for collector in self.text_collectors
            if collector.tag == "title" and (text := _normalize_title(collector.parts))
        ]
        h1_texts = tuple(
            text
            for collector in self.text_collectors
            if collector.tag == "h1" and (text := _normalize("".join(collector.parts)))
        )
        return (titles[0] if titles else None, h1_texts, self._canonical_url())

    def _canonical_url(self) -> str | None:
        if self.canonical_candidate is None:
            return None
        try:
            resolved = urljoin(self.source_url, self.canonical_candidate)
        except ValueError:
            return None
        parsed = _parse_http_url(resolved)
        return _without_fragment(parsed) if parsed is not None else None


def extract_on_page_evidence(*, html: str, source_url: str) -> OnPageEvidence:
    if not isinstance(html, str) or not isinstance(source_url, str):
        raise TypeError("html and source_url must be strings")
    if len(html) > _MAX_HTML_LENGTH:
        raise ValueError("html exceeds 1,000,000 Unicode code points")

    parsed_source = _parse_http_url(source_url)
    if parsed_source is None:
        raise ValueError("source_url must be an absolute HTTP(S) URL without credentials")
    normalized_source = _without_fragment(parsed_source)

    parser = _OnPageParser(source_url=normalized_source)
    parser.feed(html)
    parser.close()
    title, h1_texts, canonical_url = parser.evidence()
    return OnPageEvidence(
        source_url=normalized_source,
        title=title,
        meta_description=parser.meta_description,
        canonical_url=canonical_url,
        robots=parser.robots,
        html_lang=parser.html_lang,
        h1_texts=h1_texts,
    )
