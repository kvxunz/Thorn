from __future__ import annotations

from constituency import TokenSpan


def comparative_ellipsis(sentence, doc, constituency, analyze_clause):
    if sentence.root.pos_ not in ("NOUN", "PROPN", "PRON"):
        return None
    start, end = sentence.start, sentence.end
    if doc[start].lower_ != "the":
        return None
    commas = [token.i for token in sentence if token.text == ","]
    for comma in commas:
        right = comma + 1
        if right >= end or doc[right].lower_ != "the":
            continue
        degrees = [span for span in constituency.spans
                   if span.labels.intersection({"ADJP", "ADVP"})
                   and span.start == right
                   and span.end < end
                   and any(doc[index].tag_ in ("JJR", "RBR") for index in range(span.start, span.end))]
        for degree in degrees:
            nominals = [span for span in constituency.spans if "NP" in span.labels
                        and span.start == degree.end
                        and span.contains(sentence.root.i)
                        and all(doc[index].is_punct for index in range(span.end, end))]
            left_clauses = [span for span in constituency.spans if "S" in span.labels
                            and start < span.start < span.end == comma
                            and doc[span.start:span.end].root.pos_ in ("VERB", "AUX")]
            if not nominals or not left_clauses:
                continue
            left_clause = min(left_clauses, key=lambda span: span.start)
            if not any(doc[index].tag_ in ("JJR", "RBR") for index in range(start, left_clause.start)):
                continue
            if not any(span.start == start and span.end == left_clause.start
                       and span.labels.intersection({"ADJP", "ADVP"}) for span in constituency.spans):
                continue

            def node(begin, stop, role, children=None, gloss=""):
                return {"text": doc[begin:stop].text, "role": role, "gloss": gloss,
                        "children": children, "_lo": begin, "_hi": stop - 1}

            children = [node(start, left_clause.start, "adverbial")]
            children.extend(analyze_clause(
                doc[left_clause.start:left_clause.end].root, doc,
                clause_role_of_head="clause-adverbial", constituency=constituency,
                parent_span=TokenSpan(left_clause.start, left_clause.end),
            ))
            return [node(start, right, "clause-adverbial", children),
                    node(right, degree.end, "complement", gloss="比较关联结构；系动词省略"),
                    node(degree.end, end, "subject")]
    return None
