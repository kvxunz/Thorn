import ast
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "sidecar"
modules = {path.stem for path in root.glob("*.py")}
pending, included = ["server"], set()
while pending:
    name = pending.pop()
    if name in included:
        continue
    included.add(name)
    for node in ast.walk(ast.parse((root / f"{name}.py").read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            pending.extend({node.module.split(".")[0]} & modules)
        elif isinstance(node, ast.Import):
            pending.extend({alias.name.split(".")[0] for alias in node.names} & modules)

with tempfile.TemporaryDirectory(prefix="thorn-runtime-") as directory:
    stage = Path(directory)
    for filename in [*[f"{module}.py" for module in included], "server.py.lock", ".python-version",
                     "model-lock.json", "relation_holdout.json", "external_eval_manifest.json", "benchmark_cases.json"]:
        shutil.copy2(root / filename, stage / filename)
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in stage.iterdir()}
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environment.pop("PYTHONPATH", None)
    command = ["uv", "run", "--locked", "--script", str(stage / "server.py")]
    result = subprocess.run(command + ["--analyze", "The people waiting outside looked tired."],
                            cwd=stage, env=environment, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    payload = json.loads(result.stdout)
    if not payload["chunks"] or not payload["relations"]["edges"] or not payload["boundaryDecisions"]:
        raise ValueError("isolated runtime produced empty analysis")
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in stage.iterdir() if path.is_file()}
    if before != after or list(stage.rglob("__pycache__")):
        raise ValueError("runtime mutated signed bundle contents")
    script = stage / "server.py"
    script.write_text(script.read_text().replace('"numpy==1.26.4"', '"numpy>=1.26.4,<2"'))
    rejected = subprocess.run(["uv", "run", "--locked", "--script", str(script), "--help"],
                              cwd=stage, env=environment, capture_output=True, text=True, timeout=180, check=False)
    if rejected.returncode == 0:
        raise ValueError("stale lock was accepted")
    if "lockfile" not in rejected.stderr.lower() or "--locked" not in rejected.stderr:
        raise ValueError(f"failed for a reason other than stale lock: {rejected.stderr}")
    if hashlib.sha256((stage / "server.py.lock").read_bytes()).hexdigest() != before["server.py.lock"]:
        raise ValueError("stale lock was rewritten")
    (stage / "server.py.lock").unlink()
    missing = subprocess.run(["uv", "run", "--offline", "--locked", "--script", str(script), "--help"],
                             cwd=stage, env=environment, capture_output=True, text=True, timeout=30, check=False)
    if missing.returncode == 0 or (stage / "server.py.lock").exists():
        raise ValueError("missing lock was accepted or recreated")
    print("PASS: isolated locked runtime; nonempty parse; bundle unchanged; stale and missing locks rejected")
