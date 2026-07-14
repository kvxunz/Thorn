# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "spacy==3.7.5",
#     "benepar==0.2.0",
#     "torch>=2.2,<3",
#     "transformers==4.30.2",
#     "protobuf==3.20.3",
#     "sentencepiece>=0.1.99",
#     "fastapi>=0.110",
#     "uvicorn>=0.29",
#     "spacy-transformers>=1.3,<1.4",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
"""Thorn structure sidecar: dual-tree (dependency + constituency) sentence
chunking. Returns Thorn's Chunk JSON with empty glosses; the app fills
glosses/translation with a local LLM.

Run: uv run --script server.py [--port 48620] [--idle-exit 900]
"""
import argparse
import sys
import threading
import time

import benepar
import spacy
from fastapi import FastAPI
from pydantic import BaseModel

# UD dep label -> Thorn role, for clause-level constituents
CLAUSE_ROLES = {
    "relcl": "clause-relative",
    "acl": "clause-relative",
    "advcl": "clause-adverbial",
    "ccomp": "clause-noun",
    "csubj": "clause-noun",
    "csubjpass": "clause-noun",
    "xcomp": "complement",  # non-finite: treat as complement, not clause
}

nlp = None
last_request = time.time()


def load():
    global nlp
    benepar.download("benepar_en3")
    nlp = spacy.load("en_core_web_trf")
    if "benepar" not in nlp.pipe_names:
        nlp.add_pipe("benepar", config={"model": "benepar_en3"})


# ---------------------------------------------------------------- chunking

def verb_group(head):
    """Verb + its auxiliaries, negation, particles, plus a directly attached
    preposition when it has no object of its own inside this clause (phrasal
    feel: 'benefit from' stays with the verb only when 'from' is prt)."""
    toks = {head.i}
    for c in head.children:
        if c.dep_ in ("aux", "auxpass", "neg", "prt"):
            toks.add(c.i)
    return toks


def chunk_roots(head, is_root_clause):
    """Decide the chunk-root tokens directly under a clause head.
    Returns list of (root_token, role, expand). expand=True -> recurse."""
    roots = []
    for c in sorted(head.children, key=lambda t: t.i):
        d = c.dep_
        if d in ("aux", "auxpass", "neg", "prt", "punct"):
            continue  # part of the verb group / attached punctuation
        if d in ("nsubj", "nsubjpass", "expl"):
            roots.append((c, "subject", contains_clause(c)))
        elif d in ("dobj", "obj", "iobj", "dative", "oprd"):
            # linking verbs never take an object: theirs is a predicative
            linking = head.lemma_ in ("be", "seem", "become", "remain", "appear",
                                      "look", "feel", "sound", "stay", "grow")
            roots.append((c, "complement" if linking else "object", contains_clause(c)))
        elif d in ("attr", "acomp"):
            roots.append((c, "complement", contains_clause(c)))
        elif d == "xcomp":
            roots.append((c, "complement", True))
        elif d in ("ccomp", "csubj", "csubjpass"):
            roots.append((c, "clause-noun", True))
        elif d == "advcl":
            if c.pos_ not in ("VERB", "AUX"):
                # advcl hung on a non-verb ("at worst"): plain adverbial, no expansion
                roots.append((c, "adverbial", False))
            else:
                # infinitive purpose phrases have no subject of their own:
                # label them adverbial, not clause (still expanded)
                has_to = any(t.tag_ == "TO" for t in c.children) or (
                    c.i > 0 and c.doc[c.i - 1].tag_ == "TO")
                roots.append((c, "adverbial" if has_to else "clause-adverbial", True))
        elif d in ("relcl", "acl"):
            roots.append((c, "clause-relative", True))
        elif d in ("prep", "agent"):
            # "agent" is the by-phrase of a passive
            roots.append((c, "prep-phrase", contains_clause(c)))
        elif d in ("advmod", "npadvmod"):
            roots.append((c, "adverbial", False))
        elif d == "cc":
            roots.append((c, "conjunction", False))
        elif d == "conj":
            # coordinate clause/phrase: same backbone treatment
            if c.pos_ in ("VERB", "AUX"):
                roots.append((c, "__coord_clause__", True))
            else:
                roots.append((c, "object" if head.pos_ in ("VERB", "AUX") else "adverbial",
                              contains_clause(c)))
        elif d == "mark":
            roots.append((c, "conjunction", False))
        elif d in ("intj", "parataxis", "appos"):
            roots.append((c, "insertion", contains_clause(c)))
        else:
            roots.append((c, None, contains_clause(c)))  # absorbed later
    return roots


def contains_clause(tok):
    return any(t.dep_ in ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
               for t in tok.subtree if t is not tok)


def relative_or_conjunction(tok):
    if tok.tag_ in ("WDT", "WP", "WP$", "WRB") and tok.dep_ != "advmod":
        return "relative"
    return "conjunction"


CLAUSE_DEPS = ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
WH_TAGS = ("WDT", "WP", "WP$")


