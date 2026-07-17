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
#     "numpy<2",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
"""Thorn local language sidecar: deterministic sentence chunking.

Run: uv run --script server.py [--port 48620] [--idle-exit 900]
"""
import argparse
import hmac
import os
import re
import signal
import threading
import time

import benepar
import spacy
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from alignment import annotate_chunk_spans
from chunk_rules import (
    constituent_token_indices,
    is_clausal_pcomp,
    is_comitative_participle,
    is_concessive_however_clause,
    is_left_edge_introducer_token,
    merge_or_so,
    verb_group_indices,
)

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
nlp_inference_lock = threading.Lock()
# One request may wait behind the active inference; additional requests fail
# fast instead of consuming every FastAPI worker while blocked on Torch.
parse_slots = threading.BoundedSemaphore(2)
last_request = time.time()
auth_token = os.environ.get("THORN_SIDECAR_TOKEN", "")


def require_auth(x_thorn_token: str | None = Header(default=None)):
    if (not auth_token or not x_thorn_token
            or not hmac.compare_digest(auth_token, x_thorn_token)):
        raise HTTPException(status_code=401, detail="unauthorized sidecar request")


def load():
    global nlp
    benepar.download("benepar_en3")
    nlp = spacy.load("en_core_web_trf")
    if "benepar" not in nlp.pipe_names:
        nlp.add_pipe("benepar", config={"model": "benepar_en3"})


def clause_role_for(head):
    signals = [
        (token.text, token.dep_, token.pos_, token.head.pos_, token.tag_)
        for token in head.subtree
    ]
    if is_concessive_however_clause(head.dep_, signals):
        return "clause-adverbial"

    role = CLAUSE_ROLES.get(head.dep_, "clause-relative")
    if role == "clause-relative" and any(
            token.dep_ == "mark" and token.lower_ == "that"
            for token in head.children):
        return "clause-noun"
    return role


# ---------------------------------------------------------------- chunking

def chunk_roots(head):
    """Decide the chunk-root tokens directly under a clause head.
    Returns list of (root_token, role, expand). expand=True -> recurse."""
    # In inversions ("Nor, if …, is management to be blamed") spaCy hangs
    # fronted conjunctions/clauses on the auxiliary, not the content verb.
    # The verbal complex is one predicate: harvest dependents of every
    # member, or those tokens become orphans swallowed by a neighbor chunk.
    group = verb_group_indices(head)
    doc = head.doc
    candidates = list(head.children)
    for index in group:
        if index == head.i:
            continue
        candidates.extend(
            c for c in doc[index].children if c.i not in group
        )
    roots = []
    for c in sorted(candidates, key=lambda t: t.i):
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
                # adjectival-predicate clauses ("however farfetched their
                # principles may seem") still contain a verb: expand those;
                # verbless fragments ("at worst") stay flat
                if any(t.pos_ in ("VERB", "AUX") for t in c.subtree if t is not c):
                    roots.append((c, "clause-adverbial", True))
                else:
                    roots.append((c, "adverbial", False))
            else:
                # infinitive purpose phrases have no subject of their own:
                # label them adverbial, not clause (still expanded)
                has_to = any(t.tag_ == "TO" for t in c.children) or (
                    c.i > 0 and c.doc[c.i - 1].tag_ == "TO")
                roots.append((c, "adverbial" if has_to else "clause-adverbial", True))
        elif d in ("relcl", "acl"):
            # Infinitival acl after adjectives/nouns ("enough to cover…",
            # "a plan to expand") is purpose/complement, not a relative clause.
            has_to = any(t.tag_ == "TO" for t in c.children) or (
                c.i > 0 and c.doc[c.i - 1].tag_ == "TO"
            )
            has_own_subject = any(
                t.dep_ in ("nsubj", "nsubjpass", "csubj", "csubjpass")
                for t in c.children
            )
            if has_to and not has_own_subject:
                roots.append((c, "adverbial", True))
            elif c.tag_ == "VBG" and has_own_subject:
                # Absolute / participial appositive: "everyone being the same…"
                roots.append((c, "insertion", True))
            elif is_comitative_participle(c):
                # "coupled with…", "combined with…" — not a true relative clause
                roots.append((c, "insertion", True))
            else:
                roots.append((c, clause_role_for(c), True))
        elif d in ("prep", "agent"):
            # Comparative "than" is not a true preposition for teaching labels.
            if c.lower_ == "than":
                roots.append((c, "conjunction", contains_clause(c)))
            else:
                # "agent" is the by-phrase of a passive
                roots.append((c, "prep-phrase", contains_clause(c)))
        elif d in ("advmod", "npadvmod"):
            # Mid-complex adverbs already in the verbal complex stay off this list
            # so they cannot steal nested degree modifiers (almost under certainly).
            if c.i in group:
                continue
            roots.append((c, "adverbial", False))
        elif d == "cc":
            roots.append((c, "conjunction", False))
        elif d == "conj":
            # coordinate clause/phrase: same backbone treatment
            if c.pos_ in ("VERB", "AUX"):
                roots.append((c, "__coord_clause__", True))
            elif any(t.dep_ in ("nsubj", "nsubjpass") for t in c.children):
                # Non-verbal conjunct carrying its own subject = a verbless
                # coordinated clause ("…, my sister, Margaret, dead and gone"):
                # an absolute construction, never the verb's object.
                roots.append((c, "absolute", True))
            else:
                roots.append((c, "object" if head.pos_ in ("VERB", "AUX") else "adverbial",
                              contains_clause(c)))
        elif d == "mark":
            roots.append((c, "conjunction", False))
        elif d in ("intj", "parataxis", "appos"):
            roots.append((c, "insertion", contains_clause(c)))
        elif c.lower_ == "for" and c.pos_ in ("ADP", "CCONJ", "SCONJ") and not any(
                t.dep_ == "pobj" for t in c.children):
            # bare coordinating "for" (= because) between clauses
            roots.append((c, "conjunction", False))
        else:
            roots.append((c, None, contains_clause(c)))  # absorbed later
    return roots


