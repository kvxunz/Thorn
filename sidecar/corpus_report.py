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
"""Measure the teaching tree against English nobody here wrote.

Two numbers, and they answer different questions:

  contract pass rate -- how often the tree is *legal* (the invariants
  Sidecar.swift enforces, plus full coverage). A failure here is visible to
  the user as "engine unavailable", so this must stay near 100%.

  coarse-card rate -- how often a card swallowed structure instead of showing
  it. Nothing rejects these; they read as a correct-but-blunt reading, which
  is why only a corpus can find them.

Whoever writes the rules must not write the sentences, or the number measures
their imagination instead of the language. Two ways to hold to that, and they
find different things:

  random -- sampled with a fixed seed from public text in three registers.
  Says what an average sentence costs. Blind to anything the language uses
  rarely: 200 sampled sentences contained no VP ellipsis whatsoever.

  stratified -- english_sentence_training.md, hand-grouped by construction
  (ellipsis, inversion, comparatives, parentheticals). Says which
  *constructions* the rules never learned, which is the actual question.

  uv run --script corpus_report.py --fetch          # rebuild the random corpus
  uv run --script corpus_report.py                  # measure it
  uv run --script corpus_report.py --constructions  # measure by construction
"""
import collections
import itertools
import json
import random
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

import server
from corpus import load_constructions
from undersplit import find_undersplit

UA = {"User-Agent": "thorn-corpus-probe/1.0 (parser coverage measurement)"}


def get(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")


def arxiv(n_batches=4):
    """Academic prose: dense subordination, heavy nominalisation."""
    out = []
    cats = ["cs.CL", "q-bio.NC", "econ.GN", "physics.hist-ph"]
    for i, cat in enumerate(cats[:n_batches]):
        xml = get(
            "http://export.arxiv.org/api/query?"
            f"search_query=cat:{cat}&start={i * 40}&max_results=40"
        )
        for entry in ET.fromstring(xml).iter("{http://www.w3.org/2005/Atom}summary"):
            out.append(" ".join((entry.text or "").split()))
    return out


def wikipedia(n=8):
    """Expository prose: what most non-fiction reading looks like.

    The REST random endpoint rate-limits one-article-at-a-time polling, so use
    the action API's random generator, which returns a batch per request.
    """
    out = []
    for _ in range(n):
        try:
            data = json.loads(get(
                "https://en.wikipedia.org/w/api.php?action=query&format=json"
                "&generator=random&grnnamespace=0&grnlimit=20"
                "&prop=extracts&explaintext=1"
            ))
        except Exception as exc:  # noqa: BLE001 - one flaky page is fine
            print(f"  skipped a page: {exc}", file=sys.stderr)
            continue
        for page in (data.get("query") or {}).get("pages", {}).values():
            if page.get("extract"):
                out.append(" ".join(page["extract"].split()))
    return out


def gutenberg():
    """Narrative prose: dialogue, ellipsis, inversion. Gatsby (1925, PD)."""
    raw = get("https://www.gutenberg.org/cache/epub/64317/pg64317.txt")
    body = raw.split("*** START", 1)[-1].split("*** END", 1)[0]
    return [" ".join(p.split()) for p in body.split("\n\n") if len(p) > 120]




def build_corpus():
    import server
    import spacy

    # Segmentation does not need the transformer or Benepar -- and Benepar
    # refuses anything over 512 sub-word tokens, which a Wikipedia extract
    # exceeds. Split with a bare sentencizer, then confirm each candidate is a
    # real sentence with the actual model.
    splitter = spacy.blank("en")
    splitter.add_pipe("sentencizer")

    random.seed(20260802)
    pools = {"academic": arxiv(), "expository": wikipedia(), "narrative": gutenberg()}
    for name, paras in pools.items():
        print(f"fetched {name}: {len(paras)} paragraphs", file=sys.stderr)

    candidates = {}
    for register, paragraphs in pools.items():
        seen, kept = set(), []
        for para in paragraphs:
            for sent in splitter(para).sents:
                text = sent.text.strip()
                words = text.split()
                if not (6 <= len(words) <= 38):
                    continue
                letters = [c for c in text if c.isalpha()]
                if not letters or sum(c.isascii() for c in letters) / len(letters) < 0.99:
                    continue
                if re.search(r"[\[\]{}<>|@#]|\bhttp|_{2,}|\.\.\.", text):
                    continue
                if not text[0].isupper() or text[-1] not in ".!?":
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                kept.append(text)
        random.shuffle(kept)
        candidates[register] = kept[:160]
        print(f"{register}: {len(kept)} candidates", file=sys.stderr)

    server.load()
    corpus = []
    for register, texts in candidates.items():
        kept = []
        for text in texts:
            if len(kept) >= 67:
                break
            try:
                doc = server.nlp(text)
            except Exception as exc:  # noqa: BLE001 - probe, not the app
                print(f"  skipped a candidate: {exc}", file=sys.stderr)
                continue
            # A heading or caption has no tensed verb; it is not a sentence and
            # judging the parser on it would be unfair in both directions.
            if any(tok.tag_ in {"VBD", "VBP", "VBZ", "MD"} for tok in doc):
                kept.append(text)
        corpus.extend({"register": register, "text": t} for t in kept)
        print(f"{register}: {len(kept)} sentences", file=sys.stderr)

    random.shuffle(corpus)
    corpus = corpus[:200]
    with open(CORPUS_PATH, "w") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=1)
    print(f"wrote {len(corpus)} sentences", file=sys.stderr)