def np_expand(head, doc, role):
    """Expand a noun-ish chunk that embeds clauses: the clause subtrees become
    child chunks (recursed); everything else is the core, keeping the parent
    role. 'a decision that surprised...' -> core 'a decision' + that-clause."""
    subtree = sorted(head.subtree, key=lambda t: t.i)
    clause_heads = [t for t in subtree
                    if t is not head and t.dep_ in CLAUSE_DEPS and t.head in subtree]
    # only direct clause attachments; nested ones handled by recursion
    clause_heads = [c for c in clause_heads
                    if not any(c is not o and c in o.subtree for o in clause_heads)]
    owner = {}
    for c in clause_heads:
        for t in c.subtree:
            owner[t.i] = c
    chunks = []
    run_owner, run = "__sentinel__", []

    def flush():
        nonlocal run, run_owner
        if not run:
            return
        text = doc[run[0]: run[-1] + 1].text
        o = run_owner
        if o is None:
            chunks.append({"text": text, "role": role, "gloss": "", "children": None})
        else:
            crole = CLAUSE_ROLES.get(o.dep_, "clause-relative")
            kids = build_chunks(o, doc, clause_role_of_head=crole)
            chunks.append({"text": text, "role": crole, "gloss": "",
                           "children": kids if len(kids) >= 2 else None})
        run, run_owner = [], "__sentinel__"

    for t in subtree:
        o = owner.get(t.i)
        if o is not run_owner:
            flush()
            run_owner = o
        run.append(t.i)
    flush()
    return merge_tiny(chunks)


def build_chunks(head, doc, clause_role_of_head=None):
    """Partition the subtree of `head` (a verbal head) into ordered chunks.
    Every token is assigned to exactly one chunk root; chunks are contiguous
    runs of each assignment -> full coverage, and discontinuous constituents
    naturally become multiple chunks."""
    subtree = sorted(head.subtree, key=lambda t: t.i)
    lo, hi = subtree[0].i, subtree[-1].i
    assign = {}
    for t in verb_group(head):
        assign[t] = "verb"

    root_entries = {"verb": None}
    inline = set()
    for c, role, expand in chunk_roots(head, clause_role_of_head is None):
        key = f"n{c.i}"
        if role == "__coord_clause__":
            inline.add(key)
        root_entries[key] = (c, role, expand)
        for t in c.subtree:
            if t.i not in assign:
                assign[t.i] = key

    # leftovers (punctuation, stray dets) -> nearest assigned neighbor,
    # preferring left, falling back right
    for t in subtree:
        if t.i in assign:
            continue
        i = t.i - 1
        while i >= lo and i not in assign:
            i -= 1
        if i < lo:
            i = t.i + 1
            while i <= hi and i not in assign:
                i += 1
        assign[t.i] = assign.get(i, "verb")

    chunks = []
    run_key, run = None, []

    def flush():
        nonlocal run, run_key
        if not run:
            return
        text = doc[run[0]: run[-1] + 1].text
        toks = [doc[i] for i in run]
        key = run_key
        run_local = list(run)
        run, run_key = [], None

        if key == "verb":
            chunks.append({"text": text, "role": "verb", "gloss": "", "children": None})
            return
        c, role, expand = root_entries[key]
        if key in inline:
            # coordinate clause: splice its own backbone in at this level
            chunks.extend(build_chunks(c, doc))
            return
        # single wh-word: it's the relative/interrogative word
        if len(run_local) == 1 and toks[0].tag_ in WH_TAGS:
            r = "relative" if (clause_role_of_head == "clause-relative") else "conjunction"
            chunks.append({"text": text, "role": r, "gloss": "", "children": None})
            return
        if role is None:
            chunks.append({"text": text, "role": "other", "gloss": "", "children": None})
        elif expand:
            if c.pos_ in ("VERB", "AUX"):
                # verbal heads recurse fully, wrapped under their clause label
                kids = build_chunks(c, doc,
                                    clause_role_of_head=role if role.startswith("clause") else None)
                chunks.append({"text": text, "role": role, "gloss": "",
                               "children": kids if len(kids) >= 2 else None})
            else:
                # nominal head embedding a clause: splice core + clause as
                # siblings — no wrapper level, and the backbone highlight
                # stays on the core noun only
                chunks.extend(np_expand(c, doc, role))
        else:
            chunks.append({"text": text, "role": role, "gloss": "", "children": None})

    for t in subtree:
        key = assign[t.i]
        if key != run_key:
            flush()
            run_key = key
        run.append(t.i)
    flush()
    return merge_tiny(chunks)


def merge_tiny(chunks):
    """Attach punctuation-only chunks to the previous chunk (or the next one
    when they lead)."""
    out = []
    pending = ""
    for ch in chunks:
        if not any(c.isalnum() for c in ch["text"]):
            if out:
                out[-1]["text"] = out[-1]["text"] + ch["text"]
            else:
                pending += ch["text"]
        else:
            if pending:
                ch = dict(ch, text=pending + ch["text"])
                pending = ""
            out.append(ch)
    return out


def parse_text(text):
    doc = nlp(text)
    all_chunks = []
    for sent in doc.sents:
        root = sent.root
        all_chunks.extend(build_chunks(root, doc))
    return all_chunks


# ---------------------------------------------------------------- server

app = FastAPI()


class ParseRequest(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": nlp is not None}


@app.post("/parse")
def parse(req: ParseRequest):
    global last_request
    last_request = time.time()
    return {"chunks": parse_text(req.text)}


def idle_watchdog(limit):
    while True:
        time.sleep(30)
        if time.time() - last_request > limit:
            sys.exit(0)


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=48620)
    ap.add_argument("--idle-exit", type=int, default=900)
    args = ap.parse_args()
    load()
    threading.Thread(target=idle_watchdog, args=(args.idle_exit,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
