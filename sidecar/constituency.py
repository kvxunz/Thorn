"""Benepar-backed phrase boundaries for Thorn's dependency roles.

Dependency parsing decides *what* a chunk does (subject, object, clause …).
This module decides *where* that chunk starts and ends.  A constituency span
is accepted only when its Penn Treebank label is compatible with the role and
it does not swallow another direct dependency root.  Otherwise the resolver
falls back to the contiguous dependency component around the root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


CLAUSE_LABELS = frozenset({"S", "SBAR", "SBARQ", "SINV", "SQ"})
WH_LABELS = frozenset({"WHNP", "WHADVP", "WHPP", "WHADJP"})

ROLE_LABEL_PRIORITY = {
    "subject": ("NP", "WHNP"),
    "object": ("NP", "WHNP"),
    "complement": ("ADJP", "NP", "WHNP", "VP", "SBAR", "S", "SINV", "SQ"),
    "prep-phrase": ("PP", "WHPP"),
    "adverbial": ("ADVP", "PP", "WHADVP", "SBAR", "S", "SINV", "SQ", "VP"),
    "insertion": ("PRN", "SBAR", "S", "VP", "NP", "ADJP"),
    "absolute": ("S", "SINV", "VP", "ADJP", "NP"),
    "relative": ("WHNP", "WHADVP", "WHPP", "WHADJP"),
    "conjunction": ("WHNP", "WHADVP", "WHPP", "WHADJP"),
}


@dataclass(frozen=True)
class TokenSpan:
    start: int
    end: int
    labels: frozenset[str] = frozenset()

    def __post_init__(self):
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid token span: {self.start}:{self.end}")

    @property
    def width(self) -> int:
        return self.end - self.start

    def contains(self, token_index: int) -> bool:
        return self.start <= token_index < self.end

    def contains_all(self, token_indices: Iterable[int]) -> bool:
        return all(self.contains(index) for index in token_indices)

    def inside(self, parent: "TokenSpan") -> bool:
        return parent.start <= self.start and self.end <= parent.end


class ConstituencyIndex:
    """Immutable index over Benepar constituents from one spaCy ``Doc``."""

    def __init__(
        self,
        spans: Sequence[TokenSpan],
        sentence_spans: Sequence[TokenSpan] = (),
    ):
        merged: dict[tuple[int, int], set[str]] = {}
        for span in spans:
            merged.setdefault((span.start, span.end), set()).update(span.labels)
        self.spans = tuple(
            TokenSpan(start, end, frozenset(labels))
            for (start, end), labels in sorted(merged.items())
        )
        self.sentence_spans = tuple(sentence_spans)

    @classmethod
    def from_doc(cls, doc) -> "ConstituencyIndex":
        spans: list[TokenSpan] = []
        sentences: list[TokenSpan] = []
        for sentence in doc.sents:
            sentences.append(TokenSpan(sentence.start, sentence.end, frozenset({"SENT"})))
            try:
                constituents = sentence._.constituents
            except AttributeError as error:
                raise ValueError("benepar constituency output is unavailable") from error
            for constituent in constituents:
                spans.append(TokenSpan(
                    constituent.start,
                    constituent.end,
                    frozenset(constituent._.labels),
                ))
        if not spans:
            raise ValueError("benepar produced no constituency spans")
        return cls(spans, sentences)

    def sentence_span(self, start: int, end: int) -> TokenSpan:
        for span in self.sentence_spans:
            if span.start == start and span.end == end:
                return span
        return TokenSpan(start, end, frozenset({"SENT"}))

    def resolve(
        self,
        *,
        root: int,
        role: str | None,
        parent: TokenSpan,
        required: Iterable[int] = (),
        blocked: Iterable[int] = (),
        dependency_indices: Iterable[int] = (),
    ) -> TokenSpan:
        """Choose a compatible constituent, otherwise a safe dependency run."""
        anchors = {root, *required}
        barriers = set(blocked) - anchors
        priorities = self._priorities(role)
        candidates = [
            span for span in self.spans
            if span.inside(parent)
            and span.contains_all(anchors)
            and not any(span.contains(index) for index in barriers)
            and span.labels.intersection(priorities)
        ]
        if candidates:
            return min(candidates, key=lambda span: (
                self._label_rank(span, priorities),
                span.width,
                span.start,
            ))
        return self._dependency_component(
            root=root,
            parent=parent,
            blocked=barriers,
            dependency_indices=dependency_indices,
        )

    def leading_wh_span(self, token_index: int, parent: TokenSpan) -> TokenSpan | None:
        """Return a Benepar WH introducer beginning at ``token_index``."""
        candidates = [
            span for span in self.spans
            if span.inside(parent)
            and span.start == token_index
            and span.labels.intersection(WH_LABELS)
        ]
        return min(candidates, key=lambda span: (span.width, span.end), default=None)

    def coordinate_clause_children(self, parent: TokenSpan) -> tuple[TokenSpan, ...]:
        """Maximal sibling-like clause spans strictly inside ``parent``.

        One nested S is merely an SBAR's body.  Two or more disjoint maximal
        clauses are a coordinated clause family worth grouping in the UI.
        """
        candidates = [
            span for span in self.spans
            if span.inside(parent)
            and (span.start != parent.start or span.end != parent.end)
            and span.labels.intersection(CLAUSE_LABELS)
        ]
        maximal = [
            span for span in candidates
            if not any(
                other is not span
                and other.start <= span.start
                and span.end <= other.end
                and (other.start < span.start or span.end < other.end)
                for other in candidates
            )
        ]
        ordered = sorted(maximal, key=lambda span: (span.start, span.end))
        if len(ordered) < 2:
            return ()
        # Real coordinated clauses leave at least one separator token (and/or,
        # punctuation) between siblings. Adjacent SBARs are commonly a bad
        # Benepar flattening of a relative nested under the preceding NP.
        if any(left.end >= right.start for left, right in zip(ordered, ordered[1:])):
            return ()
        return tuple(ordered)

    @staticmethod
    def _priorities(role: str | None) -> tuple[str, ...]:
        if role and role.startswith("clause-"):
            return ("SBAR", "SBARQ", "S", "SINV", "SQ")
        if role == "__coord_clause__":
            return ("SBAR", "SBARQ", "S", "SINV", "SQ", "VP")
        return ROLE_LABEL_PRIORITY.get(role or "", ())

    @staticmethod
    def _label_rank(span: TokenSpan, priorities: tuple[str, ...]) -> int:
        return min(
            (position for position, label in enumerate(priorities) if label in span.labels),
            default=len(priorities),
        )

    @staticmethod
    def _dependency_component(
        *,
        root: int,
        parent: TokenSpan,
        blocked: set[int],
        dependency_indices: Iterable[int],
    ) -> TokenSpan:
        available = sorted({
            index for index in dependency_indices
            if parent.contains(index) and index not in blocked
        })
        if root not in available:
            available.append(root)
            available.sort()
        position = available.index(root)
        left = position
        right = position
        while left > 0 and available[left - 1] == available[left] - 1:
            left -= 1
        while right + 1 < len(available) and available[right + 1] == available[right] + 1:
            right += 1
        return TokenSpan(available[left], available[right] + 1)
