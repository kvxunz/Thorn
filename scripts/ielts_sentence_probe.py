import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.current is not None:
            self.parts.append(" ".join("".join(self.current).split()))
            self.current = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    args = parser.parse_args()
    raw = args.html.read_bytes()
    document = Paragraphs()
    document.feed(raw.decode())
    prefixes = ["The scent she carried", "When you have looked", "Attached to the Booking",
                "Taree offers", "In the third"]
    sentences = [sentence for paragraph in document.parts
                 for sentence in re.split(r"(?<=[.!?])\s+", paragraph)]
    selected = []
    for prefix in prefixes:
        matches = {sentence for sentence in sentences if sentence.startswith(prefix)}
        if len(matches) != 1:
            raise ValueError(f"source selector must be unique: {prefix} ({len(matches)})")
        selected.append(matches.pop())
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sidecar"))
    import server

    server.load()
    results = []
    for index, text in enumerate(selected):
        analysis = server.analyze_text(text)

        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get("children") or [])

        nodes = list(walk(analysis.chunks))
        errors = []
        if not nodes or analysis.evidence.relations.diagnostics:
            errors.append("empty or cyclic analysis")
        covered = [token for node in analysis.chunks for token in range(node["s"], node["e"])]
        if covered != list(range(len(analysis.source_tokens))):
            errors.append("top-level token coverage")
        if index == 0:
            relatives = [node for node in nodes if node["text"].rstrip(".") == "they were looking for"]
            if not relatives or any(node["role"] != "clause-relative" for node in relatives):
                errors.append("zero relative misclassified")
            if not any(node["role"] == "complement" and relatives
                       and relatives[0] in (node.get("children") or []) for node in nodes):
                errors.append("relative lost nominal owner")
        results.append({"id": f"cambridge4-{index + 1}", "words": len(text.split()),
                        "sentence_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "checks": "nonempty acyclic analysis and token coverage; first case also checks relative role/owner",
                        "errors": errors})
    print(json.dumps({"source": "https://engnovate.com/ielts-reading-tests/cambridge-ielts-04-general-training-reading-test-2/",
                      "provenance": "Third-party transcription labelled Cambridge IELTS 4 GT Test 2, not publisher-verified or independently annotated; full text kept outside repository",
                      "html_sha256": hashlib.sha256(raw).hexdigest(), "cases": results}, indent=2))
    raise SystemExit(1 if any(result["errors"] for result in results) else 0)


if __name__ == "__main__":
    main()
