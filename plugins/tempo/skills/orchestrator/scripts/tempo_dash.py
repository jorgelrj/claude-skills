#!/usr/bin/env python3
"""TEMPO dashboard: a local, read-only web page of the TEMPO tasks on this machine.

It reads each task folder: state.json, events.jsonl (the history tempo_state.py and
tempo_run.py append), procs.json and the documents. It writes nothing there. A task from
before 0.22.0 has no events.jsonl and shows only the agents still in flight. The server
listens on 127.0.0.1 only and answers GET only. A process row never carries its command
line (it can hold passwords), and the files that repeat it (procs.json, procs.log, procs/) are never served.

Usage: tempo_dash.py <command> [--port N] [--root DIR ...] [--allow-host NAME ...]
  start    start the server detached from this shell, or find the one already running.
           Prints DASH: http://127.0.0.1:<port>/. Log: <cache>/dash.log, record: <cache>/dash.json
           (<cache> is $TEMPO_CACHE or ~/.cache/tempo). Exit 1 when the port is taken by something else.
  stop     stop the recorded server
  status   print the URL, or DASH: not running
  serve    run in the foreground (port 0 picks a free port and prints it)
  --port defaults to 4310. --root adds a folder: its .tempo/*/ and */.tempo/*/ tasks are listed
  next to the registered ones (tempo_procs.py registry). --allow-host accepts one more Host header,
  with or without a port, such as the name `tailscale serve` forwards (my-mac.tailnet.ts.net).
Endpoints:
  /                          dashboard.html, the file next to this script
  /api/tasks[?hours=N]       tasks RUNNING or WAITING-ON-JORGE, or changed in the last N hours (24; 0: all)
  /api/file?tag=T&path=P     one document of a listed task, as text (the last 512 KB)
Exit 0 ok, 1 error.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempo_os  # noqa: E402
import tempo_procs  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = tempo_procs.HOME_CACHE / "dash.json"
SUFFIXES = (".md", ".txt", ".log", ".json", ".jsonl", ".diff")
LIVE = ("RUNNING", "WAITING-ON-JORGE")
# Where the templates state a verdict: the line under "## N Result" (findings, integration, qa),
# or "- Result: X" (work report, spec rules check, repro).
VERDICT = re.compile(r"^## \d+ Result\s*\n[-\s]*([A-Z]+(?: [A-Z]+)*)|^- Result:\s*([A-Z]+(?: [A-Z]+)*)", re.M)
META, MODELS, SCANNED = {}, {}, [0.0]  # agent id -> metadata file, agent id -> model, time of the last scan
OWNED = [0.0, set(), set()]  # time of the last look, folders of live sessions, folders any session registered


def text(p, root=None, tail=False, cap=512 * 1024):
    """Up to cap bytes of a regular file (inside root, when given), else OSError: a FIFO would block every
    poll, a huge file would cost it seconds, a symlink could lead out of the task folder."""
    p = Path(p).resolve()
    if root is not None and not p.is_relative_to(Path(root).resolve()):
        raise OSError(f"{p}: outside {root}")
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))  # O_NONBLOCK: opening a FIFO returns at once (Windows has none)
    with open(fd, "rb") as f:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"{p}: not a regular file")
        f.seek(max(0, st.st_size - cap) if tail else 0)
        return f.read(cap).decode("utf-8", "replace")


def load_state(d):
    for again in (True, False):
        try:
            return json.loads(text(d / "state.json", d))
        except ValueError:  # read mid-write: plugin versions before 0.22.0 did not write it atomically
            if again:
                time.sleep(0.05)
        except OSError:
            break
    return None


def events(d):
    """The parsed lines of events.jsonl, or None when the task has none."""
    try:
        lines = text(d / "events.jsonl", d, tail=True, cap=8 << 20).splitlines()
    except OSError:
        return None
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a line still being written
    return [e for e in out if isinstance(e, dict)]


HIDDEN = ("procs.json", "procs.log", "procs")  # the ledger, the teardown log, the service logs: all hold command lines


def hidden(d, p):
    """True when p is, or sits under, one of HIDDEN. By file identity, not by name: a case-insensitive
    volume opens procs.json under other spellings."""
    for x in (p, *p.parents):
        if x == d:
            return False
        for h in HIDDEN:
            try:
                if os.path.samefile(x, d / h):
                    return True
            except OSError:
                pass  # this task has no such file
    return False


def inside(d, rel):
    """<d>/<rel> resolved, when it stays in the task folder and is a file the dashboard may show; else None."""
    try:
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            return None
        p = (d / rel).resolve()  # the checks run on the target, so a symlink cannot lead out or to a hidden file
        ok = p.is_relative_to(d) and p.suffix.lower() in SUFFIXES and p.is_file() and not hidden(d, p)
        return p if ok else None
    except (OSError, ValueError):
        return None


def owned():
    """Task folders whose Claude Code session is alive, and those any session registered. A resumed task
    has a new session, so the pid in .claim says nothing. One process listing every 10 s."""
    if time.time() - OWNED[0] > 10:
        table, live, known = tempo_procs.snapshot(), set(), set()
        for f in (tempo_procs.SESSIONS.glob("*.json") if tempo_procs.SESSIONS.exists() else []):
            try:
                dirs = {str(x) for x in json.loads(f.read_text(encoding="utf-8"))}
            except (OSError, ValueError, TypeError):
                continue
            known |= dirs
            if f.stem.isdigit() and tempo_procs.is_claude(int(f.stem), table):
                live |= dirs
        OWNED[:] = [time.time(), live, known]
    return OWNED[1], OWNED[2]


def model(aid):
    if aid not in MODELS:
        if aid not in META and time.time() - SCANNED[0] > 30:  # a new agent's metadata: scan again, at most every 30 s
            SCANNED[0] = time.time()
            for f in glob.glob(str(Path.home() / ".claude/projects/*/*/subagents/agent-*.meta.json")):
                META[Path(f).name[6:-10]] = f
        try:
            meta = json.loads(text(META[aid]))
            MODELS[aid] = meta.get("pickedEffortModel") or meta.get("model")
        except Exception:
            return None
    return MODELS[aid]


def agents(st, evs):
    out, live = [], {}  # live: id -> rows not ended yet
    for e in evs or []:
        mine = e.get("ev") == "agent"
        if mine and e.get("action") == "start":
            out.append({"id": e.get("id"), "label": e.get("label"), "output": e.get("output"),
                        "prompt": e.get("prompt"), "started": e.get("at"), "ended": None})
            live.setdefault(str(e.get("id")), []).append(out[-1])
        for aid in ([e.get("id")] if mine and e.get("action") == "done" else e.get("closed") or []):
            for x in live.pop(str(aid), []):
                x["ended"] = e.get("at")
    seen = {x["id"] for x in out}
    # In flight with no start event: the task, or this agent, started before events.jsonl existed.
    out = [{"id": k, "label": v.get("label"), "output": v.get("output"), "prompt": v.get("prompt"),
            "started": v.get("started"), "ended": None}
           for k, v in (st.get("agents") or {}).items() if k not in seen] + out
    for x in out:
        x["model"] = model(str(x["id"]))
    return out


def runs(evs):
    out = []
    for e in [e for e in evs or [] if e.get("ev") == "run"][-20:]:
        rd = Path(str(e.get("dir")))
        state, result = "gone", None
        # only a folder tempo_run.py made: a line in events.jsonl must not point the server at other files
        if rd.name == e.get("id") and rd.name.startswith("tempo-run-") and rd.is_dir():
            try:
                state, result = "done", (text(rd / "result.txt", rd, cap=65536).splitlines() or [None])[0]
            except OSError:  # no result yet
                try:
                    waits = text(rd / "state", rd, cap=64).startswith("waiting")
                except OSError:
                    waits = False
                state = "waiting for a slot" if waits else "running"
        out.append({"id": e.get("id"), "label": e.get("label"), "heavy": bool(e.get("heavy")),
                    "started": e.get("at"), "state": state, "result": result})
    return out


def procs(d):
    # Field by field: a ledger row's "command" holds database passwords and never leaves this function.
    return [{"label": r.get("label"), "pid": r.get("pid"),
             "alive": not r.get("stopped") and tempo_procs.alive(r.get("pid")),
             "started": r.get("started_at"), "stopped": r.get("stopped"), "log": r.get("log")}
            for r in tempo_procs.load_ledger(d)]


def results(d):
    out = {}
    for p in sorted([*d.glob("*.md"), *d.glob("review/*.md"), *d.glob("qa/*.md")]):
        try:
            m = VERDICT.search(text(p, d))
        except OSError:
            continue
        if m:
            out[str(p.relative_to(d))] = m.group(1) or m.group(2)
    return out


def files(d):
    out = []
    for base, dirs, names in os.walk(d):
        rel = Path(base).relative_to(d)
        top = not rel.parts  # os.walk gives the names on disk, so the top-level HIDDEN ones are skipped by name
        dirs[:] = [] if len(rel.parts) >= 2 else [x for x in dirs if x != "worktrees" and not (top and x.lower() in HIDDEN)]
        out += [str(rel / n) for n in names if Path(n).suffix.lower() in SUFFIXES and not (top and n.lower() in HIDDEN)]
    return sorted(out)[:300]


def task(d, st, mtime):
    evs = events(d)
    w = st.get("waiting")
    wf = (inside(d, w) or inside(d, Path(w).name)) if w else None  # a bare name, or a path that ends in it
    try:
        qa = [x for x in text(d / "qa/progress.md", d, tail=True, cap=65536).splitlines() if x.strip()]
    except OSError:
        qa = []
    live, known = owned()
    alive = True if str(d) in live else False if str(d) in known or (d / ".claim").exists() else None
    return {"tag": tempo_procs.tag(d), "task": d.name, "dir": str(d), "checkout": d.parent.parent.name,
            "mtime": mtime, "alive": alive, "state": st,
            "agents": agents(st, evs), "runs": runs(evs), "procs": procs(d),
            "waiting_text": "\n".join(text(wf).splitlines()[:30]) if wf else None,
            "qa_progress": qa[-1] if qa else None, "results": results(d), "files": files(d)}


def tasks(roots, hours):
    queue = [(c, False) for c in tempo_procs.registry().values()]
    for r in roots:
        queue += [(c, False) for pat in (".tempo/*/", "*/.tempo/*/") for c in glob.glob(os.path.join(glob.escape(r), pat))]
    out = {}
    while queue:
        c, forced = queue.pop(0)
        try:  # one broken folder never breaks the list
            d = Path(c).resolve()
            st = None if str(d) in out else load_state(d)
            if st is None:
                continue
            mtime = (d / "state.json").stat().st_mtime
            if forced or not hours or st.get("status") in LIVE or time.time() - mtime < hours * 3600:
                out[str(d)] = task(d, st, mtime)
                queue += [(ch["folder"], True) for ch in (st.get("children") or {}).values() if ch.get("folder")]
        except Exception:
            continue
    return [out[k] for k in sorted(out)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype="text/plain; charset=utf-8"):
        body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                     ("X-Content-Type-Options", "nosniff")):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def __getattr__(self, name):  # do_POST, do_PUT and every other method but GET
        if name.startswith("do_"):
            return lambda: self.reply(405, "GET only\n")
        raise AttributeError(name)

    def do_GET(self):
        port = self.server.server_address[1]
        host = self.headers.get("Host") or ""
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}") and host.rsplit(":", 1)[0].lower() not in self.server.hosts:
            return self.reply(403, "forbidden host\n")  # a web page that rebinds its own name to 127.0.0.1
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/tasks":
            hours = q.get("hours", ["24"])[0]
            found = tasks(self.server.roots, float(hours) if hours.replace(".", "", 1).isdigit() else 24)
            self.server.tags.update((t["tag"], t["dir"]) for t in found)
            body = {"now": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "host": socket.gethostname(), "tasks": found}
            return self.reply(200, json.dumps(body, ensure_ascii=False), "application/json")
        if u.path == "/api/file":
            d = self.server.tags.get(q.get("tag", [""])[0])
            p = inside(Path(d), q.get("path", [""])[0]) if d else None
            if not p:
                return self.reply(404, "not found\n")
            with open(p, "rb") as f:
                f.seek(max(0, p.stat().st_size - 512 * 1024))
                return self.reply(200, f.read())
        if u.path == "/":
            page = HERE / "dashboard.html"
            if page.is_file():
                return self.reply(200, page.read_bytes(), "text/html; charset=utf-8")
            return self.reply(404, "dashboard.html is missing next to tempo_dash.py\n")
        self.reply(404, "not found\n")


def server(port, roots, hosts=()):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.roots, srv.tags = [str(Path(r).resolve()) for r in roots], {}  # tags: the folders /api/file may read
    srv.hosts = {h.lower() for h in hosts}  # opt-in names a proxy forwards, e.g. tailscale serve
    return srv


def url(port):
    return f"DASH: http://127.0.0.1:{port}/"


def answers(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close()
        return True
    except OSError:
        return False


def recorded():
    """dash.json, when its pid still is a dashboard server (the pid may have been reused); else None."""
    try:
        rec = json.loads(RECORD.read_text(encoding="utf-8"))
        cmd = (tempo_procs.snapshot().get(int(rec["pid"])) or {}).get("command", "") if tempo_os.WINDOWS else \
            subprocess.run(["ps", "-o", "command=", "-p", str(int(rec["pid"]))], capture_output=True, text=True).stdout
        return rec if "tempo_dash.py" in cmd and int(rec["port"]) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def start(port, roots, hosts=()):
    rec = recorded()
    if rec and answers(rec["port"]):
        print(url(rec["port"]))
        return 0
    if answers(port):
        print(f"tempo_dash: port {port} is taken by something else; pass --port N", file=sys.stderr)
        return 1
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    # No TEMPO_TAG, TEMPO_OWNER, TEMPO_SVC or TEMPO_RUN: the server is no task's process, so no teardown or
    # SessionEnd hook stops it. TEMPO_CACHE stays, so it reads the registry this command wrote its record to.
    env = {k: v for k, v in os.environ.items() if not k.startswith("TEMPO_") or k == "TEMPO_CACHE"}
    roots = [str(Path(r).resolve()) for r in roots]
    args = [sys.executable, os.path.abspath(__file__), "serve", "--port", str(port)] + (["--root"] + roots if roots else []) + \
        [x for h in hosts for x in ("--allow-host", h)]
    with open(RECORD.parent / "dash.log", "a", encoding="utf-8") as log:
        p = tempo_os.spawn(args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=RECORD.parent)
    end = time.monotonic() + 10
    while time.monotonic() < end:
        rec = recorded()  # written by the server that got the port: ours, or a start that ran at the same moment
        if rec and answers(rec["port"]):
            print(url(rec["port"]))
            return 0
        if p.poll() is not None and not answers(port):
            break
        time.sleep(0.1)
    if p.poll() is None:
        p.kill()
    print(f"tempo_dash: the server did not start; see {RECORD.parent / 'dash.log'}", file=sys.stderr)
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_dash.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["start", "stop", "status", "serve"])
    p.add_argument("--port", type=int, default=4310)
    p.add_argument("--root", nargs="+", action="extend", default=[])
    p.add_argument("--allow-host", action="append", default=[])
    a = p.parse_args(argv)
    if a.cmd == "start":
        return start(a.port, a.root, a.allow_host)
    if a.cmd == "serve":
        try:
            srv = server(a.port, a.root, a.allow_host)
        except OSError as e:
            sys.exit(f"tempo_dash: cannot listen on 127.0.0.1:{a.port}: {e}")
        if a.port:  # port 0 is a test or a one-off look: it never replaces the recorded server
            RECORD.parent.mkdir(parents=True, exist_ok=True)
            RECORD.write_text(json.dumps({"pid": os.getpid(), "port": a.port, "roots": srv.roots}), encoding="utf-8")
        print(url(srv.server_address[1]), flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    rec = recorded()
    if a.cmd == "stop" and rec:
        tempo_os.kill(rec["pid"])
        RECORD.unlink(missing_ok=True)
        print("DASH: stopped")
    else:
        print(url(rec["port"]) if rec and answers(rec["port"]) else "DASH: not running")
    return 0


if __name__ == "__main__":
    sys.exit(main())
