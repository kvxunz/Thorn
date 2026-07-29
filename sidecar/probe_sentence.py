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
    cases = {}
    for name, sentence in {
        "relative": "The book that I bought yesterday was surprisingly expensive.",
        "stranded-wh": (
            "When juries began holding advertisers responsible for misleading claims, "
            "companies changed their practices."
        ),
        "coordinate": (
            "My father and mother should have stayed in New York "
            "where they met and married and where I was born."
        ),
        "vbg-relative": "She came to help the students who were struggling.",
        "notion": (
            "The notion is that people have failed to detect the massive changes "
            "which have happened in the ocean because they have been looking back "
            "only a relatively short time into the past."
        ),
        "however": (
            "\"The test of any democratic society,\" he wrote in a Wall Street Journal "
            "column, \"lies not in how well it can control expression but in whether it "
            "gives freedom of thought and expression the widest possible latitude, "
            "however disputable or irritating the results may sometimes be"
        ),
        "idiom": (
            "Last year Mitsuo Setoyama, who was then education minister, raised eyebrows "
            "when he argued that reforms had weakened the morality."
        ),
        "negated-coordinate": "The problem is not that we lack data but that we lack time.",
        "nested-relative": "The cat that chased the mouse that stole the cheese slept.",
        "correlative": "The harder he worked, the less he achieved.",
        "sooner": "The sooner we start, the sooner we finish.",
        "fronted-degree": "Much as I admire him, I cannot agree.",
    }.items():
        cases[name], _tokens = server.parse_text(sentence)

    # Progressive disclosure keeps a noun and its relative modifier inside one
    # subject card; the clause remains available one expansion below.
    assert [chunk["role"] for chunk in cases["relative"]] == [
        "subject", "verb", "complement",
    ]
    relative_subject = cases["relative"][0]
    assert [chunk["role"] for chunk in relative_subject["children"]] == [
        "subject", "clause-relative",
    ]
    when_clause = cases["stranded-wh"][0]
    assert when_clause["children"][0]["text"] == "When"
    assert when_clause["children"][0]["role"] == "conjunction"
    assert when_clause["children"][3]["text"].startswith("holding ")
    coordinate_modifier = next(
        chunk for chunk in cases["coordinate"]
        if chunk["role"] == "prep-phrase" and chunk.get("children")
    )
    coordinated = coordinate_modifier["children"][1:]
    assert [chunk["text"] for chunk in coordinated] == [
        "where they met and married", "and", "where I was born",
    ]
    assert coordinated[0]["role"] == coordinated[2]["role"] == "clause-relative"
    who_clause = cases["vbg-relative"][2]["children"][2]
    assert who_clause["role"] == "clause-relative"
    assert who_clause["children"][0]["role"] == "relative"

    def flatten(nodes):
        return [
            node
            for chunk in nodes
            for node in [chunk, *flatten(chunk.get("children") or [])]
        ]

    assert any(chunk["role"] == "clause-relative" for chunk in flatten(cases["notion"]))
    however = next(
        chunk for chunk in flatten(cases["however"])
        if chunk["text"] == "however disputable or irritating the results may sometimes be"
    )
    assert however["role"] == "clause-adverbial"
    idiom = flatten(cases["idiom"])
    assert any(chunk["text"] == "raised eyebrows" for chunk in idiom)
    assert any(chunk["role"] == "clause-relative" for chunk in idiom)
    negated = cases["negated-coordinate"]
    assert negated[1]["text"] == "is not"
    assert "not" not in negated[2]["text"]
    nested = next(
        chunk for chunk in flatten(cases["nested-relative"])
        if chunk["text"].startswith("that chased")
    )
    assert nested["children"][0]["text"] == "that"
    assert any(child["text"] == "the mouse" for child in nested["children"])
    assert any(child["text"] == "that stole the cheese" for child in nested["children"])
    correlative = cases["correlative"][0]
    assert correlative["children"][0]["text"] == "The harder"
    sooner = cases["sooner"][0]
    assert sooner["children"][0]["text"] == "The sooner"
    fronted_degree = cases["fronted-degree"][0]
    assert fronted_degree["text"].startswith("Much ")
    print("12 live spaCy+Benepar integration probes passed")


sentence = sys.argv[1] if len(sys.argv) > 1 else (
    "My father and mother should have stayed in New York "
    "where they met and married and where I was born."
)

server.load()
if sentence == "--self-test":
    self_test()
    raise SystemExit(0)

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
except Exception:
    traceback.print_exc()
