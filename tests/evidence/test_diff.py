from __future__ import annotations

import ast
import builtins
import socket
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any, get_type_hints
from urllib import request

import pytest

import growth_os.evidence as evidence_package
from growth_os.evidence import (
    EvidenceValue,
    OnPageEvidence,
    OnPageEvidenceChange,
    OnPageEvidenceDiff,
    OnPageEvidenceField,
    diff_on_page_evidence,
)


def evidence(**overrides: object) -> OnPageEvidence:
    values: dict[str, object] = {
        "source_url": "https://example.com/page",
        "title": "Previous title",
        "meta_description": "Previous description",
        "canonical_url": "https://example.com/previous",
        "robots": "index, follow",
        "html_lang": "en",
        "h1_texts": ("First", "Second"),
    }
    values.update(overrides)
    return OnPageEvidence(**values)  # type: ignore[arg-type]


def test_public_contract_shape_equality_immutability_and_exports() -> None:
    assert [(member.name, member.value) for member in OnPageEvidenceField] == [
        ("TITLE", "title"),
        ("META_DESCRIPTION", "meta_description"),
        ("CANONICAL_URL", "canonical_url"),
        ("ROBOTS", "robots"),
        ("HTML_LANG", "html_lang"),
        ("H1_TEXTS", "h1_texts"),
    ]
    assert tuple(field.name for field in fields(OnPageEvidenceChange)) == (
        "field",
        "before",
        "after",
    )
    assert tuple(field.name for field in fields(OnPageEvidenceDiff)) == (
        "source_url",
        "changes",
    )
    assert get_type_hints(OnPageEvidenceChange) == {
        "field": OnPageEvidenceField,
        "before": EvidenceValue,
        "after": EvidenceValue,
    }
    assert get_type_hints(OnPageEvidenceDiff) == {
        "source_url": str,
        "changes": tuple[OnPageEvidenceChange, ...],
    }

    change = OnPageEvidenceChange(OnPageEvidenceField.TITLE, "before", "after")
    result = OnPageEvidenceDiff("https://example.com/page", (change,))
    assert result == OnPageEvidenceDiff("https://example.com/page", (change,))
    assert isinstance(result.changes, tuple)
    assert not hasattr(change, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        change.before = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.source_url = "mutated"  # type: ignore[misc]

    assert evidence_package.__all__ == [
        "OnPageEvidence",
        "extract_on_page_evidence",
        "OnPageEvidenceField",
        "EvidenceValue",
        "OnPageEvidenceChange",
        "OnPageEvidenceDiff",
        "diff_on_page_evidence",
    ]


def test_identical_evidence_returns_empty_change_tuple() -> None:
    previous = evidence()

    assert diff_on_page_evidence(previous=previous, current=previous) == OnPageEvidenceDiff(
        source_url=previous.source_url,
        changes=(),
    )


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        (OnPageEvidenceField.TITLE, "Previous title", "Current title"),
        (OnPageEvidenceField.META_DESCRIPTION, "Previous description", None),
        (OnPageEvidenceField.CANONICAL_URL, "https://example.com/previous", None),
        (OnPageEvidenceField.ROBOTS, "index, follow", "noindex"),
        (OnPageEvidenceField.HTML_LANG, "en", "fr"),
        (OnPageEvidenceField.H1_TEXTS, ("First", "Second"), ("Second", "First", "Third")),
    ],
)
def test_each_field_independently_produces_one_exact_change(
    field: OnPageEvidenceField,
    before: EvidenceValue,
    after: EvidenceValue,
) -> None:
    previous = evidence(**{field.value: before})
    current = evidence(**{field.value: after})

    assert diff_on_page_evidence(previous=previous, current=current) == OnPageEvidenceDiff(
        source_url=previous.source_url,
        changes=(OnPageEvidenceChange(field=field, before=before, after=after),),
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (("First", "Second"), ("Changed", "Second")),
        (("First", "Second"), ("Second", "First")),
        (("First",), ("First", "Second")),
    ],
)
def test_h1_content_order_and_length_changes_are_each_one_exact_change(
    before: tuple[str, ...], after: tuple[str, ...]
) -> None:
    result = diff_on_page_evidence(
        previous=evidence(h1_texts=before),
        current=evidence(h1_texts=after),
    )

    assert result.changes == (OnPageEvidenceChange(OnPageEvidenceField.H1_TEXTS, before, after),)


def test_all_changes_are_emitted_once_in_canonical_order_with_exact_values() -> None:
    previous = evidence(
        title=None,
        meta_description="  exact previous  ",
        canonical_url=None,
        robots="INDEX",
        html_lang=None,
        h1_texts=("A", "B"),
    )
    current = evidence(
        title="  exact current  ",
        meta_description=None,
        canonical_url="HTTPS://Example.com/Current#fragment",
        robots="index",
        html_lang="en-US",
        h1_texts=("B", "A", "C"),
    )

    assert diff_on_page_evidence(previous=previous, current=current).changes == (
        OnPageEvidenceChange(OnPageEvidenceField.TITLE, None, "  exact current  "),
        OnPageEvidenceChange(OnPageEvidenceField.META_DESCRIPTION, "  exact previous  ", None),
        OnPageEvidenceChange(
            OnPageEvidenceField.CANONICAL_URL,
            None,
            "HTTPS://Example.com/Current#fragment",
        ),
        OnPageEvidenceChange(OnPageEvidenceField.ROBOTS, "INDEX", "index"),
        OnPageEvidenceChange(OnPageEvidenceField.HTML_LANG, None, "en-US"),
        OnPageEvidenceChange(OnPageEvidenceField.H1_TEXTS, ("A", "B"), ("B", "A", "C")),
    )


@pytest.mark.parametrize(("parameter", "invalid"), [("previous", object()), ("current", {})])
def test_invalid_input_types_raise_without_coercion(parameter: str, invalid: Any) -> None:
    arguments: dict[str, Any] = {"previous": evidence(), "current": evidence()}
    arguments[parameter] = invalid

    with pytest.raises(TypeError):
        diff_on_page_evidence(**arguments)


def test_different_source_urls_raise_without_normalization_or_mutation() -> None:
    previous = evidence(source_url="https://example.com/page")
    current = evidence(source_url="https://example.com/page#fragment", title="Current")
    previous_snapshot = evidence(source_url="https://example.com/page")
    current_snapshot = evidence(source_url="https://example.com/page#fragment", title="Current")

    with pytest.raises(ValueError):
        diff_on_page_evidence(previous=previous, current=current)

    assert previous == previous_snapshot
    assert current == current_snapshot


def test_comparison_makes_no_external_or_parsing_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("external or parsing call attempted")

    monkeypatch.setattr(builtins, "open", unexpected_call)
    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(request, "urlopen", unexpected_call)

    previous = evidence()
    current = evidence(title="Current title")
    assert diff_on_page_evidence(previous=previous, current=current).changes == (
        OnPageEvidenceChange(OnPageEvidenceField.TITLE, "Previous title", "Current title"),
    )
    assert previous.title == "Previous title"
    assert current.title == "Current title"


def test_module_import_and_integration_boundaries() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "src/growth_os/evidence/diff.py"
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

    assert imported_roots <= {"__future__", "dataclasses", "enum", "typing", "growth_os"}
    assert all(
        "growth_os.evidence.diff" not in path.read_text(encoding="utf-8")
        and "diff_on_page_evidence" not in path.read_text(encoding="utf-8")
        for path in active_paths
    )
    assert not list((repository_root / "alembic/versions").glob("*product_007*"))