def contains_clause(tok):
    return any(
        t.dep_ in ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
        or is_clausal_pcomp(t)
        for t in tok.subtree if t is not tok)


CLAUSE_DEPS = ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
WH_TAGS = ("WDT", "WP", "WP$")

# adverb+preposition compounds that read as one prep chunk
COMPOUND_ADV_PREP = {
    ("apart", "from"), ("according", "to"), ("regardless", "of"), ("instead", "of"),
    ("prior", "to"), ("owing", "to"), ("contrary", "to"), ("thanks", "to"),
    ("along", "with"), ("together", "with"), ("ahead", "of"), ("aside", "from"),
}

# verb+object pairs that read as one idiom chunk (lemma-based)
IDIOM_VO = {
    ("raise", "eyebrow"), ("make", "sense"), ("take", "place"), ("pay", "attention"),
    ("take", "care"), ("take", "advantage"), ("make", "use"), ("shed", "light"),
    ("play", "role"), ("play", "part"), ("catch", "sight"), ("give", "rise"),
    ("draw", "attention"), ("make", "progress"), ("take", "part"), ("keep", "pace"),
    ("lose", "sight"), ("make", "difference"), ("take", "account"), ("take", "effect"),
    ("make", "way"), ("take", "root"), ("break", "ground"), ("set", "foot"),
}


