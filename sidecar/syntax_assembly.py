from __future__ import annotations

from dataclasses import dataclass

from constituency import ConstituencyIndex
from syntax_clause import analyze_clause
from syntax_ellipsis import comparative_ellipsis
from syntax_structure import SyntaxStructure


@dataclass(frozen=True)
class StructuralNode:
    attributes: tuple[tuple[str, object], ...]
    children: tuple[StructuralNode, ...] = ()

    def __post_init__(self):
        if any(not isinstance(value, (str, int, float, bool, type(None)))
               for _, value in self.attributes):
            raise TypeError("structural node attributes must be immutable scalar values")

    @classmethod
    def from_payload(cls, payload):
        return cls(
            tuple((key, value) for key, value in payload.items() if key != "children"),
            tuple(cls.from_payload(child) for child in payload.get("children") or ()),
        )

    def payload(self):
        return dict(self.attributes, children=[child.payload() for child in self.children] or None)

@dataclass(frozen=True)
class StructuralAnalysis:
    nodes: tuple[StructuralNode, ...]
    boundary_decisions: tuple[tuple[tuple[str, object], ...], ...]

    def payload(self):
        return [node.payload() for node in self.nodes]

    def decisions(self):
        return tuple(dict(decision) for decision in self.boundary_decisions)

def analyze_structure(doc, relations, *, trace=False):
    constituency = ConstituencyIndex.from_doc(doc, trace=trace, relations=relations)
    constituency.structure = SyntaxStructure(doc, relations)
    all_chunks = []
    last_end = None
    for sent in doc.sents:
        sent_chunks = comparative_ellipsis(sent, doc, constituency, analyze_clause) or analyze_clause(
            sent.root,
            doc,
            constituency=constituency,
            parent_span=constituency.sentence_span(sent.start, sent.end),
        )
        if sent_chunks:
            all_chunks.extend(sent_chunks)
        elif all_chunks and last_end is not None:
            # spaCy splits a bare colon/dash between clauses into its own
            # "sentence"; its chunks all die as punctuation-only. Glue the
            # exact source text onto the previous chunk so no character
            # vanishes from the header.
            all_chunks[-1]["text"] += doc.text[last_end: sent.end_char]
            all_chunks[-1]["_hi"] = sent.end - 1
        last_end = sent.end_char
    return StructuralAnalysis(
        tuple(StructuralNode.from_payload(chunk) for chunk in all_chunks),
        tuple(tuple(decision.items()) for decision in constituency.decisions),
    )
