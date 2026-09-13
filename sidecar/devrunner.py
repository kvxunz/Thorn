"""Hold the parser in memory so a verification run costs seconds, not a minute.

`en_core_web_trf` plus `benepar_en3` take about 70 seconds to load, and every
`uv run --script` paid that again: a single change to a chunking rule meant
several minutes of waiting before the corpus could say whether it helped.  The
models are the only expensive part and they never change, so a worker keeps
them and the scripts become clients.

    tmux new-session -d -s thorn-dev 'uv run --locked --script server.py --tool devrunner.py -- --serve'
    python3 devrunner.py golden_parse_checks.py
    python3 devrunner.py corpus_report.py --constructions

The client is stdlib-only and runs under plain `python3` on purpose -- routing
it through `uv` would reintroduce an environment resolve on every call.

Staleness is the hazard this design has to answer for, because a suite that
silently tests the code the worker loaded an hour ago is worse than a slow one:
it reports green for work that was never run.  So every job *purges* all sidecar
modules from `sys.modules` and lets the script import them again from disk.
Purging rather than reloading means no import order to keep in step with the
code -- a new module cannot be forgotten here, because nothing here names them
one by one.  The loaded `nlp` survives the purge in this module and is injected
back before the script runs.
"""
import json
import os
import socket
import sys
import traceback

SOCKET_PATH = "/tmp/thorn-devrunner.sock"
SIDECAR_DIR = os.path.dirname(os.path.abspath(__file__))
START_HINT = (
    "tmux new-session -d -s thorn-dev "
    "-c {dir} 'uv run --locked --script server.py --tool devrunner.py -- --serve'"
)


# ------------------------------------------------------------------- worker


def _purge_sidecar_modules():
    """Drop every module loaded from the sidecar directory.

    The next `import server` then re-reads the source, so a job can never run
    against an edit the worker has not seen.  Modules outside this directory
    (spacy, torch, benepar) are left alone -- they are what the worker exists
    to keep.
    """
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and os.path.dirname(os.path.abspath(path)) == SIDECAR_DIR:
            del sys.modules[name]


class _StreamWriter:
    """Stands in for stdout/stderr and forwards writes down the socket."""

    def __init__(self, connection, stream):
        self._connection = connection
        self._stream = stream

    def write(self, text):
        if text:
            _send(self._connection, {"stream": self._stream, "data": text})
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def _send(connection, message):
    connection.sendall((json.dumps(message) + "\n").encode())


def _run_job(connection, request, nlp):
    import runpy

    path = request["path"]
    saved = sys.argv, sys.stdout, sys.stderr, os.getcwd()
    sys.argv = [path, *request.get("argv", [])]
    sys.stdout = _StreamWriter(connection, "out")
    sys.stderr = _StreamWriter(connection, "err")
    code = 0
    try:
        os.chdir(request.get("cwd") or SIDECAR_DIR)
        _purge_sidecar_modules()
        # Import server here, before the script does, so the injection below
        # lands on the instance the script will get from sys.modules. `load()`
        # is idempotent, so the script's own call to it returns immediately.
        import server

        server.nlp = nlp
        runpy.run_path(path, run_name="__main__")
    except SystemExit as exit_request:
        code = exit_request.code if isinstance(exit_request.code, int) else 0
    except BaseException:  # noqa: BLE001 -- a failing job must not kill the worker
        traceback.print_exc()
        code = 1
    finally:
        sys.argv, sys.stdout, sys.stderr, cwd = saved
        os.chdir(cwd)
    return code


def serve():
    print("loading models…", file=sys.stderr, flush=True)
    sys.path.insert(0, SIDECAR_DIR)
    import server

    server.load()
    nlp = server.nlp

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(SOCKET_PATH)
    listener.listen(1)
    print(f"ready on {SOCKET_PATH}", file=sys.stderr, flush=True)

    while True:
        connection, _ = listener.accept()
        with connection:
            try:
                request = json.loads(connection.makefile("r").readline())
            except (ValueError, OSError):
                continue
            code = _run_job(connection, request, nlp)
            try:
                _send(connection, {"exit": code})
            except OSError:
                pass  # client hung up mid-run; the next job is unaffected


# ------------------------------------------------------------------- client


def run_client(argv):
    if not argv:
        raise SystemExit(f"usage: python3 devrunner.py <script.py> [args...]\n"
                         f"start the worker with:\n  "
                         f"{START_HINT.format(dir=SIDECAR_DIR)}")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError):
        raise SystemExit(
            f"no worker on {SOCKET_PATH}. Start one with:\n  "
            f"{START_HINT.format(dir=SIDECAR_DIR)}"
        ) from None
    _send(connection, {
        "path": os.path.abspath(argv[0]),
        "argv": argv[1:],
        "cwd": os.getcwd(),
    })
    streams = {"out": sys.stdout, "err": sys.stderr}
    with connection.makefile("r") as incoming:
        for line in incoming:
            message = json.loads(line)
            if "exit" in message:
                return message["exit"]
            stream = streams[message["stream"]]
            stream.write(message["data"])
            stream.flush()
    return 1  # worker died mid-job: never report a job that vanished as passing


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        raise SystemExit(run_client(sys.argv[1:]))
