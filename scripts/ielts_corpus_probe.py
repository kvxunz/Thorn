import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class PassageParagraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.divs = []
        self.current = None
        self.parts = []
        self.section = None
        self.heading = False
        self.advertisements = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div":
            self.divs.append(self.section)
            identifier = attributes.get("id", "")
            if re.fullmatch(r"ielts-reading-transcript-\d+", identifier):
                self.section = identifier
                self.advertisements = False
        if tag == "p" and self.section:
            self.current = []
            self.heading = "ielts-reading-passage-subhead" in attributes.get("class", "")
        if tag == "em" and self.current == []:
            self.heading = True

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.current is not None:
            text = " ".join("".join(self.current).split())
            if self.heading and text == "Advertisements for local businesses":
                self.advertisements = True
            if not self.heading and not self.advertisements and text and not re.match(
                r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", text
            ):
                self.parts.append((self.section, text))
            self.current = None
        if tag == "div" and self.divs:
            self.section = self.divs.pop()


def extract_cases(raw, segmenter):
    parser = PassageParagraphs()
    parser.feed(raw.decode("utf-8"))
    seen = set()
    cases = []
    for section, paragraph in parser.parts:
        for sentence in segmenter(paragraph).sents:
            text = sentence.text.strip()
            if len(text.split()) < 5 or not re.search(r"[.!?]['\"’”]?$", text):
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            previously_used = digest in {
                "66adf613274b83e19da698e2243a5de0dbb89c1c6a0de77f065bad593f477f27",
                "55937597fcc359d9bba9d9e1a4b51108834ab7042dfb47cfc7803d2cc5fdd49c",
                "389916da3a15007f1082a1494f20cf3701e5c5afb84b511139e4ce5cbf817fd5",
                "f1647024926a20107fc58ca3825df3ec22e665df25c45fa5ed32fcbedd94d8de",
                "cf479c6e7d458e18443a96cf5be0bbde3744af109b5172d4894f20f57a044e58",
            }
            cases.append({"sentence_sha256": digest, "section": section, "text": text,
                          "split": "heldout" if not previously_used and int(digest[:8], 16) % 5 == 0
                          else "development"})
    if not cases:
        raise ValueError("no passage sentences found; check source markup")
    return cases


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children") or [])


def structural_errors(analysis):
    errors = []
    if not analysis.chunks or analysis.evidence.relations.diagnostics:
        errors.append("empty or cyclic analysis")
    covered = [index for node in analysis.chunks for index in range(node["s"], node["e"])]
    if covered != list(range(len(analysis.source_tokens))):
        errors.append("top-level token coverage")
    for node in walk(analysis.chunks):
        end = node["s"]
        for child in node.get("children") or []:
            if not node["s"] <= child["s"] < child["e"] <= node["e"] or child["s"] < end:
                errors.append("child containment or sibling overlap")
                break
            end = child["e"]
    return sorted(set(errors))


def check_expectations(chunks, expectations):
    errors = []
    nodes = list(walk(chunks))
    for expectation in expectations:
        matches = [node for node in nodes if node["s"] <= expectation["anchor"] < node["e"]
                   and node["role"] == expectation["role"]]
        if "start" in expectation:
            matches = [node for node in matches if node["s"] == expectation["start"]]
        if "end" in expectation:
            matches = [node for node in matches if node["e"] == expectation["end"]]
        if "parent_anchor" in expectation:
            matches = [node for node in matches if any(
                parent["s"] <= expectation["parent_anchor"] < parent["e"]
                and parent["role"] == expectation["parent_role"]
                and node in (parent.get("children") or []) for parent in nodes)]
        if expectation.get("top_level"):
            matches = [node for node in matches if node in chunks]
        if not matches:
            errors.append(expectation)
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--review-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.review_dir and args.review_dir.resolve().is_relative_to(root):
        parser.error("full-text review output must stay outside the repository")
    sys.path.insert(0, str(root / "sidecar"))
    import server
    import spacy

    segmenter = spacy.blank("en")
    segmenter.add_pipe("sentencizer")
    raw = args.html.read_bytes()
    cases = extract_cases(raw, segmenter)
    gold = json.loads(args.gold.read_text()) if args.gold else {}
    missing = set(gold) - {case["sentence_sha256"] for case in cases}
    if missing:
        raise ValueError(f"{len(missing)} annotated sentences missing from source")
    if args.review_dir:
        args.review_dir.mkdir(parents=True, exist_ok=True)
    server.load()
    results = []
    for case in cases:
        digest = case["sentence_sha256"]
        analysis = server.analyze_text(case["text"])
        expectations = gold.get(digest, {}).get("expectations", [])
        result = {key: value for key, value in case.items() if key != "text"}
        result.update(words=len(case["text"].split()),
                      review_status=gold.get(digest, {}).get("review", "not-reviewed"),
                      structural_errors=structural_errors(analysis),
                      semantic_checks=len(expectations),
                      semantic_errors=check_expectations(analysis.chunks, expectations))
        if args.review_dir and case["split"] == "development":
            (args.review_dir / f"{digest}.json").write_text(json.dumps({
                **case, "tokens": list(enumerate(analysis.source_tokens)), "chunks": analysis.chunks,
            }, ensure_ascii=False, indent=2))
        results.append(result)
    print(json.dumps({"source": args.source, "html_sha256": hashlib.sha256(raw).hexdigest(),
                      "provenance": "Third-party transcription; not publisher-verified; annotations are assistant-reviewed, not independent gold",
                      "selection": "Deduplicated prose sentences, >=5 words, terminal punctuation; headings, instructions, opening hours and advertisement block excluded",
                      "split_policy": "Historical SHA256 partition retained for reproducibility; all 100 sentences now exposed to assistant review, not heldout or independent blind gold",
                      "cases": results}, indent=2))
    raise SystemExit(1 if any(case["structural_errors"] or case["semantic_errors"] for case in results) else 0)


if __name__ == "__main__":
    main()
