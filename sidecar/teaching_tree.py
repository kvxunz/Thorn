"""Span-first teaching-tree transformations.

The dependency/constituency builder still decides semantic roles.  This module
owns the presentation tree that follows: every node has one authoritative,
half-open source-token span, and display text is always derived from that span.
Internal grouping metadata never crosses the sidecar protocol boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any

from syntax_relations import SyntaxRelations

_DASH_TOKENS = frozenset({"--", "—", "–", "―"})
_QUESTION_WORDS = frozenset({"why", "how", "when", "where", "what"})


@dataclass(frozen=True)
class TokenSource:
    """Source text plus exact character offsets for each parser token."""

    text: str
    token_offsets: tuple[tuple[int, int], ...]

    def __post_init__(self):
        previous_end = 0
        for start, end in self.token_offsets:
            if start < previous_end or end <= start or end > len(self.text):
                raise ValueError(f"invalid source token offset: {start}:{end}")
            previous_end = end

    @property
    def token_count(self) -> int:
        return len(self.token_offsets)

    def token_text(self, index: int) -> str:
        start, end = self.token_offsets[index]
        return self.text[start:end]

    def span_text(self, start: int, end: int) -> str:
        if not (0 <= start < end <= self.token_count):
            raise ValueError(f"invalid source token span: {start}:{end}")
        char_start = self.token_offsets[start][0]
        char_end = self.token_offsets[end - 1][1]
        return self.text[char_start:char_end]


@dataclass(frozen=True)
class SyntaxToken:
    """The dependency evidence needed by conservative teaching annotations."""

    index: int
    text: str
    lemma: str
    pos: str
    tag: str
    dep: str
    head: int


@dataclass(frozen=True)
class ConstituentEvidence:
    """One exact Benepar span and all labels attached to it."""

    start: int
    end: int
    labels: frozenset[str]


@dataclass(frozen=True)
class TeachingEvidence:
    """Immutable parser evidence consumed by the presentation-only pass."""

    tokens: tuple[SyntaxToken, ...]
    constituents: tuple[ConstituentEvidence, ...]
    repairs: tuple = ()

    @cached_property
    def relations(self) -> SyntaxRelations:
        return SyntaxRelations.from_evidence(self)

    def __post_init__(self):
        for expected, token in enumerate(self.tokens):
            if token.index != expected or not (0 <= token.head < len(self.tokens)):
                raise ValueError("invalid teaching evidence token sequence")
        for constituent in self.constituents:
            if not (
                0 <= constituent.start < constituent.end <= len(self.tokens)
            ):
                raise ValueError("invalid teaching evidence constituent span")

    @classmethod
    def from_doc(cls, doc) -> TeachingEvidence:
        tokens = tuple(
            SyntaxToken(
                index=token.i,
                text=token.text,
                lemma=token.lemma_,
                pos=token.pos_,
                tag=token.tag_,
                dep=token.dep_,
                head=token.head.i,
            )
            for token in doc
        )
        labels_by_span: dict[tuple[int, int], set[str]] = {}
        for sentence in doc.sents:
            for constituent in sentence._.constituents:
                labels = set(constituent._.labels)
                if labels:
                    labels_by_span.setdefault(
                        (constituent.start, constituent.end),
                        set(),
                    ).update(labels)
        constituents = tuple(
            ConstituentEvidence(start, end, frozenset(labels))
            for (start, end), labels in sorted(labels_by_span.items())
        )
        return cls(tokens=tokens, constituents=constituents, repairs=doc.user_data.get("thorn.syntax_repairs", ()))

    @cached_property
    def _labels_by_span(self) -> dict[tuple[int, int], frozenset[str]]:
        labels: dict[tuple[int, int], set[str]] = {}
        for constituent in self.constituents:
            labels.setdefault((constituent.start, constituent.end), set()).update(constituent.labels)
        return {span: frozenset(values) for span, values in labels.items()}

    def labels_for(self, start: int, end: int) -> frozenset[str]:
        return self._labels_by_span.get((start, end), frozenset())


@dataclass(frozen=True)
class TeachingNode:
    """A contiguous presentation node backed by a source-token span."""

    start: int
    end: int
    role: str
    gloss: str = ""
    children: tuple[TeachingNode, ...] = ()
    kind: str = "semantic"
    function: str | None = None
    form: str | None = None

    def __post_init__(self):
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid teaching-node span: {self.start}:{self.end}")
        previous_end = self.start
        for child in self.children:
            if child.start < self.start or child.end > self.end:
                raise ValueError("teaching-node child escapes its parent")
            if child.start < previous_end:
                raise ValueError("teaching-node children overlap or are out of order")
            previous_end = child.end

    def with_children(self, children: Sequence[TeachingNode]) -> TeachingNode:
        return replace(self, children=tuple(children))


def _node_from_builder(
    source: TokenSource,
    payload: dict[str, Any],
) -> TeachingNode:
    """Convert legacy builder bounds (inclusive ``_hi``) to half-open spans."""
    lo = payload.get("_lo")
    hi = payload.get("_hi")
    if not isinstance(lo, int) or not isinstance(hi, int):
        raise TypeError("builder chunk is missing explicit token bounds")
    end = hi + 1
    if not (0 <= lo < end <= source.token_count):
        raise ValueError(f"builder chunk has invalid token bounds: {lo}:{hi}")
    children = tuple(
        _node_from_builder(source, child)
        for child in payload.get("children") or ()
    )
    return TeachingNode(
        start=lo,
        end=end,
        role=str(payload.get("role") or "other"),
        gloss=str(payload.get("gloss") or ""),
        children=children,
    )


def _validate_siblings(nodes: Sequence[TeachingNode]) -> None:
    previous_end = 0
    for node in nodes:
        if node.start < previous_end:
            raise ValueError("teaching-tree siblings overlap or are out of order")
        previous_end = node.end


def _alignment_payload(source: TokenSource, node: TeachingNode) -> dict[str, Any]:
    payload = {
        "text": source.span_text(node.start, node.end),
        "role": node.role,
        "gloss": node.gloss,
        "children": (
            [_alignment_payload(source, child) for child in node.children]
            if node.children else None
        ),
        # alignment.py consumes half-open internal bounds and strips them from
        # the public v4 response.
        "_lo": node.start,
        "_hi": node.end,
    }
    if node.function is not None:
        payload["function"] = node.function
    if node.form is not None:
        payload["form"] = node.form
    return payload


def _ends_sentence(source: TokenSource, node: TeachingNode) -> bool:
    """Whether the node's surface text stops at a sentence/clause terminator.

    merge_tiny glues trailing punctuation onto the preceding chunk, so a
    chunk ending in ``.!?;:`` marks a boundary the predicate-grouping
    passes must never merge across (two selected sentences would otherwise
    fuse into one fake inverted/coordinated predicate).
    """
    text = source.span_text(node.start, node.end).rstrip().rstrip("\"'”’)]")
    return text.endswith((".", "!", "?", ";", ":"))




def _group_coordinated_predicates(
    source: TokenSource,
    nodes: Sequence[TeachingNode],
) -> tuple[TeachingNode, ...]:
    output: list[TeachingNode] = []
    index = 0
    while index < len(nodes):
        if nodes[index].role != "verb":
            output.append(nodes[index])
            index += 1
            continue

        cluster = [nodes[index]]
        cursor = index + 1
        while (
            cursor + 1 < len(nodes)
            and nodes[cursor].role == "conjunction"
            and nodes[cursor + 1].role == "verb"
            and not _ends_sentence(source, cluster[-1])
        ):
            cluster.extend((nodes[cursor], nodes[cursor + 1]))
            cursor += 2

        if (
            len(cluster) >= 3
            and cursor < len(nodes)
            and nodes[cursor].role == "object"
            and not _ends_sentence(source, cluster[-1])
        ):
            cluster.append(nodes[cursor])
            cursor += 1

        if len(cluster) >= 3:
            output.append(TeachingNode(
                start=cluster[0].start,
                end=cluster[-1].end,
                role="verb",
                children=tuple(cluster),
                kind="coordinated-predicate",
            ))
            index = cursor
        else:
            output.append(nodes[index])
            index += 1
    return tuple(output)


def _coarsen_predicates(
    source: TokenSource,
    nodes: Sequence[TeachingNode],
    parent_role: str | None = None,
) -> tuple[TeachingNode, ...]:
    nested = tuple(
        node.with_children(_coarsen_predicates(
            source,
            node.children,
            parent_role=node.role,
        ))
        if node.children else node
        for node in nodes
    )
    nested = tuple(
        replace(node, role="adverbial")
        if (
            node.role == "conjunction"
            and not node.children
            and parent_role not in {"clause-adverbial", "clause-relative"}
            and source.span_text(node.start, node.end)
                .strip().lower().strip(".,;:?") in _QUESTION_WORDS
        )
        else node
        for node in nested
    )
    return _group_coordinated_predicates(source, nested)


def _split_paired_dash_parentheticals(
    source: TokenSource,
    nodes: Sequence[TeachingNode],
) -> tuple[TeachingNode, ...]:
    output: list[TeachingNode] = []
    splittable_roles = {"subject", "object", "complement", "other"}
    next_roles = {"verb", "complement", "insertion"}

    for index, node in enumerate(nodes):
        following_role = nodes[index + 1].role if index + 1 < len(nodes) else None
        dash_positions = [
            token_index
            for token_index in range(node.start, node.end)
            if source.token_text(token_index) in _DASH_TOKENS
        ]
        if (
            node.role not in splittable_roles
            or len(dash_positions) < 2
            or following_role not in next_roles | {None}
        ):
            output.append(node)
            continue

        first_dash = dash_positions[0]
        last_dash = dash_positions[-1]
        if node.start >= first_dash or first_dash >= last_dash:
            output.append(node)
            continue

        output.append(TeachingNode(
            start=node.start,
            end=first_dash,
            role=node.role,
            gloss=node.gloss,
        ))
        output.append(TeachingNode(
            start=first_dash,
            end=last_dash + 1,
            role="insertion",
            kind="parenthetical",
        ))
        if last_dash + 1 < node.end:
            output.append(TeachingNode(
                start=last_dash + 1,
                end=node.end,
                role=node.role,
                gloss=node.gloss,
            ))
    return tuple(output)


def _contains_verb(node: TeachingNode) -> bool:
    return (
        node.role == "verb"
        or any(_contains_verb(child) for child in node.children)
    )


def _group_semicolon_clauses(
    source: TokenSource,
    nodes: Sequence[TeachingNode],
) -> tuple[TeachingNode, ...]:
    segments: list[list[TeachingNode]] = []
    current: list[TeachingNode] = []
    for node in nodes:
        current.append(node)
        if source.span_text(node.start, node.end).rstrip().endswith((";", ":")):
            segments.append(current)
            current = []
    if current:
        segments.append(current)

    if (
        len(segments) < 2
        or any(not any(_contains_verb(node) for node in segment)
               for segment in segments)
    ):
        return tuple(nodes)

    output: list[TeachingNode] = []
    for segment in segments:
        if len(segment) < 2:
            output.extend(segment)
            continue
        output.append(TeachingNode(
            start=segment[0].start,
            end=segment[-1].end,
            role="clause",
            children=tuple(segment),
            kind="semicolon-clause",
        ))
    return tuple(output)


_ROLE_FUNCTIONS = {
    "subject": "subject",
    "verb": "predicate",
    "object": "object",
    "complement": "complement",
    "clause-relative": "modifier",
    "clause-adverbial": "adverbial",
    "absolute": "adverbial",
    "conjunction": "connector",
    "relative": "connector",
    "adverbial": "adverbial",
}

_ROLE_FORMS = {
    "clause-relative": "relative-clause",
    "clause-adverbial": "adverbial-clause",
    "clause-noun": "nominal-clause",
    "prep-phrase": "prepositional-phrase",
    "absolute": "absolute-construction",
}

# Words that can open a content clause as a pure complementizer, carrying no
# role inside it.  A relative "that" is never one of these — spaCy tags it
# WDT and gives it a slot.
_COMPLEMENTIZERS = frozenset({"that", "whether", "if"})

_OBJECT_DEPS = frozenset({"dobj", "obj", "pobj", "attr", "oprd"})
_SPEECH_LEMMAS = frozenset({
    "say", "add", "announce", "answer", "ask", "cry", "reply", "shout",
    "state", "tell", "whisper", "write",
})


def _rewrite_smallest_covering(
    node: TeachingNode,
    token_index: int,
    **changes: Any,
) -> TeachingNode:
    children = list(node.children)
    for position, child in enumerate(children):
        if child.start <= token_index < child.end:
            children[position] = _rewrite_smallest_covering(
                child,
                token_index,
                **changes,
            )
            return node.with_children(children)
    if node.start <= token_index < node.end:
        return replace(node, **changes)
    return node


def _outside_governor(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> list[SyntaxToken]:
    return [
        token
        for token in evidence.tokens[node.start:node.end]
        if token.head == token.index
        or not (node.start <= token.head < node.end)
    ]


def _object_infinitive_parts(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> tuple[TeachingNode, TeachingNode] | None:
    """Expose the object in ``expect NP to VP`` on the matrix backbone.

    spaCy labels the infinitive ``ccomp`` when it has an overt subject, while
    Benepar correctly supplies ``S -> NP VP``.  The generic ccomp mapping then
    hides the matrix object inside a nominal-clause card.  Require both parses
    to agree on the narrow object-plus-to-infinitive shape before splitting;
    finite content clauses remain nominal clauses.

    Benepar's spans stop before sentence-final punctuation while merge_tiny
    glues that punctuation onto the last chunk, so the node is one token wider
    than the constituent whenever the construction ends the sentence — which
    it usually does.  Compare labels against the node's content, and let the
    emitted complement keep the punctuation so the split still tiles the node.
    """
    if node.role != "clause-noun" or len(node.children) < 2:
        return None

    content_end = node.end
    while (
        content_end > node.start
        and evidence.tokens[content_end - 1].pos == "PUNCT"
    ):
        content_end -= 1
    if "S" not in evidence.labels_for(node.start, content_end):
        return None

    object_node = node.children[0]
    tail = node.children[1:]
    if (
        object_node.role != "subject"
        or object_node.start != node.start
        or tail[0].start != object_node.end
        or not (content_end <= tail[-1].end <= node.end)
    ):
        return None

    infinitives = [
        token
        for token in evidence.tokens[node.start:node.end]
        if (
            token.dep == "ccomp"
            and token.tag == "VB"
            and not (node.start <= token.head < node.end)
            and evidence.tokens[token.head].pos in {"VERB", "AUX"}
        )
    ]
    if len(infinitives) != 1:
        return None
    infinitive = infinitives[0]

    markers = [
        token
        for token in evidence.tokens[node.start:node.end]
        if token.dep == "aux" and token.tag == "TO" and token.head == infinitive.index
    ]
    if len(markers) != 1:
        return None
    marker = markers[0]
    if (
        marker.index != object_node.end
        or "VP" not in evidence.labels_for(marker.index, content_end)
    ):
        return None

    has_overt_subject = any(
        token.dep in {"nsubj", "nsubjpass", "expl"}
        and token.head == infinitive.index
        and object_node.start <= token.index < object_node.end
        for token in evidence.tokens[object_node.start:object_node.end]
    )
    if not has_overt_subject:
        return None

    return (
        replace(object_node, role="object"),
        TeachingNode(
            start=marker.index,
            end=node.end,
            role="complement",
            children=tail,
            kind="object-infinitive",
            form="infinitive-predicate",
        ),
    )


def _split_object_infinitive_complements(
    nodes: Sequence[TeachingNode],
    evidence: TeachingEvidence,
) -> tuple[TeachingNode, ...]:
    output: list[TeachingNode] = []
    for node in nodes:
        nested = (
            node.with_children(
                _split_object_infinitive_complements(node.children, evidence)
            )
            if node.children else node
        )
        output.extend(_object_infinitive_parts(nested, evidence) or (nested,))
    return tuple(output)


def _annotate_wh_infinitive(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> TeachingNode:
    if node.end - node.start < 3 or node.role not in {
        "object", "complement", "clause-noun",
    }:
        return node
    leading = evidence.tokens[node.start]
    if leading.tag not in {"WDT", "WP", "WP$", "WRB"}:
        return node
    infinitives = [
        token
        for token in evidence.tokens[node.start:node.end]
        if token.tag == "VB"
        and any(
            marker.dep == "aux"
            and marker.tag == "TO"
            and marker.head == token.index
            for marker in evidence.tokens[node.start:node.end]
        )
    ]
    if not infinitives or not (
        evidence.labels_for(node.start, node.end) & {"SBAR", "S", "VP"}
    ):
        return node
    infinitive = infinitives[0]
    if (
        infinitive.dep not in {"ccomp", "xcomp"}
        or node.start <= infinitive.head < node.end
        or evidence.tokens[infinitive.head].pos not in {"VERB", "AUX"}
    ):
        return node

    annotated = replace(node, function="object", form="wh-infinitive")
    wh_function = (
        "object" if leading.dep in _OBJECT_DEPS
        else "adverbial" if leading.dep in {"advmod", "npadvmod"}
        else None
    )
    wh_changes: dict[str, Any] = {
        "function": wh_function,
        "form": "wh-word",
    }
    if wh_function in {"object", "adverbial"}:
        wh_changes["role"] = wh_function
    annotated = _rewrite_smallest_covering(
        annotated,
        leading.index,
        **wh_changes,
    )
    annotated = _rewrite_smallest_covering(
        annotated,
        infinitive.index,
        function="predicate",
        form="infinitive-predicate",
    )
    return annotated


def _annotate_with_complex(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> TeachingNode:
    first = evidence.tokens[node.start]
    if (
        node.role != "prep-phrase"
        or first.lemma.lower() != "with"
        or first.pos != "ADP"
        or "PP" not in evidence.labels_for(node.start, node.end)
    ):
        return node
    participles = [
        token
        for token in evidence.tokens[node.start + 1:node.end]
        if token.dep == "pcomp"
        and token.head == first.index
        and token.tag in {"VBG", "VBN"}
    ]
    if not participles:
        return node
    participle = participles[0]
    subjects = [
        token
        for token in evidence.tokens[node.start + 1:node.end]
        if token.dep in {"nsubj", "nsubjpass"}
        and token.head == participle.index
    ]
    if not subjects:
        return node

    annotated = replace(
        node,
        role="adverbial",
        function="adverbial",
        form="with-complex",
    )
    annotated = _rewrite_smallest_covering(
        annotated,
        first.index,
        function=None,
        form="preposition",
    )
    annotated = _rewrite_smallest_covering(
        annotated,
        subjects[0].index,
        function="logical-subject",
    )
    annotated = _rewrite_smallest_covering(
        annotated,
        participle.index,
        function="predicate",
        form=(
            "present-participle"
            if participle.tag == "VBG" else "past-participle"
        ),
    )
    children = list(annotated.children)
    for position, child in enumerate(children):
        if (
            child.start <= participle.index < child.end
            and child.start <= subjects[0].index < child.end
        ):
            children[position] = replace(
                child,
                role="clause",
                form="participial-clause",
            )
            break
    return annotated.with_children(children)


def _annotate_reduced_relative(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> TeachingNode:
    # The dependency supplies the grammatical relation; Benepar must at least
    # agree on the exact phrase boundary. Its English model sometimes labels
    # a VBG-led reduced relative as PP rather than VP, so require a boundary,
    # not one brittle phrase label.
    if (
        node.role != "clause-relative"
        or not evidence.labels_for(node.start, node.end)
    ):
        return node
    inside = evidence.tokens[node.start:node.end]
    candidates = [
        token
        for token in inside
        if (attachment := evidence.relations.attachment(token.index)) is not None
        and attachment.dependency == "acl"
        and token.tag in {"VBG", "VBN"}
        and not (node.start <= attachment.head < node.end)
        and evidence.tokens[attachment.head].pos in {"NOUN", "PROPN", "PRON"}
        # "The news that he had won …" is also VBN under acl, and calling its
        # finite predicate a participle is exactly backwards. A reduced
        # relative is reduced because it has no complementizer.
        and not _opens_with_complementizer(token.index, inside)
    ]
    if not candidates:
        return node
    participle = candidates[0]
    annotated = replace(
        node,
        function="modifier",
        form="reduced-relative",
    )
    return _rewrite_smallest_covering(
        annotated,
        participle.index,
        function="predicate",
        form=(
            "present-participle"
            if participle.tag == "VBG" else "past-participle"
        ),
    )


def _opens_with_complementizer(
    clause_index: int,
    tokens: Sequence[SyntaxToken],
) -> bool:
    """Whether the clause headed by ``clause_index`` is introduced by one."""
    return any(
        token.dep == "mark"
        and token.head == clause_index
        and token.lemma.lower() in _COMPLEMENTIZERS
        for token in tokens
    )


def _annotate_appositive_clause(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> TeachingNode:
    """"the fact that Parliament governs …" is not a relative clause.

    Both hang off a noun and both usually open with ``that``, so the tree
    builder lumps them together — but they are different constructions and
    Chinese grammar teaching names them separately, which is the whole point
    of the label.  The dependency settles it without a word list: a relative
    clause is ``relcl`` and its ``that`` fills a slot inside the clause
    ("a product **that** fails" — subject), while a content clause is ``acl``
    and its ``that`` is a bare complementizer, a ``mark`` filling nothing.

    Requiring that ``mark`` is what keeps the participial ``acl`` of a
    reduced relative ("payments depending on returns") out — it has none.
    """
    if node.role != "clause-relative":
        return node
    inside = evidence.tokens[node.start:node.end]
    for token in inside:
        if token.dep != "acl" or node.start <= token.head < node.end:
            continue
        if evidence.tokens[token.head].pos not in {"NOUN", "PROPN"}:
            continue
        if not _opens_with_complementizer(token.index, inside):
            continue
        # No function: "同位语从句" already names both the slot and the shape,
        # and a second chip repeating half of it earns nothing on a card.
        return replace(node, function=None, form="appositive-clause")
    return node


def _annotate_bare_preposition(
    node: TeachingNode,
    evidence: TeachingEvidence,
) -> TeachingNode:
    """A card holding the preposition alone is the 介词, not a 介词短语.

    Its object sits on the sibling card beside it, so repeating the phrase
    label here would name a phrase that is not on this card.
    """
    if node.role != "prep-phrase" or node.children:
        return node
    inside = evidence.tokens[node.start:node.end]
    if not any(token.pos == "ADP" for token in inside):
        return node
    if any(token.pos not in {"ADP", "ADV", "PART"} for token in inside):
        return node
    return replace(node, form="preposition")


def _annotate_direct_quotation(
    node: TeachingNode,
    source: TokenSource,
    evidence: TeachingEvidence,
) -> TeachingNode:
    if (
        node.role != "clause-noun"
        or "S" not in evidence.labels_for(node.start, node.end)
    ):
        return node
    governors = [
        token for token in _outside_governor(node, evidence)
        if token.dep == "ccomp"
        and token.head != token.index
        and evidence.tokens[token.head].lemma.lower() in _SPEECH_LEMMAS
    ]
    if not governors or node.start == 0:
        return node
    previous = evidence.tokens[node.start - 1]
    first_text = source.token_text(node.start).lstrip("\"'“‘")
    if (
        previous.text not in {",", ":", "\"", "“", "‘"}
        or not first_text[:1].isupper()
    ):
        return node
    return replace(node, function="content", form="direct-quotation")


def _annotate_teaching_metadata(
    source: TokenSource,
    nodes: Sequence[TeachingNode],
    evidence: TeachingEvidence,
) -> tuple[TeachingNode, ...]:
    output: list[TeachingNode] = []
    for node in nodes:
        annotated = node.with_children(
            _annotate_teaching_metadata(source, node.children, evidence)
        ) if node.children else node
        annotated = replace(
            annotated,
            function=annotated.function or _ROLE_FUNCTIONS.get(annotated.role),
            form=annotated.form or _ROLE_FORMS.get(annotated.role),
        )
        annotated = _annotate_wh_infinitive(annotated, evidence)
        annotated = _annotate_with_complex(annotated, evidence)
        annotated = _annotate_reduced_relative(annotated, evidence)
        annotated = _annotate_appositive_clause(annotated, evidence)
        annotated = _annotate_bare_preposition(annotated, evidence)
        annotated = _annotate_direct_quotation(annotated, source, evidence)
        output.append(annotated)
    return tuple(output)


def _validate_full_coverage(
    nodes: Sequence[TeachingNode],
    token_count: int,
) -> None:
    cursor = 0
    for node in nodes:
        if node.start != cursor:
            raise ValueError(
                f"teaching tree does not cover token range {cursor}:{node.start}"
            )
        cursor = node.end
    if cursor != token_count:
        raise ValueError(
            f"teaching tree does not cover token range {cursor}:{token_count}"
        )


def _project_coordinated_modifiers(
    nodes: Sequence[TeachingNode],
    evidence: TeachingEvidence,
) -> tuple[TeachingNode, ...]:
    output = []
    graph = evidence.relations
    for node in nodes:
        node = node.with_children(_project_coordinated_modifiers(node.children, evidence))
        if node.role != "clause-relative" or len(node.children) < 3:
            output.append(node)
            continue
        for group in graph.coordinations:
            attachment = graph.attachment(group.head)
            if (
                attachment is None or attachment.dependency != "acl"
                or node.start <= attachment.head < node.end
                or not all(node.start <= member < node.end for member in group.members)
                or not all(evidence.tokens[member].tag in {"VBG", "VBN"} for member in group.members)
                or any(
                    owner in group.members and not node.start <= index < node.end
                    for index, owner in enumerate(graph.clause_by_token)
                )
            ):
                continue
            runs: list[tuple[int | None, list[TeachingNode]]] = []
            for child in node.children:
                owners = {
                    graph.clause_by_token[index]
                    for index in range(child.start, child.end)
                    if evidence.tokens[index].pos != "PUNCT"
                }
                owner = next(iter(owners)) if len(owners) == 1 else None
                if child.role == "conjunction":
                    owner = None
                if owner not in group.members:
                    owner = None
                if runs and owner is not None and runs[-1][0] == owner:
                    runs[-1][1].append(child)
                else:
                    runs.append((owner, [child]))
            owners = [owner for owner, _ in runs if owner is not None]
            if owners != list(group.members) or any(
                owner is None and any(child.role != "conjunction" for child in children)
                for owner, children in runs
            ):
                continue
            if any(
                not children[0].start <= owner < children[-1].end
                for owner, children in runs if owner is not None
            ):
                continue
            projected = []
            for owner, children in runs:
                if owner is None:
                    projected.extend(children)
                    continue
                projected.append(TeachingNode(
                    start=children[0].start, end=children[-1].end,
                    role="clause-relative", children=tuple(children),
                    kind="coordinate-modifier", function="modifier", form="reduced-relative",
                ))
            node = node.with_children(projected)
            break
        output.append(node)
    return tuple(output)


def compile_teaching_tree(
    source: TokenSource,
    builder_chunks: Sequence[dict[str, Any]],
    evidence: TeachingEvidence | None = None,
) -> list[dict[str, Any]]:
    """Compile legacy semantic chunks into span-authoritative protocol input."""
    nodes = tuple(_node_from_builder(source, chunk) for chunk in builder_chunks)
    _validate_siblings(nodes)
    nodes = _split_paired_dash_parentheticals(source, nodes)
    nodes = _coarsen_predicates(source, nodes)
    nodes = _group_semicolon_clauses(source, nodes)
    if evidence is not None:
        if len(evidence.tokens) != source.token_count:
            raise ValueError("teaching evidence does not match source tokens")
        nodes = _split_object_infinitive_complements(nodes, evidence)
        nodes = _project_coordinated_modifiers(nodes, evidence)
        nodes = _annotate_teaching_metadata(source, nodes, evidence)
    _validate_full_coverage(nodes, source.token_count)
    return [_alignment_payload(source, node) for node in nodes]