def np_expand(head, doc, role):
    """Expand a noun-ish chunk that embeds clauses: the clause subtrees become
    child chunks (recursed); everything else is the core, keeping the parent
    role. 'a decision that surprised...' -> core 'a decision' + that-clause."""
    subtree = sorted(head.subtree, key=lambda t: t.i)
    clause_heads = [t for t in subtree
                    if t is not head
                    and (t.dep_ in CLAUSE_DEPS or is_clausal_pcomp(t))
                    and t.head in subtree]
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
        bounds = {"_lo": run[0], "_hi": run[-1]}
        o = run_owner
        if o is None:
            chunks.append({"text": text, "role": role, "gloss": "",
                           "children": None, **bounds})
        else:
            # Infinitival acl ("enough to cover") is purpose, not a relative.
            # VBG + own subject is absolute/appositive insertion, not relcl.
            has_to = any(t.tag_ == "TO" for t in o.children) or (
                o.i > 0 and doc[o.i - 1].tag_ == "TO"
            )
            has_own_subject = any(
                t.dep_ in ("nsubj", "nsubjpass", "csubj", "csubjpass")
                for t in o.children
            )
            if o.dep_ == "pcomp":
                # Clausal complement of a preposition ("in how well it can
                # control expression"): a noun clause, never a relative.
                crole = "clause-noun"
            elif has_to and not has_own_subject:
                crole = "adverbial"
            elif o.tag_ == "VBG" and has_own_subject:
                crole = "insertion"
            elif is_comitative_participle(o):
                crole = "insertion"
            else:
                crole = clause_role_for(o)
            kids = build_chunks(
                o, doc,
                clause_role_of_head=crole if crole.startswith("clause") else None,
            )
            chunks.append({"text": text, "role": crole, "gloss": "",
                           "children": kids if len(kids) >= 2 else None, **bounds})
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
    # spaCy often hangs left-edge when/if on a lower xcomp ("holding…") or a
    # coordinated verb ("where they met and married") even though the token
    # belongs to the clause above. constituent_token_indices strips stranded
    # introducers (adjacency-checked) so they are neither promoted as children
    # of a complement whose text no longer contains them, nor duplicated when
    # a discontinuous conj constituent is spliced per contiguous run.
    subtree = [head.doc[i] for i in constituent_token_indices(head)]
    lo, hi = subtree[0].i, subtree[-1].i
    assign = {}
    for t_i in verb_group_indices(head):
        assign[t_i] = "verb"

    root_entries = {"verb": None}
    inline = set()
    for c, role, expand in chunk_roots(head):
        key = f"n{c.i}"
        if role == "__coord_clause__":
            inline.add(key)
        root_entries[key] = (c, role, expand)
        # Same token set the spliced/expanded chunk will own: stranded
        # left-edge when/where stay out (they belong to this clause, not the
        # lower constituent) so runs and splices can never double-emit.
        for t_i in constituent_token_indices(c):
            if t_i not in assign:
                assign[t_i] = key

    # Promote stranded left-edge introducers (when/if…) to their own chunk
    # under the finite clause parent — never under the lower non-finite host
    # (already stripped from that head's subtree above).
    for t in subtree:
        if t.i in assign:
            continue
        if is_left_edge_introducer_token(t) and t.i < head.i:
            key = f"intro{t.i}"
            intro_role = (
                "relative" if clause_role_of_head == "clause-relative" else "conjunction"
            )
            root_entries[key] = (t, intro_role, False)
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
        run_local = list(run)
        key = run_key
        run, run_key = [], None
        before = len(chunks)
        emit(doc[run_local[0]: run_local[-1] + 1].text,
             [doc[i] for i in run_local], key, run_local)
        # Exact token bounds ride along internally: coordinate-clause grouping
        # rebuilds wrapper texts from doc spans. Stripped before the response.
        for ch in chunks[before:]:
            ch.setdefault("_lo", run_local[0])
            ch.setdefault("_hi", run_local[-1])

    def emit(text, toks, key, run_local):
        if key == "verb":
            chunks.append({"text": text, "role": "verb", "gloss": "",
                           "children": None, "_lem": head.lemma_})
            return
        c, role, expand = root_entries[key]
        if key in inline:
            # Coordinate clause. With its own subject it is a full clause:
            # inside a labeled clause it reads best as one collapsible block
            # ("and where I was born"); subject-sharing VP coordination
            # ("and married") splices flat. Top level always splices flat so
            # the header keeps per-role colors on the whole backbone.
            sub = build_chunks(c, doc)
            own_subject = any(
                t.dep_ in ("nsubj", "nsubjpass", "expl") for t in c.children
            )
            if clause_role_of_head is not None and own_subject and len(sub) >= 2:
                chunks.append({"text": text, "role": clause_role_of_head,
                               "gloss": "", "children": sub, "_coord": True})
            else:
                chunks.extend(sub)
            return
        # single introducing word inside a clause gets its true role:
        # wh-pronouns/adverbs -> relative (in relative clauses) or conjunction;
        # bare subordinators (when/if/because via "mark") -> conjunction.
        # For relatives the dependency tree already knows the referent
        # (the noun the clause hangs on), so the gloss is deterministic.
        referent = head.head.text if clause_role_of_head == "clause-relative" else None
        if len(run_local) == 1 and clause_role_of_head is not None:
            tok = toks[0]
            if tok.tag_ in WH_TAGS or tok.tag_ == "WRB":
                if clause_role_of_head == "clause-relative":
                    gloss = f"指代前述的 {referent}" if referent else ""
                    chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
                else:
                    chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return
            if tok.dep_ == "mark":
                chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return
        if len(run_local) == 1 and toks[0].tag_ in WH_TAGS:
            if clause_role_of_head == "clause-relative":
                gloss = f"指代前述的 {referent}" if referent else ""
                chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
            else:
                chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
            return
        if role is None:
            chunks.append({"text": text, "role": "other", "gloss": "", "children": None})
        elif (role == "clause-noun"
              and not any(t.dep_ == "mark" and t.lower_ in
                          ("that", "whether", "if", "what", "whatever", "how", "why", "who")
                          for t in c.children)
              and not (chunks and chunks[-1]["role"] == "verb")):
            # A "noun clause" with no real subordinator that does NOT follow
            # its governing verb is almost always a misattached coordinate
            # main clause ("..., for, ..."): splice its backbone in flat.
            # Right after a verb it's a bare object clause ("He said he would
            # come") and keeps its clause identity.
            chunks.extend(build_chunks(c, doc, clause_role_of_head=clause_role_of_head))
        elif role == "object" and not expand:
            chunks.append({"text": text, "role": role, "gloss": "",
                           "children": None, "_lem": c.lemma_})
        elif expand:
            if c.pos_ in ("VERB", "AUX") or role == "absolute":
                # verbal heads recurse fully, wrapped under their clause label;
                # an absolute's adjectival head works the same way — its "verb"
                # run is the elided-be predicate ("dead and gone").
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
    result = merge_tiny(merge_or_so(merge_idioms(chunks)))
    if clause_role_of_head is not None:
        result = group_coordinate_clauses(result, clause_role_of_head, doc)
    for ch in result:
        ch.pop("_coord", None)  # marker never escapes its own level
    return result


