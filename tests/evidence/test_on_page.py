from __future__ import annotations

import ast
import builtins
import socket
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any
from urllib import request

import pytest

from growth_os.evidence import OnPageEvidence, extract_on_page_evidence


def test_result_shape_immutability_equality_and_ordinary_extraction() -> None:
    html = """
        <HTML lang=" en\u2003US ">
          <head>
            <title> First &amp; <em>nested</em>\n title </title>
            <meta NAME=" Description " content=" A&nbsp; useful\t summary ">
            <meta name="ROBOTS" content=" Index,\n Follow ">
            <link rel="alternate CANONICAL" href="/guide?q=one&amp;x=two#part">
          </head>
          <body>
            <H1> Main <span>heading &amp; detail</span></H1>
            <h1>Second\u2028heading</h1>
          </body>
        </HTML>
    """

    actual = extract_on_page_evidence(
        html=html,
        source_url="HTTPS://Example.COM/base/page?source=yes#old",
    )
    expected = OnPageEvidence(
        source_url="https://Example.COM/base/page?source=yes",
        title="First & nested title",
        meta_description="A useful summary",
        canonical_url="https://Example.COM/guide?q=one&x=two",
        robots="Index, Follow",
        html_lang="en US",
        h1_texts=("Main heading & detail", "Second heading"),
    )

    assert actual == expected
    assert tuple(field.name for field in fields(actual)) == (
        "source_url",
        "title",
        "meta_description",
        "canonical_url",
        "robots",
        "html_lang",
        "h1_texts",
    )
    assert isinstance(actual.h1_texts, tuple)
    with pytest.raises(FrozenInstanceError):
        actual.title = "changed"  # type: ignore[misc]


def test_absent_blank_duplicate_malformed_and_ignored_content_behavior() -> None:
    html = """
      <html lang="   "><html lang="later">
      <TITLE> &nbsp; </TITLE><title>Kept <script>bad</script><b>title</b></title>
      <title>later title</title>
      <META NaMe=" DESCRIPTION " content="\t">
      <meta name="description" content=" First  description ">
      <meta name="description" content="later description">
      <meta name=" robots " content=" ">
      <meta name="ROBOTS" content="noIndex,   NOFOLLOW">
      <meta name="robots" content="later">
      <h1> </h1><H1>One <br>two<style>bad</style><template>bad</template></H1>
      <h1>Three<noscript>bad</noscript><script>bad</script>four
    """

    actual = extract_on_page_evidence(html=html, source_url="https://example.com")

    assert actual.title == "Kept title"
    assert actual.meta_description == "First description"
    assert actual.robots == "noIndex, NOFOLLOW"
    assert actual.html_lang is None
    assert actual.h1_texts == ("One two", "Threefour")


def test_all_values_are_absent_for_empty_document() -> None:
    assert extract_on_page_evidence(html="", source_url="https://example.com") == OnPageEvidence(
        source_url="https://example.com",
        title=None,
        meta_description=None,
        canonical_url=None,
        robots=None,
        html_lang=None,
        h1_texts=(),
    )


def test_escaped_title_markup_is_text_while_real_markup_is_descendant_content() -> None:
    actual = extract_on_page_evidence(
        html="<title>&lt;b&gt;literal&lt;/b&gt; <b>nested&amp;text</b></title>",
        source_url="https://example.com",
    )

    assert actual.title == "<b>literal</b> nested&text"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://other.example/a?q=1#part", "https://other.example/a?q=1"),
        ("../canonical?q=1#part", "https://example.com/root/canonical?q=1"),
        ("//cdn.example/path#part", "https://cdn.example/path"),
    ],
)
def test_canonical_resolution_and_fragment_removal(href: str, expected: str) -> None:
    actual = extract_on_page_evidence(
        html=f'<link rel="canonical" href="{href}">',
        source_url="https://example.com/root/dir/page?old=1#source-fragment",
    )

    assert actual.canonical_url == expected


def test_canonical_skips_blank_href_before_first_non_empty_candidate() -> None:
    html = """
      <link rel="canonical" href=" ">
      <link rel="CANONICAL alternate" href="/first">
      <link rel="canonical" href="/later">
    """

    actual = extract_on_page_evidence(html=html, source_url="https://example.com/page")

    assert actual.canonical_url == "https://example.com/first"


@pytest.mark.parametrize(
    "invalid_href",
    [
        "mailto:hello@example.com",
        "http:///hostless",
        "https://user@example.com/private",
        "https://:password@example.com/private",
    ],
)
def test_invalid_first_canonical_does_not_fall_through(invalid_href: str) -> None:
    html = f"""
      <link rel="canonical" href="{invalid_href}">
      <link rel="canonical" href="https://valid.example/later">
    """

    actual = extract_on_page_evidence(html=html, source_url="https://example.com/page")

    assert actual.canonical_url is None


def test_canonical_rel_requires_a_complete_whitespace_separated_token() -> None:
    html = """
      <link rel="notcanonical" href="/wrong">
      <link rel="canonical canonical" href="/right">
    """

    actual = extract_on_page_evidence(html=html, source_url="https://example.com/page")

    assert actual.canonical_url == "https://example.com/right"


@pytest.mark.parametrize(
    "source_url",
    [
        "/relative",
        "http:///hostless",
        "ftp://example.com/file",
        "https://user@example.com/private",
        "https://:password@example.com/private",
    ],
)
def test_invalid_source_urls_raise_value_error(source_url: str) -> None:
    with pytest.raises(ValueError):
        extract_on_page_evidence(html="", source_url=source_url)


def test_source_url_removes_only_fragment_and_accepts_mixed_case_scheme() -> None:
    actual = extract_on_page_evidence(
        html="",
        source_url="HtTpS://Example.COM:8443/a/../b?q=One#fragment",
    )

    assert actual.source_url == "https://Example.COM:8443/a/../b?q=One"


def test_html_size_limit_counts_unicode_code_points() -> None:
    accepted = extract_on_page_evidence(html="😀" * 1_000_000, source_url="https://example.com")
    assert accepted.h1_texts == ()

    with pytest.raises(ValueError):
        extract_on_page_evidence(html="😀" * 1_000_001, source_url="https://example.com")


@pytest.mark.parametrize(
    ("html", "source_url"),
    [
        (b"<title>bytes</title>", "https://example.com"),
        ("", object()),
    ],
)
def test_inputs_are_not_coerced(html: Any, source_url: Any) -> None:
    with pytest.raises(TypeError):
        extract_on_page_evidence(html=html, source_url=source_url)


def test_extraction_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("external call attempted")

    monkeypatch.setattr(builtins, "open", unexpected_call)
    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(request, "urlopen", unexpected_call)

    actual = extract_on_page_evidence(
        html="<title>Offline</title><h1>Observed</h1>",
        source_url="https://example.com/page",
    )

    assert actual.title == "Offline"
    assert actual.h1_texts == ("Observed",)


def test_module_has_only_standard_library_imports_and_no_active_path_reference() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "src/growth_os/evidence/on_page.py"
    syntax = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(syntax)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(syntax)
        if isinstance(node, ast.ImportFrom)
    }
    active_paths = [
        path
        for path in (repository_root / "src/growth_os").rglob("*.py")
        if path.parent.name != "evidence"
    ]

    assert imported_roots <= {"__future__", "dataclasses", "html", "re", "urllib"}
    assert all(
        "growth_os.evidence" not in path.read_text(encoding="utf-8") for path in active_paths
    )
