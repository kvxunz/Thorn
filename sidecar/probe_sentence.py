"""One-off probe: run parse_text on a sentence and dump the chunk tree.

Usage from repository root: bash scripts/run-sidecar.sh probe_sentence.py "Sentence here."
"""
import json
import sys
import traceback

import server

sentence = sys.argv[1] if len(sys.argv) > 1 else (
    "My father and mother should have stayed in New York "
    "where they met and married and where I was born."
)

server.load()
doc = server.nlp(sentence)
for s in doc.sents:
    print("SENT:", repr(s.text), "root:", s.root.text, s.root.i)
    for span in s._.constituents:
        labels = "/".join(span._.labels)
        print(f"  CST {span.start:>3}:{span.end:<3} {labels:<12} {span.text!r}")
for t in doc:
    print(f"{t.i:>3} {t.text:<10} dep={t.dep_:<10} head={t.head.i}:{t.head.text:<10} pos={t.pos_} tag={t.tag_}")
try:
    chunks, tokens = server.parse_text(sentence)
    print("TOKENS:", tokens)
    print(json.dumps(chunks, ensure_ascii=False, indent=1))
except Exception:  # noqa: BLE001 - a one-off probe must report any parser failure
    traceback.print_exc()
