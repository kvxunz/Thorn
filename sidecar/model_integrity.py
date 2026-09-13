from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_directory(directory, manifest):
    directory = Path(directory)
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("invalid model lock manifest")
    for name, expected in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("model lock must contain plain filenames")
        with (directory / name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"model integrity mismatch: {name}; reinstall the pinned model")


def verify_benepar():
    import nltk.data

    manifest = json.loads(Path(__file__).with_name("model-lock.json").read_text())
    location = nltk.data.find(f"models/{manifest['model']}")
    verify_directory(str(location), manifest)


def verify_ollama(payload, expected):
    for model in payload.get("models", []):
        if model.get("name") == expected["name"] and model.get("digest") == expected["digest"]:
            return
    raise ValueError("default translation model missing or digest differs from model-lock.json")


if __name__ == "__main__":
    import urllib.request

    manifest = json.loads(Path(__file__).with_name("model-lock.json").read_text())
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
        verify_ollama(json.load(response), manifest["ollama"])
    print("Default translation model digest verified")
