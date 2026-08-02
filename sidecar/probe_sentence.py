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
"""One-off probe: run parse_text on a sentence and dump the chunk tree.

Usage: uv run --script probe_sentence.py "Sentence here."
"""
import json
import sys
import traceback

import server


def self_test():
    """Delegate to the golden regression suite.

    The corpus and its assertions used to live here as bare asserts: the first
    failure hid the other nineteen cases, and one assertion indexed children by
    position, so an unrelated commit that split out an extra card made it
    report a correct tree as broken. Both belong to a real test runner.
    """
    import unittest

    import golden_parse_checks

    suite = unittest.TestLoader().loadTestsFromModule(golden_parse_checks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


sentence = sys.argv[1] if len(sys.argv) > 1 else (
    "My father and mother should have stayed in New York "
    "where they met and married and where I was born."
)

# Before load(): the suite loads the model itself, and doing it twice costs
# another ~3 s for nothing.
if sentence == "--self-test":
    self_test()

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
