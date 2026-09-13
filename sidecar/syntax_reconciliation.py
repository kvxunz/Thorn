from __future__ import annotations


def reconcile_document(doc):
    repairs = []

    def change(token, rule, **attributes):
        before = (token.head.i, token.dep_, token.pos_, token.tag_)
        for name, value in attributes.items():
            setattr(token, name, value)
        repairs.append((token.i, rule, before))

    for sentence in list(doc.sents):
        spans = tuple(sentence._.constituents)
        root = sentence.root
        if root.lemma_ == "do" and any("SBARQ" in span._.labels for span in spans):
            candidates = [token for token in sentence if token.dep_ == "nsubj" and token.head == root
                          and token.tag_ == "VB" and token.pos_ == "NOUN"
                          and any(span.start == token.i and span.end == token.i + 1
                                  and "VP" in span._.labels for span in spans)]
            if len(candidates) == 1:
                predicate = candidates[0]
                subjects = [span for span in spans if "NP" in span._.labels
                            and root.i < span.start < span.end == predicate.i]
                if subjects:
                    subject_span = max(subjects, key=lambda span: len(span))
                    heads = [token for token in subject_span
                             if token.pos_ in ("NOUN", "PROPN", "PRON") and token.head == predicate]
                    if not heads:
                        continue
                    subject = heads[-1]
                    dependents = list(root.children)
                    change(predicate, "benepar-do-question", head=predicate, dep_="ROOT", pos_="VERB")
                    change(root, "benepar-do-question", head=predicate, dep_="aux", pos_="AUX")
                    change(subject, "benepar-do-question", head=predicate, dep_="nsubj")
                    for token in subject_span:
                        if token != subject and token.head == predicate:
                            change(token, "benepar-do-question", head=subject)
                    for token in dependents:
                        if token == predicate:
                            continue
                        dependency = "dobj" if token.dep_ == "attr" and token.tag_ in ("WP", "WDT") else token.dep_
                        change(token, "benepar-do-question", head=predicate, dep_=dependency)
        for predicate in sentence:
            children = list(predicate.children)
            if predicate.tag_ != "VBN" or not any(child.dep_ == "auxpass" for child in children):
                continue
            if any(child.dep_ in ("nsubj", "nsubjpass", "expl", "csubj", "csubjpass") for child in children):
                continue
            objects = [child for child in children if child.dep_ == "dobj" and child.i > predicate.i]
            if len(objects) != 1:
                continue
            nominal = objects[0]
            fronted = [child for child in children if child.dep_ == "prep" and child.i < predicate.i]
            if not fronted or not any(
                "PP" in span._.labels and span.start <= fronted[0].i < span.end <= predicate.i
                for span in spans
            ):
                continue
            if not any("NP" in span._.labels and predicate.i < span.start <= nominal.i < span.end
                       for span in spans):
                continue
            change(nominal, "passive-locative-inversion", dep_="nsubjpass")
    doc.user_data["thorn.syntax_repairs"] = tuple(repairs)
    return doc