def group_coordinate_clauses(chunks, role, doc):
    """Coordinated full clauses inside a labeled clause become sibling blocks:
    "where they met and married and where I was born" shows as
    [where they met and married] / and / [where I was born], each expandable,
    instead of nine flat rows. Only the lead segment needs wrapping — the
    coordinate ones arrive as blocks from emit."""
    idx = next((i for i, c in enumerate(chunks) if c.get("_coord")), None)
    if idx is None:
        return chunks
    lead_end = idx - 1 if idx >= 1 and chunks[idx - 1].get("role") == "conjunction" else idx
    lead = chunks[:lead_end]
    if len(lead) < 2 or any(c.get("_coord") for c in lead):
        return chunks
    if "_lo" not in lead[0] or "_hi" not in lead[-1]:
        return chunks
    text = doc[lead[0]["_lo"]: lead[-1]["_hi"] + 1].text
    wrapper = {"text": text, "role": role, "gloss": "", "children": lead,
               "_lo": lead[0]["_lo"], "_hi": lead[-1]["_hi"]}
    return [wrapper] + chunks[lead_end:]


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
                ch = dict(ch, text=out[-1]["text"] + " " + ch["text"])
                if "_lo" in out[-1]:
                    ch["_lo"] = out[-1]["_lo"]
                out.pop()
        out.append(ch)
    for ch in out:
        ch.pop("_lem", None)
    return out


def merge_tiny(chunks):
    """Attach punctuation-only chunks to the previous chunk (or the next one
    when they lead)."""
    out = []
    pending = ""
    pending_lo = None
    for ch in chunks:
        if not any(c.isalnum() for c in ch["text"]):
            if out:
                out[-1]["text"] = out[-1]["text"] + ch["text"]
                if "_hi" in ch:
                    out[-1]["_hi"] = ch["_hi"]
            else:
                if pending_lo is None:
                    pending_lo = ch.get("_lo")
                pending += ch["text"]
        else:
            if pending:
                ch = dict(ch, text=pending + ch["text"])
                if pending_lo is not None:
                    ch["_lo"] = pending_lo
                pending = ""
                pending_lo = None
            out.append(ch)
    return out


def _strip_internal_keys(nodes):
    for node in nodes:
        for key in ("_lo", "_hi", "_coord", "_lem"):
            node.pop(key, None)
        if node.get("children"):
            _strip_internal_keys(node["children"])


def parse_text(text):
    with nlp_inference_lock:
        doc = nlp(text)
    all_chunks = []
    for sent in doc.sents:
        root = sent.root
        all_chunks.extend(build_chunks(root, doc))
    _strip_internal_keys(all_chunks)
    offsets = [(token.idx, token.idx + len(token.text)) for token in doc]
    chunks = annotate_chunk_spans(text, all_chunks, offsets)
    return chunks, [token.text for token in doc]


# ---------------------------------------------------------------- server

app = FastAPI()


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


@app.get("/health", dependencies=[Depends(require_auth)])
def health():
    return {
        "ok": nlp is not None,
        "protocolVersion": 3,
    }


@app.post("/parse", dependencies=[Depends(require_auth)])
def parse(req: ParseRequest):
    global last_request
    last_request = time.time()
    # Reject oversized input before running the transformer/benepar pipeline.
    if len(re.findall(r"\w+|[^\w\s]", req.text)) > 512:
        raise HTTPException(status_code=422, detail="source token limit exceeded")
    if not parse_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="sentence parser is busy")
    try:
        chunks, source_tokens = parse_text(req.text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        parse_slots.release()
    return {"chunks": chunks, "sourceTokens": source_tokens}


def idle_watchdog(limit):
    while True:
        time.sleep(30)
        if time.time() - last_request > limit:
            # sys.exit() would only stop this watchdog thread. Terminating the
            # process is required to release spaCy and benepar memory.
            os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=48620)
    ap.add_argument("--idle-exit", type=int, default=900)
    args = ap.parse_args()
    if not auth_token:
        raise SystemExit("THORN_SIDECAR_TOKEN is required")
    load()
    threading.Thread(target=idle_watchdog, args=(args.idle_exit,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
