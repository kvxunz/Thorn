from __future__ import annotations

from itertools import pairwise


def coordinated_gerund_subject_children(
    root,
    doc,
    constituency,
    parent_span,
):
    """Return coarse children for a Benepar-backed coordinated VBG subject."""
    if root.tag_ != "VBG" or root.i != parent_span.start:
        return None
    for connector_index in range(root.i + 1, parent_span.end - 1):
        connector = doc[connector_index]
        if connector.pos_ != "CCONJ":
            continue
        if connector.dep_ != "cc":
            continue
        later = next((
            doc[index]
            for index in range(connector_index + 1, parent_span.end)
            if (
                doc[index].tag_ == "VBG"
                and doc[index].dep_ == "conj"
                and connector.head.i in (doc[index].head.i, doc[index].i)
            )
        ), None)
        if later is None:
            continue
        later_is_vp = any(
            span.start == later.i
            and span.end == parent_span.end
            and "VP" in span.labels
            for span in constituency.spans
        )
        whole_is_clause = any(
            span.start == parent_span.start
            and span.end == parent_span.end
            and span.labels.intersection({"S", "VP"})
            for span in constituency.spans
        )
        if not (later_is_vp and whole_is_clause):
            continue
        return [
            {
                "text": doc[parent_span.start:connector_index].text,
                "role": "subject",
                "gloss": "",
                "children": None,
                "_lo": parent_span.start,
                "_hi": connector_index - 1,
            },
            {
                "text": doc[connector_index:later.i].text,
                "role": "conjunction",
                "gloss": "",
                "children": None,
                "_lo": connector_index,
                "_hi": later.i - 1,
            },
            {
                "text": doc[later.i:parent_span.end].text,
                "role": "subject",
                "gloss": "",
                "children": None,
                "_lo": later.i,
                "_hi": parent_span.end - 1,
            },
        ]
    return None

def group_explanatory_for_clause(chunks, doc, constituency, parent_span):
    """Keep a comma-introduced explanatory ``for`` clause as one branch."""
    for index, chunk in enumerate(chunks):
        if (
            chunk.get("role") != "conjunction"
            or chunk.get("text", "").strip(" ,;:").lower() != "for"
        ):
            continue
        before = chunks[:index]
        after = chunks[index + 1:]
        if not (
            any(item.get("role") == "subject" for item in before)
            and any(item.get("role") == "verb" for item in before)
            and any(item.get("role") == "subject" for item in after)
            and any(item.get("role") == "verb" for item in after)
        ):
            continue
        cut = len(chunks)
        # When Benepar exposes coordinated top-level S children, use the
        # constituent containing ``for`` as the authoritative endpoint. With
        # no such boundary, keep the entire tail: guessing from a later "and"
        # would wrongly eject a coordinate clause that is still inside for.
        coordinate_spans = constituency.coordinate_clause_children(parent_span)
        for span in coordinate_spans:
            if not span.contains(chunk.get("_lo", -1)):
                continue
            cut = next(
                (
                    position
                    for position in range(index + 1, len(chunks))
                    if chunks[position].get("_lo", parent_span.end) >= span.end
                    and chunks[position].get("role") == "conjunction"
                ),
                len(chunks),
            )
            break
        tail = chunks[index:cut]
        rest = chunks[cut:]
        lo = tail[0].get("_lo")
        hi = tail[-1].get("_hi")
        if lo is None or hi is None:
            return chunks
        return before + [{
            "text": doc[lo:hi + 1].text,
            "role": "clause",
            "gloss": "",
            "children": tail,
            "_lo": lo,
            "_hi": hi,
        }] + rest
    return chunks

def group_colon_enumerations(chunks, doc, parent_span):
    """Collapse post-colon appositive lists into one expandable insertion.

    ``…is pervasive: an aspirin…, some wine…, coffee…`` otherwise floods the
    top level with insertion crumbs.
    """
    if len(chunks) < 3:
        return chunks
    colon_at = None
    for index, chunk in enumerate(chunks):
        text = chunk.get("text") or ""
        if text.rstrip().endswith(":") or text.strip() == ":":
            colon_at = index
            break
        # colon glued to previous card ("pervasive:")
        if ":" in text and index + 1 < len(chunks):
            # only treat as list opener when following cards look like list items
            following = chunks[index + 1:]
            if sum(1 for c in following if c.get("role") in ("insertion", "appositive", "adverbial", "other")) >= 2:
                colon_at = index
                break
    if colon_at is None or colon_at >= len(chunks) - 1:
        return chunks
    head = chunks[: colon_at + 1]
    tail = chunks[colon_at + 1:]
    list_roles = {"insertion", "appositive", "adverbial", "other", "object", "complement"}
    if sum(1 for c in tail if c.get("role") in list_roles) < 2:
        return chunks
    # Keep trailing non-list material (rare) outside the group.
    cut = len(tail)
    for i, chunk in enumerate(tail):
        if chunk.get("role") in ("verb", "subject", "clause-noun", "clause-adverbial",
                                   "clause-relative", "coordinator"):
            cut = i
            break
    items = tail[:cut]
    rest = tail[cut:]
    if len(items) < 2:
        return chunks
    lo = items[0].get("_lo")
    hi = items[-1].get("_hi")
    # `_hi` is inclusive everywhere in the builder layer (teaching_tree's
    # _node_from_builder converts it with `end = hi + 1`), so the slice needs
    # `hi + 1`. Slicing `doc[lo:hi]` dropped the last item of every enumeration.
    # Nothing downstream noticed because _alignment_payload recomputes the text
    # from `_lo`/`_hi`; the card was wrong only for whoever read it next.
    if lo is not None and hi is not None and lo <= hi < len(doc):
        text = doc[lo:hi + 1].text
    else:
        text = " ".join(c.get("text", "") for c in items)
    group = {
        "text": text,
        "role": "insertion",
        "gloss": "",
        "children": items,
    }
    if lo is not None:
        group["_lo"] = lo
    if hi is not None:
        group["_hi"] = hi
    return head + [group] + rest

