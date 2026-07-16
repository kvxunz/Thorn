"""Chunk-span annotation for Thorn's /parse response.

The gloss-alignment subsystem (SimAlign + heuristic gloss slicing) was removed:
the local pipeline now delivers deterministic structure plus one whole-sentence
translation, nothing per-chunk.  What remains is the stable node/span contract
that lets the Swift client validate the tree it receives.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


MAX_CHUNKS = 256
MAX_SOURCE_TOKENS = 512


def annotate_chunk_spans(
    sentence: str,
    chunks: Sequence[dict[str, Any]],
    source_token_offsets: Sequence[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Copy a chunk tree and add stable IDs plus exact source token spans.

    Chunk text is produced from the same spaCy ``Doc`` as the supplied token
    offsets.  Parent-constrained, left-to-right lookup disambiguates repeated
    text such as two separate occurrences of ``that``.
    """
    if not sentence:
        raise ValueError("sentence is empty")
    if not source_token_offsets or len(source_token_offsets) > MAX_SOURCE_TOKENS:
        raise ValueError("invalid source token count")

    node_count = 0

    def token_span(char_start: int, char_end: int) -> tuple[int, int]:
        token_ids = [
            index
            for index, (start, end) in enumerate(source_token_offsets)
            if start >= char_start and end <= char_end
        ]
        if not token_ids:
            raise ValueError(f"chunk has no source tokens at {char_start}:{char_end}")
        return token_ids[0], token_ids[-1] + 1

    def walk(
        nodes: Sequence[dict[str, Any]],
        parent_start: int,
        parent_end: int,
        path: tuple[int, ...],
    ) -> list[dict[str, Any]]:
        nonlocal node_count
        output: list[dict[str, Any]] = []
        cursor = parent_start
        for position, original in enumerate(nodes):
            node_count += 1
            if node_count > MAX_CHUNKS:
                raise ValueError("chunk tree is too large")

            text = original.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("chunk text is missing")
            char_start = sentence.find(text, cursor, parent_end)
            if char_start < 0:
                # A child can start before a previous, reordered child only in
                # malformed structure output.  The fallback still stays inside
                # the parent so repeated text cannot jump to another clause.
                char_start = sentence.find(text, parent_start, parent_end)
            if char_start < 0:
                raise ValueError(f"chunk text is outside its parent: {text!r}")

            char_end = char_start + len(text)
            start_token, end_token = token_span(char_start, char_end)
            node_path = path + (position,)
            node_id = ".".join(str(part) for part in node_path)
            children = original.get("children") or []

            copied = dict(original)
            copied["id"] = node_id
            copied["s"] = start_token
            copied["e"] = end_token
            copied["children"] = (
                walk(children, char_start, char_end, node_path) if children else None
            )
            output.append(copied)
            cursor = char_end
        return output

    return walk(chunks, 0, len(sentence), ())
