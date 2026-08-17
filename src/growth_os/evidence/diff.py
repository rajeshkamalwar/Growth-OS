from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from growth_os.evidence.on_page import OnPageEvidence


class OnPageEvidenceField(StrEnum):
    TITLE = "title"
    META_DESCRIPTION = "meta_description"
    CANONICAL_URL = "canonical_url"
    ROBOTS = "robots"
    HTML_LANG = "html_lang"
    H1_TEXTS = "h1_texts"


EvidenceValue: TypeAlias = str | tuple[str, ...] | None  # noqa: UP040


@dataclass(frozen=True, slots=True)
class OnPageEvidenceChange:
    field: OnPageEvidenceField
    before: EvidenceValue
    after: EvidenceValue


@dataclass(frozen=True, slots=True)
class OnPageEvidenceDiff:
    source_url: str
    changes: tuple[OnPageEvidenceChange, ...]


_FIELD_ORDER = (
    OnPageEvidenceField.TITLE,
    OnPageEvidenceField.META_DESCRIPTION,
    OnPageEvidenceField.CANONICAL_URL,
    OnPageEvidenceField.ROBOTS,
    OnPageEvidenceField.HTML_LANG,
    OnPageEvidenceField.H1_TEXTS,
)


def diff_on_page_evidence(
    *, previous: OnPageEvidence, current: OnPageEvidence
) -> OnPageEvidenceDiff:
    if not isinstance(previous, OnPageEvidence) or not isinstance(current, OnPageEvidence):
        raise TypeError("previous and current must be OnPageEvidence instances")
    if previous.source_url != current.source_url:
        raise ValueError("previous and current must have the same source_url")

    changes = []
    for field in _FIELD_ORDER:
        before: EvidenceValue = getattr(previous, field.value)
        after: EvidenceValue = getattr(current, field.value)
        if before != after:
            changes.append(OnPageEvidenceChange(field=field, before=before, after=after))

    return OnPageEvidenceDiff(source_url=previous.source_url, changes=tuple(changes))