def group_constituency_clauses(chunks, role, doc, constituency, parent_span):
    """Wrap coordinated clause siblings using Benepar's actual boundaries."""
    clause_spans = constituency.coordinate_clause_children(parent_span)
    if not clause_spans:
        return chunks

    def content_hi(chunk):
        """A card's last non-punctuation token.

        Benepar's clause spans stop before a trailing comma while merge_tiny
        glues that comma onto the card, so comparing raw ``_hi`` against a
        span end drops a card that belongs inside — the same seam as
        LEARNINGS #42. "not because she was not hardworking, but …" lost its
        complement that way and the wrapper read "because she was not".
        """
        hi = chunk.get("_hi", parent_span.end - 1)
        lo = chunk.get("_lo", hi)
        while hi > lo and not any(c.isalnum() for c in doc[hi].text):
            hi -= 1
        return hi
    for left, right in pairwise(clause_spans):
        separators = [
            chunk for chunk in chunks
            if chunk.get("_lo", -1) >= left.end
            and chunk.get("_hi", parent_span.end) < right.start
        ]
        if not any(chunk.get("role") == "conjunction" for chunk in separators):
            return chunks
    result = list(chunks)
    for span in reversed(clause_spans):
        positions = [
            index for index, chunk in enumerate(result)
            if chunk.get("_lo", -1) >= span.start
            and content_hi(chunk) < span.end
        ]
        if not positions or positions != list(range(positions[0], positions[-1] + 1)):
            continue
        first, last = positions[0], positions[-1]
        selected = result[first:last + 1]
        # Bounds come from the cards actually grouped, never from the Benepar
        # span. `positions` keeps only cards falling wholly inside the span, so
        # a card that straddles its edge is left outside — and a wrapper
        # measured by the span would then cover tokens that also live in that
        # sibling. "not because she was not hardworking, but because …" hit
        # exactly this: `hardworking` sat in both the wrapper and the
        # complement card beside it, and the duplicate killed the sentence.
        lo = selected[0].get("_lo", span.start)
        hi = selected[-1].get("_hi", span.end - 1)
        if (len(selected) == 1
                and selected[0].get("_lo") == lo
                and selected[0].get("_hi") == hi):
            continue
        wrapper = {
            "text": doc[lo:hi + 1].text,
            "role": role,
            "gloss": "",
            "children": selected,
            "_lo": lo,
            "_hi": hi,
        }
        result[first:last + 1] = [wrapper]
    return result

COMPOUND_ADV_PREP = {
    ("apart", "from"), ("according", "to"), ("regardless", "of"), ("instead", "of"),
    ("prior", "to"), ("owing", "to"), ("contrary", "to"), ("thanks", "to"),
    ("along", "with"), ("together", "with"), ("ahead", "of"), ("aside", "from"),
}
IDIOM_VO = {
    ("raise", "eyebrow"), ("make", "sense"), ("take", "place"), ("pay", "attention"),
    ("take", "care"), ("take", "advantage"), ("make", "use"), ("shed", "light"),
    ("play", "role"), ("play", "part"), ("catch", "sight"), ("give", "rise"),
    ("draw", "attention"), ("make", "progress"), ("take", "part"), ("keep", "pace"),
    ("lose", "sight"), ("make", "difference"), ("take", "account"), ("take", "effect"),
    ("make", "way"), ("take", "root"), ("break", "ground"), ("set", "foot"),
}


def merge_idioms(chunks):
    """Fuse verb+object idioms (raise eyebrows) and adverb+preposition
    compounds (apart from the fact)."""
    out = []
    for ch in chunks:
        if (out and out[-1].get("_lem") and out[-1]["role"] == "verb"
                and ch.get("_lem") and ch["role"] == "object"
                and (out[-1]["_lem"], ch["_lem"]) in IDIOM_VO):
            out[-1]["text"] = out[-1]["text"] + " " + ch["text"]
            if "_hi" in ch:
                out[-1]["_hi"] = ch["_hi"]
            continue
        if (out and out[-1]["role"] in ("adverbial", "other")
                and ch["role"] == "prep-phrase" and not out[-1].get("children")):
            first_prep = ch["text"].split()[0].lower() if ch["text"].split() else ""
            if (out[-1]["text"].strip(",").lower(), first_prep) in COMPOUND_ADV_PREP:
                kids = ch.get("children")
                if kids and kids[0].get("_lo") == ch.get("_lo"):
                    # The adverb is half of the preposition ("apart from"), so
                    # it belongs on the card that names it, not only on the
                    # wrapper above it.
                    kids = list(kids)
                    kids[0] = dict(
                        kids[0],
                        text=out[-1]["text"] + " " + kids[0]["text"],
                    )
                    if "_lo" in out[-1]:
                        kids[0]["_lo"] = out[-1]["_lo"]
                ch = dict(ch, text=out[-1]["text"] + " " + ch["text"])
                if kids:
                    ch["children"] = kids
                if "_lo" in out[-1]:
                    ch["_lo"] = out[-1]["_lo"]
                out.pop()
        out.append(ch)
    for ch in out:
        ch.pop("_lem", None)
    return out
