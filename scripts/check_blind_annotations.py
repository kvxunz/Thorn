import argparse
import hashlib
import json
from pathlib import Path


def validate(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("annotations must be a nonempty list")
    grouped = {}
    for row in rows:
        for field in ("id", "text", "source", "annotator", "annotated_at", "main_predicate"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"missing annotation field: {field}")
        if row.get("model_output_seen") is not False:
            raise ValueError("blind annotations must explicitly declare model_output_seen=false")
        for field in ("subjects", "objects_or_complements", "modifiers", "coordination_groups",
                      "acceptable_alternatives", "uncertainties"):
            if not isinstance(row.get(field), list):
                raise TypeError(f"missing annotation list: {field}")
        text = row["text"]
        for phrase in [row["main_predicate"], *row["subjects"], *row["objects_or_complements"]]:
            if not isinstance(phrase, str) or not phrase or phrase not in text:
                raise ValueError("annotated phrase must occur in the source text")
        for modifier in row["modifiers"]:
            if not isinstance(modifier, dict) or not modifier.get("reason"):
                raise ValueError("modifier requires an attachment reason")
            for field in ("phrase", "modifies"):
                phrase = modifier.get(field)
                if not isinstance(phrase, str) or not phrase or phrase not in text:
                    raise ValueError("modifier and its owner must occur in source text")
        for group in row["coordination_groups"]:
            if not isinstance(group, list) or len(group) < 2 or any(
                not isinstance(phrase, str) or not phrase or phrase not in text for phrase in group
            ):
                raise ValueError("coordination group requires at least two source phrases")
        grouped.setdefault(row["id"], []).append(row)
    disagreements = []
    for case_id, annotations in grouped.items():
        if len(annotations) != 2 or len({row["annotator"] for row in annotations}) != 2:
            raise ValueError("each sentence requires exactly two distinct annotators")
        if len({row["text"] for row in annotations}) != 1:
            raise ValueError("annotators must use identical source text")
        fields = ("main_predicate", "subjects", "objects_or_complements", "modifiers",
                  "coordination_groups", "acceptable_alternatives", "uncertainties")
        differences = [field for field in fields if annotations[0][field] != annotations[1][field]]
        if differences:
            disagreements.append({"id": case_id, "fields": differences})
    return {"sentences": len(grouped), "annotations": len(rows), "disagreements": disagreements,
            "status": "awaiting-adjudication" if disagreements else "format-valid-awaiting-independent-verification",
            "limitation": "Validates declared metadata and source phrases only; cannot establish human identity or blindness"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    raw = args.annotations.read_bytes()
    report = validate(json.loads(raw))
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["disagreements"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