_WS = re.compile(r"\s+")


def contract_violation(chunks, source_tokens):
    """The invariants Sidecar.swift enforces, plus the coverage rule."""
    if not chunks:
        return "empty tree"
    seen = set()

    def walk(nodes, path, lo, hi, depth):
        if depth > 32:
            return "depth > 32"
        previous_end = lo
        for index, node in enumerate(nodes):
            node_id = f"{path}{index}" if path == "" else f"{path}.{index}"
            if node.get("id") != node_id:
                return f"id {node.get('id')!r} != path {node_id!r}"
            if node_id in seen:
                return f"duplicate id {node_id}"
            seen.add(node_id)
            start, end = node["s"], node["e"]
            if not (lo <= start < end <= hi):
                return f"span {start}:{end} escapes {lo}:{hi}"
            if start < previous_end:
                return f"span {start}:{end} overlaps previous end {previous_end}"
            previous_end = end
            expect = _WS.sub("", "".join(source_tokens[start:end]))
            if _WS.sub("", node["text"]) != expect:
                return f"text {node['text']!r} != tokens {expect!r}"
            failure = walk(node.get("children") or [], node_id, start, end, depth + 1)
            if failure:
                return failure
        return None

    failure = walk(chunks, "", 0, len(source_tokens), 1)
    if failure:
        return failure
    covered = [(n["s"], n["e"]) for n in chunks]
    if covered[0][0] != 0 or covered[-1][1] != len(source_tokens):
        return "top level does not tile the sentence"
    for (_, end), (start, _) in itertools.pairwise(covered):
        if start != end:
            return f"top-level gap at token {end}"
    return None


CORPUS_PATH = "/tmp/thorn_corpus.json"


if "--fetch" in sys.argv:
    build_corpus()
    raise SystemExit(0)

if "--constructions" in sys.argv:
    corpus = load_constructions()
    stratum_label = "构式"
else:
    with open(CORPUS_PATH) as fh:
        corpus = json.load(fh)
    stratum_label = "文体"
server.load()

stats = collections.Counter()
by_register = collections.defaultdict(collections.Counter)
signals = collections.Counter()
examples = collections.defaultdict(list)

for item in corpus:
    text, register = item["text"], item["register"]
    stats["total"] += 1
    by_register[register]["total"] += 1
    try:
        analysis = server.analyze_text(text)
        chunks, source_tokens = analysis.chunks, analysis.source_tokens
    except Exception as exc:  # noqa: BLE001 - any failure is a data point
        stats["raised"] += 1
        by_register[register]["raised"] += 1
        examples["raised"].append((text, f"{type(exc).__name__}: {exc}"))
        continue
    failure = contract_violation(chunks, source_tokens)
    if failure:
        stats["contract_failed"] += 1
        by_register[register]["contract_failed"] += 1
        examples["contract"].append((text, failure))
        continue
    stats["contract_ok"] += 1
    by_register[register]["contract_ok"] += 1

    found = find_undersplit(chunks, analysis.evidence, source_tokens)
    if found:
        worst = min(found, key=lambda f: ["clause-in-one-card", "wh-word-in-leaf", "wide-leaf"].index(f.signal))
        stats["undersplit"] += 1
        by_register[register]["undersplit"] += 1
        signals[worst.signal] += 1
        examples[worst.signal].append((text, f"[{worst.role}] {worst.text}"))

print("\n=== 契约 ===")
n = stats["total"]
print(f"总句数 {n}")
print(f"  解析抛异常   {stats['raised']:>3}  ({stats['raised']/n:.1%})")
print(f"  契约不通过   {stats['contract_failed']:>3}  ({stats['contract_failed']/n:.1%})")
print(f"  契约通过     {stats['contract_ok']:>3}  ({stats['contract_ok']/n:.1%})")

ok = stats["contract_ok"]
print("\n=== 粗卡（在契约通过的句子里） ===")
print(f"至少一处粗卡 {stats['undersplit']}/{ok}  ({stats['undersplit']/max(ok,1):.1%})")
for signal, count in signals.most_common():
    print(f"  {signal:<20} {count:>3}  ({count/max(ok,1):.1%})")

print(f"\n=== 按{stratum_label}（粗卡率降序） ===")
width = max(len(name) for name in by_register) + 2
for register, c in sorted(
    by_register.items(),
    key=lambda kv: -kv[1]["undersplit"] / max(kv[1]["contract_ok"], 1),
):
    t = c["total"]
    rate = c["undersplit"] / max(c["contract_ok"], 1)
    print(
        f"{register:<{width}} 契约通过 {c['contract_ok']:>2}/{t:<3} "
        f"粗卡 {c['undersplit']:>2}/{max(c['contract_ok'],1):<3} ({rate:.0%})"
    )

for key in ("raised", "contract", "clause-in-one-card", "wh-word-in-leaf", "wide-leaf"):
    if not examples[key]:
        continue
    print(f"\n--- {key} 例（最多 6 条）---")
    for text, detail in examples[key][:6]:
        print(f"  · {text[:120]}")
        print(f"    -> {detail[:160]}")
