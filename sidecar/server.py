# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "spacy==3.7.5",
#     "benepar==0.2.0",
#     "torch==2.13.0",
#     "transformers==4.49.0",  # direct pin; see the note under this block
#     "protobuf==3.20.3",
#     "sentencepiece==0.2.2",
#     "fastapi==0.140.13",
#     "uvicorn==0.52.0",
#     "spacy-transformers==1.3.9",
#     "numpy==1.26.4",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
# `transformers` is pinned although nothing here imports it: the
# en_core_web_trf weights are read through it, and the window its consumers
# allow is wide (benepar 0.2.0 `>=4.2.2`, spacy-transformers 1.3.9 `<4.50.0`),
# so an unpinned resolve would silently change the parse. Move it only with
# the snapshot in hand: `uv run --script server.py --tool tree_snapshot.py`.
"""Thorn local language sidecar: deterministic spaCy + Benepar chunks.

Run: uv run --script server.py [--port 48620] [--idle-exit 120]
"""
import argparse
import hmac
import os
import re
import signal
import threading
import time
from dataclasses import dataclass

from chunk_rules import prepare_parse_text
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from teaching_projection import project_document
from teaching_tree import TeachingEvidence, TokenSource

SPACY_MODEL = "en_core_web_trf"
BENEPAR_MODEL = "benepar_en3"
PARSE_PROTOCOL_VERSION = 4

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
    if nlp is not None:
        # Already loaded. `devrunner` reimports this module for every job to
        # guarantee the code under test is the code on disk, and hands the one
        # loaded pipeline back afterwards. Without this guard each job builds a
        # second pipeline and drops the one it was given -- slower every time,
        # and a fresh copy of the transformer weights per job.
        return
    # Imported here, not at module scope: torch/transformers/benepar cost ~1 s
    # warm and ~15 s once the OS has evicted their pages, and nothing above this
    # line needs them. Keeping the import inside the one function that loads a
    # model is what lets `service_checks.py` exercise the request gate with only
    # fastapi installed -- an auth check that cannot run in CI is an auth check
    # that runs when someone remembers. `import benepar` must stay ahead of
    # `add_pipe("benepar")`: importing it is what registers the spaCy factory.
    import benepar  # noqa: F401  (registers the spaCy pipeline component)
    import spacy
    from model_integrity import verify_benepar

    # Model installation is an explicit setup action.  Starting the app must
    # never trigger a network download or mutate the user's model cache.
    verify_benepar()
    nlp = spacy.load(SPACY_MODEL)
    if "benepar" not in nlp.pipe_names:
        nlp.add_pipe("benepar", config={"model": BENEPAR_MODEL})


def _prepare_document(text):
    from syntax_reconciliation import reconcile_document

    prepared = prepare_parse_text(text)
    if not prepared.parser:
        raise ValueError("source contains no parseable text")
    with nlp_inference_lock:
        doc = nlp(prepared.parser)
        reconcile_document(doc)
    parser_offsets = [
        (token.idx, token.idx + len(token.text))
        for token in doc
    ]
    offsets = prepared.source_token_offsets(parser_offsets)
    return prepared, doc, offsets


@dataclass(frozen=True)
class ParseAnalysis:
    chunks: list
    source_tokens: list[str]
    evidence: TeachingEvidence
    boundary_decisions: tuple[dict, ...]


def analyze_text(text, *, trace=False, policy=None):
    prepared, doc, offsets = _prepare_document(text)
    evidence = TeachingEvidence.from_doc(doc)
    source = TokenSource(text=prepared.surface, token_offsets=offsets)
    chunks, decisions = project_document(doc, source, evidence, trace=trace, policy=policy)
    return ParseAnalysis(chunks, [
        prepared.surface[start:end] for start, end in offsets
    ], evidence, decisions)


def parse_text(text):
    analysis = analyze_text(text)
    return analysis.chunks, analysis.source_tokens


# ---------------------------------------------------------------- server

app = FastAPI()


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


@app.get("/health", dependencies=[Depends(require_auth)])
def health():
    return {
        "ok": nlp is not None,
        "parseProtocolVersion": PARSE_PROTOCOL_VERSION,
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
    # The models cost ~3.2 GB resident. Reloading them is 3.2 s warm but ~19 s
    # once the OS has evicted torch's pages -- and eviction happens exactly when
    # memory is tight, i.e. when everything else is slow too. Two minutes was
    # too eager to be a study tool: reading one paragraph between two lookups
    # already exceeded it. Ten minutes covers a reading session and still
    # releases the memory when the app is genuinely idle. The app passes this
    # explicitly (Sidecar.idleExitSeconds); keep the two in step.
    ap.add_argument("--idle-exit", type=int, default=600)
    ap.add_argument(
        "--install-models",
        action="store_true",
        help="explicitly install Benepar data, then exit",
    )
    ap.add_argument(
        "--check-regressions",
        action="store_true",
        help="run real-model regression tests in the server dependency environment",
    )
    ap.add_argument("--evaluate-relations", action="store_true", help="evaluate frozen relation checks without changing their expectations")
    ap.add_argument("--evaluate-external", metavar="CONLLU", help="evaluate the frozen external EWT sample")
    ap.add_argument("--benchmark", action="store_true", help="measure parser startup, stages and peak memory in fresh subprocesses")
    ap.add_argument("--tool", choices=["tree_snapshot.py", "corpus_report.py", "probe_sentence.py", "devrunner.py", "golden_parse_checks.py", "service_checks.py"])
    ap.add_argument("tool_args", nargs=argparse.REMAINDER)
    ap.add_argument("--analyze", metavar="TEXT", help="print local syntax relations and teaching tree as JSON")
    args = ap.parse_args()
    if args.tool:
        import runpy
        import sys
        from pathlib import Path

        tool = Path(__file__).resolve().with_name(args.tool)
        sys.argv = [str(tool), *(args.tool_args[1:] if args.tool_args[:1] == ["--"] else args.tool_args)]
        runpy.run_path(str(tool), run_name="__main__")
        raise SystemExit(0)
    if args.benchmark:
        import json
        from pathlib import Path

        from benchmark import run

        root = Path(__file__).resolve().parent
        print(json.dumps(run(root, root / "benchmark_cases.json", 5, 3), indent=2))
        raise SystemExit(0)
    if args.evaluate_external:
        from pathlib import Path

        from external_evaluation import evaluate_corpus

        load()
        raise SystemExit(evaluate_corpus(Path(args.evaluate_external), analyze_text))
    if args.evaluate_relations:
        from relation_evaluation import run

        load()
        raise SystemExit(run(analyze_text))
    if args.analyze is not None:
        import json
        from dataclasses import asdict

        load()
        analysis = analyze_text(args.analyze, trace=True)
        print(json.dumps({
            "sourceTokens": analysis.source_tokens,
            "relations": asdict(analysis.evidence.relations),
            "boundaryDecisions": analysis.boundary_decisions,
            "chunks": analysis.chunks,
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if args.check_regressions:
        import unittest

        suite = unittest.defaultTestLoader.loadTestsFromNames([
            "golden_parse_checks", "relation_parse_checks",
        ])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
    if args.install_models:
        import benepar
        from model_integrity import verify_benepar

        benepar.download(BENEPAR_MODEL)
        verify_benepar()
        raise SystemExit(0)
    if not auth_token:
        raise SystemExit("THORN_SIDECAR_TOKEN is required")
    load()
    threading.Thread(target=idle_watchdog, args=(args.idle_exit,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
