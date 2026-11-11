"""Tests for the dashboard server (tempo_dash.py) and the event log tempo_state.py and tempo_run.py feed it.

Run: python3 -m unittest discover -s <plugin>/tests -v
Everything happens in temp folders; TEMPO_CACHE points at one, so the real ~/.cache/tempo is never touched.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "orchestrator" / "scripts"
CACHE = tempfile.mkdtemp(prefix="tempo-dash-test-")
os.environ["TEMPO_CACHE"] = CACHE  # before the import: tempo_procs reads it once
sys.path.insert(0, str(SCRIPTS))
import tempo_dash  # noqa: E402
import tempo_procs  # noqa: E402

KEYS = {"tag", "task", "dir", "checkout", "mtime", "alive", "state", "agents", "runs", "procs",
        "waiting_text", "qa_progress", "results", "files"}


def tearDownModule():
    shutil.rmtree(CACHE, ignore_errors=True)


def script(name, *args, cache, **env):
    """Run one of the scripts as a subprocess, on a temp cache and with no owning session."""
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True,
                          env={**os.environ, "TEMPO_CACHE": str(cache), "TEMPO_OWNER": "0", **env})


def make_task(d, status="RUNNING", **extra):
    d.mkdir(parents=True)
    state = {"version": 1, "task": d.name, "stage": "BUILD", "status": status, "waiting": None,
             "agents": {}, "children": {}, **extra}
    (d / "state.json").write_text(json.dumps(state))
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-dash-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reg = tempo_procs.REGISTRY
        tempo_procs.REGISTRY = self.tmp / "cache" / "tasks"  # an empty registry, whatever the environment holds
        self.addCleanup(setattr, tempo_procs, "REGISTRY", reg)
        self.addCleanup(setattr, tempo_procs, "SESSIONS", tempo_procs.SESSIONS)
        tempo_procs.SESSIONS = self.tmp / "cache" / "sessions"
        tempo_dash.OWNED[0] = 0.0
        self.root = self.tmp / "root"
        self.root.mkdir()
        home = mock.patch.object(Path, "home", return_value=self.tmp / "home")  # no read of the real ~/.claude
        home.start()
        self.addCleanup(home.stop)
        tempo_dash.META.clear()
        tempo_dash.MODELS.clear()
        tempo_dash.SCANNED[0] = 0.0

    def serve(self, *roots):
        srv = tempo_dash.server(0, roots or [self.root])
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.port = srv.server_address[1]

    def get(self, path, method="GET", host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers={"Host": host} if host else {})
        r = c.getresponse()
        body = r.read().decode("utf-8")
        c.close()
        return r.status, body, r

    def tasks(self, query=""):
        status, body, _ = self.get("/api/tasks" + query)
        self.assertEqual(status, 200)
        return {t["task"]: t for t in json.loads(body)["tasks"]}


class StateEvents(Base):
    def test_state_commands_write_events(self):
        d, cache = self.tmp / "repo" / ".tempo" / "T-001", self.tmp / "cache"

        def state(*args, code=0):
            r = script("tempo_state.py", args[0], d, *args[1:], cache=cache)
            self.assertEqual(r.returncode, code, r.stderr)
            return r

        state("init", "--task", "T-001", "--flow", "FEATURE", "--title", "Title", "--base-branch", "main",
              "--base-commit", "abc", "--review-limit", "1")
        state("agent", "start", "a1", "--label", "builder-wo-01", "--output", ".tempo/T-001/report-01.md",
              "--prompt", ".tempo/T-001/prompts/builder-wo-01.md")
        state("agent", "start", "a2", "--label", "scout-CODE", "--output", ".tempo/T-001/explore/CODE.md")
        state("show")
        state("tracker")
        state("log", "TRIAGE", "report-01.md", "PASS")
        state("bump", "review")
        state("bump", "review", code=1)
        state("bump", "review", code=2)
        state("wait", "esc-1.md")
        self.assertIn("CLEARED: 1 agent(s)", state("set", "--status", "ABORTED").stdout)

        ev = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["ev"] for e in ev],
                         ["init", "agent", "agent", "log", "bump", "bump", "bump", "wait", "set"])
        for e in ev:
            self.assertEqual(list(e)[0], "at")
            self.assertRegex(e["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
            self.assertFalse({"dir", "cmd"} & set(e))
        self.assertEqual({k: v for k, v in ev[1].items() if k != "at"},
                         {"ev": "agent", "action": "start", "id": "a1", "label": "builder-wo-01",
                          "output": ".tempo/T-001/report-01.md", "prompt": ".tempo/T-001/prompts/builder-wo-01.md",
                          "state": "TRIAGE/RUNNING"})
        self.assertEqual(ev[0]["task"], "T-001")
        self.assertEqual({k: v for k, v in ev[3].items() if k != "at"},
                         {"ev": "log", "stage": "TRIAGE", "artifact": "report-01.md", "result": "PASS",
                          "closed": ["a1"], "state": "TRIAGE/RUNNING"})
        self.assertNotIn("closed", ev[4])
        self.assertEqual(ev[7]["state"], "TRIAGE/WAITING-ON-JORGE")
        self.assertEqual((ev[8]["closed"], ev[8]["state"]), (["a2"], "TRIAGE/ABORTED"))

        st = json.loads((d / "state.json").read_text())
        self.assertEqual((st["status"], st["agents"], st["counters"]["review"]), ("ABORTED", {}, 3))
        self.assertIn("# Task State: T-001", (d / "state.md").read_text())
        self.assertEqual([p.name for p in d.iterdir() if p.name.endswith(".tmp")], [])

    def test_the_other_commands_write_events_too(self):
        d, cache = self.tmp / "repo" / ".tempo" / "T-001", self.tmp / "cache"

        def state(*args):
            r = script("tempo_state.py", args[0], d, *args[1:], cache=cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

        state("init", "--task", "T-001", "--flow", "FEATURE", "--title", "T", "--base-branch", "main", "--base-commit", "abc")
        for aid, out in (("s1", "explore/A.md"), ("s2", "explore/B.md"), ("r1", "review/correctness-r1.md"),
                         ("r2", "review/security-r2.md"), ("b1", "report-01.md")):
            state("agent", "start", aid, "--label", "x-" + aid, "--output", out)
        inode = (d / "state.json").stat().st_ino
        state("agent", "done", "b1")
        self.assertNotEqual((d / "state.json").stat().st_ino, inode)  # replaced, never written in place
        state("log", "EXPLORE", "context.md", "PASS")
        state("log", "REVIEW", "findings-r1.md", "PASS")
        state("wo", "WO-01", "--status", "BUILDING")
        state("child", "api", "--folder", self.tmp / "child")
        state("decide", "SCOPE", "--question", "q", "--choice", "c", "--why", "w")
        state("wait", "esc-1.md")
        self.assertEqual(state("wait", "--clear"), f"STATE: {d}/state.md  STAGE: TRIAGE  STATUS: RUNNING\n")
        state("adopt")
        ev = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()][6:]
        for e in ev:
            e.pop("at")
            e["state"] = e["state"].split("/")[1]
        self.assertEqual(ev, [
            {"ev": "agent", "action": "done", "id": "b1", "state": "RUNNING"},
            {"ev": "log", "stage": "EXPLORE", "artifact": "context.md", "result": "PASS", "closed": ["s1", "s2"],
             "state": "RUNNING"},
            {"ev": "log", "stage": "REVIEW", "artifact": "findings-r1.md", "result": "PASS", "closed": ["r1"],
             "state": "RUNNING"},
            {"ev": "wo", "wo": "WO-01", "status": "BUILDING", "state": "RUNNING"},
            {"ev": "child", "repo": "api", "folder": str(self.tmp / "child"), "state": "RUNNING"},
            {"ev": "decide", "kind": "SCOPE", "question": "q", "choice": "c", "why": "w", "state": "RUNNING"},
            {"ev": "wait", "file": "esc-1.md", "state": "WAITING-ON-JORGE"},
            {"ev": "wait", "clear": True, "state": "RUNNING"}])

    def test_run_survives_a_missing_task_folder(self):
        gone = self.tmp / "repo" / ".tempo" / "T-404"
        r = script("tempo_run.py", "--task", gone, "--label", "unit", "--", "true", cache=self.tmp / "cache",
                   TMPDIR=str(self.tmp), TEMPO_LOCK_DIR=str(self.tmp / "locks"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(gone.exists())

    def test_run_writes_a_run_event(self):
        d = make_task(self.tmp / "repo" / ".tempo" / "T-002")
        r = script("tempo_run.py", "--task", d, "--label", "unit", "--", "true", cache=self.tmp / "cache",
                   TMPDIR=str(self.tmp), TEMPO_LOCK_DIR=str(self.tmp / "locks"))
        self.assertEqual(r.returncode, 0, r.stderr)
        e = json.loads((d / "events.jsonl").read_text())
        self.assertEqual((e["ev"], e["label"], e["heavy"], Path(e["dir"]).name), ("run", "unit", False, e["id"]))
        self.assertTrue(Path(e["dir"]).is_absolute() and e["id"].startswith("tempo-run-"))
        self.serve(self.tmp / "repo")
        self.assertEqual([(x["id"], x["state"], x["result"][:9]) for x in self.tasks()["T-002"]["runs"]],
                         [(e["id"], "done", "RUN: unit")])

    def test_event_never_raises(self):
        tempo_procs.event(self.tmp / "no-such-folder", ev="x")
        self.assertFalse((self.tmp / "no-such-folder").exists())
        tempo_procs.event(self.tmp, ev="x", bad=object())  # not JSON: dropped, no exception
        self.assertFalse((self.tmp / "events.jsonl").exists())


class Api(Base):
    def test_lists_tasks_of_a_root(self):
        make_task(self.root / ".tempo" / "T-001")
        child = make_task(self.tmp / "elsewhere" / "S-1", status="DONE")
        old = make_task(self.root / "repo" / ".tempo" / "T-002", status="DONE")
        parent = make_task(self.root / "repo" / ".tempo" / "T-003", children={"s1": {"folder": str(child)}})
        (self.root / "repo" / ".tempo" / "broken").mkdir()
        (self.root / "repo" / ".tempo" / "broken" / "state.json").write_text("{not json")
        for p in (old, child):
            os.utime(p / "state.json", (time.time() - 3 * 86400,) * 2)
        self.serve()

        status, body, r = self.get("/api/tasks")
        data = json.loads(body)
        self.assertEqual((status, r.getheader("Content-Type"), r.getheader("Cache-Control")),
                         (200, "application/json", "no-store"))
        self.assertEqual(set(data), {"now", "host", "tasks"})
        got = {t["task"]: t for t in data["tasks"]}
        self.assertEqual(set(got), {"T-001", "T-003", "S-1"})  # the old DONE task is out, the child is always in
        for t in got.values():
            self.assertEqual(set(t), KEYS)
        t = got["T-003"]
        self.assertEqual((t["dir"], t["checkout"], t["tag"], t["alive"]),
                         (str(parent), "repo", tempo_procs.tag(parent), None))
        self.assertEqual(t["state"], json.loads((parent / "state.json").read_text()))
        self.assertEqual(set(self.tasks("?hours=0")), {"T-001", "T-002", "T-003", "S-1"})

    def test_details_of_a_task(self):
        d = make_task(self.root / ".tempo" / "T-001", waiting="esc-1.md")
        gone = make_task(self.root / ".tempo" / "T-002")
        (gone / ".claim").write_text(json.dumps({"owner": 1}))  # claimed by a session that is not registered any more
        tempo_procs.SESSIONS.mkdir(parents=True)
        (tempo_procs.SESSIONS / f"{os.getpid()}.json").write_text(json.dumps([str(d)]))  # the session that resumed it
        claude = mock.patch.object(tempo_procs, "is_claude", lambda pid, table: pid == os.getpid())
        claude.start()
        self.addCleanup(claude.stop)
        (d / "esc-1.md").write_text("\n".join(f"line {n}" for n in range(40)))
        (d / "qa").mkdir()
        (d / "qa" / "progress.md").write_text("09:20 AC-1 PASS (1 of 2)\n09:21 AC-2 BLOCKED (1 of 2)\n\n")
        (d / "qa-r1.md").write_text("# QA Report\n\n## 5 Result\nFAIL\n")
        (d / "findings-r1.md").write_text("## 6 Result\n- PASS. PASS means no confirmed HIGH finding remains.\n")
        (d / "report-01.md").write_text("## 1 Summary\n- Result: BLOCKED\n- What changed\n")
        (d / "repro.md").write_text("## 2 Reproduction\n- Result: NOT REPRODUCED\n")
        (d / "task.md").write_text("# Task Card\n## 1 Request\n")
        (d / "worktrees" / "wo-01").mkdir(parents=True)
        (d / "worktrees" / "wo-01" / "README.md").write_text("x")
        (d / "a" / "b" / "c").mkdir(parents=True)
        (d / "a" / "b" / "ok.txt").write_text("x")
        (d / "a" / "b" / "c" / "deep.txt").write_text("x")
        (d / "shot.png").write_text("x")
        self.serve()
        self.assertIs(self.tasks()["T-002"]["alive"], False)
        t = self.tasks()["T-001"]
        self.assertIs(t["alive"], True)
        self.assertEqual(t["waiting_text"].splitlines()[-1], "line 29")
        self.assertEqual(t["qa_progress"], "09:21 AC-2 BLOCKED (1 of 2)")
        self.assertEqual(t["results"], {"qa-r1.md": "FAIL", "findings-r1.md": "PASS", "report-01.md": "BLOCKED",
                                        "repro.md": "NOT REPRODUCED"})
        self.assertEqual(t["files"], sorted(["a/b/ok.txt", "esc-1.md", "findings-r1.md", "qa-r1.md", "qa/progress.md",
                                             "report-01.md", "repro.md", "state.json", "task.md"]))

    def test_procs_never_carry_the_command(self):
        d = make_task(self.root / ".tempo" / "T-001")
        (d / "procs.json").write_text(json.dumps([
            {"label": "db", "pid": os.getpid(), "pgid": 1, "started_at": 5.0, "log": "/x/db.log", "cwd": "/x",
             "command": "psql postgres://app:hunter2@db/prod", "stop": "docker compose down --secret hunter2"},
            {"label": "old", "pid": 1, "started_at": 1.0, "stopped": 2.0, "command": "hunter2"}]))
        self.serve()
        status, body, _ = self.get("/api/tasks")
        self.assertNotIn("hunter2", body)
        t = json.loads(body)["tasks"][0]
        self.assertEqual(t["procs"], [
            {"label": "db", "pid": os.getpid(), "alive": True, "started": 5.0, "stopped": None, "log": "/x/db.log"},
            {"label": "old", "pid": 1, "alive": False, "started": 1.0, "stopped": 2.0, "log": None}])
        self.assertNotIn("procs.json", t["files"])

    def test_process_logs_are_never_served(self):
        d = make_task(self.root / ".tempo" / "T-001")
        (d / "procs.json").write_text('[{"command": "hunter2"}]')
        (d / "procs.log").write_text("RAN: db stop: docker compose down --secret hunter2\n")
        (d / "procs").mkdir()
        (d / "procs" / "db.log").write_text("--- start: psql postgres://app:hunter2@db/prod\n")
        (d / "alias.log").symlink_to(d / "procs.log")
        (d / "lnk").symlink_to(d / "procs")
        (d / "qa").mkdir()
        (d / "qa" / "procs.log").write_text("a QA note, not the teardown log\n")
        self.serve()
        t = self.tasks()["T-001"]
        self.assertEqual([f for f in t["files"] if "procs" in f.lower()], ["qa/procs.log"])
        # "proc\u017f.json": a case-insensitive volume folds the long s and opens procs.json
        for bad in ("procs.json", "procs.log", "procs/db.log", "PROCS/DB.LOG", "Procs.Log", "alias.log", "lnk/db.log",
                    "proc%C5%BF.json", "proc%C5%BF.log", "proc%C5%BF/db.log"):
            status, body, _ = self.get(f"/api/file?tag={t['tag']}&path={bad}")
            self.assertEqual(status, 404, bad)
            self.assertNotIn("hunter2", body)
        self.assertEqual(self.get(f"/api/file?tag={t['tag']}&path=qa/procs.log")[0], 200)

    def test_a_fifo_or_an_outside_symlink_never_stalls_or_leaks(self):
        d = make_task(self.root / ".tempo" / "T-001")
        os.mkfifo(d / "report.md")  # read_text on a FIFO blocks forever
        outside = self.tmp / "outside.md"
        outside.write_text("## 1 Result\nhunter2\n09:00 hunter2\n")
        (d / "qa").mkdir()
        (d / "qa" / "progress.md").symlink_to(outside)
        (d / "findings-r1.md").symlink_to(outside)
        make_task(self.root / ".tempo" / "T-002")
        os.mkfifo(self.root / ".tempo" / "T-002" / "events.jsonl")
        self.serve()
        status, body, _ = self.get("/api/tasks")
        self.assertNotIn("hunter2", body)
        got = {t["task"]: t for t in json.loads(body)["tasks"]}
        self.assertEqual(set(got), {"T-001", "T-002"})
        self.assertEqual((got["T-001"]["qa_progress"], got["T-001"]["results"]), (None, {}))

    def test_agents_without_and_with_events(self):
        d = make_task(self.root / ".tempo" / "T-001", agents={
            "old1": {"label": "scout-A", "output": "explore/A.md", "prompt": None, "started": "2026-11-11 10:00"}})
        meta = self.tmp / "home" / ".claude" / "projects" / "p" / "session" / "subagents"
        meta.mkdir(parents=True)
        (meta / "agent-n1.meta.json").write_text(json.dumps({"agentType": "tempo:builder", "model": "sonnet"}))
        (meta / "agent-n2.meta.json").write_text(json.dumps({"agentType": "tempo:reviewer"}))
        self.serve()
        self.assertEqual(self.tasks()["T-001"]["agents"], [
            {"id": "old1", "label": "scout-A", "output": "explore/A.md", "prompt": None,
             "started": "2026-11-11 10:00", "ended": None, "model": None}])

        at = "2026-11-11T10:0%d:00-03:00"
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
            {"at": at % 1, "ev": "agent", "action": "start", "id": "n1", "label": "builder", "output": "report-01.md"},
            {"at": at % 2, "ev": "agent", "action": "start", "id": "n2", "label": "rev", "output": "review/c-r1.md"},
            {"at": at % 3, "ev": "agent", "action": "start", "id": "n3", "label": "qa", "output": "qa-r1.md"},
            {"at": at % 4, "ev": "agent", "action": "done", "id": "n1", "state": "BUILD/RUNNING"},
            {"at": at % 5, "ev": "log", "stage": "REVIEW", "artifact": "findings-r1.md", "closed": ["n2"]},
        ]) + '{"at": "half a li')
        got = self.tasks()["T-001"]["agents"]
        self.assertEqual([(a["id"], a["ended"]) for a in got],
                         [("old1", None), ("n1", at % 4), ("n2", at % 5), ("n3", None)])
        self.assertEqual(got[1]["started"], at % 1)
        self.assertEqual([a["model"] for a in got], [None, "sonnet", None, None])

    def test_file_is_confined_to_the_task_folder(self):
        d = make_task(self.root / ".tempo" / "T-001")
        (d / "spec.md").write_text("# Spec ✓\n")
        (d / "qa").mkdir()
        (d / "qa" / "progress.md").write_text("ok\n")
        (d / "procs.json").write_text('[{"command": "hunter2"}]')
        (d / "secret.env").write_text("hunter2")
        outside = self.tmp / "outside.md"
        outside.write_text("hunter2")
        (d / "link.md").symlink_to(outside)
        (d / "ledger.md").symlink_to(d / "procs.json")
        (d / "big.log").write_bytes(b"a" * 100 + b"b" * 512 * 1024)
        self.serve()
        tag = self.tasks()["T-001"]["tag"]

        def file(path, tag=tag):
            return self.get(f"/api/file?tag={tag}&path={path}")

        status, body, r = file("spec.md")
        self.assertEqual((status, body, r.getheader("Content-Type")), (200, "# Spec ✓\n", "text/plain; charset=utf-8"))
        self.assertEqual(file("qa/progress.md")[:2], (200, "ok\n"))
        status, body, _ = file("big.log")
        self.assertEqual((status, len(body), body[0]), (200, 512 * 1024, "b"))
        for bad in ("../T-001/spec.md", "qa/../spec.md", "../../../outside.md", "%2e%2e/T-001/spec.md", str(d / "spec.md"),
                    str(outside), "link.md", "ledger.md", "procs.json", "PROCS.JSON", "secret.env", "qa", "",
                    "missing.md", "spec.md%00"):
            status, body, _ = file(bad)
            self.assertEqual(status, 404, bad)
            self.assertNotIn("hunter2", body)
        self.assertEqual(file("spec.md", tag="0" * 12)[0], 404)

    def test_refuses_foreign_hosts_and_other_methods(self):
        make_task(self.root / ".tempo" / "T-001")
        self.serve()
        for path in ("/", "/api/tasks", "/api/file?tag=x&path=y"):
            self.assertEqual(self.get(path, host="evil.example")[0], 403)
            self.assertEqual(self.get(path, host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.get("/api/tasks", host=f"localhost:{self.port}")[0], 200)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.get("/api/tasks", method=method)[0], 405)
        self.assertEqual(self.get("/nope")[0], 404)

    def test_missing_page_is_a_404(self):
        here = tempo_dash.HERE
        tempo_dash.HERE = self.tmp  # another agent writes dashboard.html: look where there is none
        self.addCleanup(setattr, tempo_dash, "HERE", here)
        self.serve()
        status, body, _ = self.get("/")
        self.assertEqual((status, body.count("\n")), (404, 1))
        (self.tmp / "dashboard.html").write_text("<!doctype html><title>x</title>")
        status, body, r = self.get("/")
        self.assertEqual((status, r.getheader("Content-Type")), (200, "text/html; charset=utf-8"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Page(unittest.TestCase):
    def test_markdown_never_nests_a_link_in_an_href(self):
        page = (SCRIPTS / "dashboard.html").read_text(encoding="utf-8")
        js = page[page.index("<script>") + 8:page.rindex("</script>")]
        cut = js.index("function md(")  # the renderer and its helpers are plain functions above the DOM code
        probe = js[:js.index("\n(function", cut)] if "\n(function" in js[cut:] else js
        hostile = ["http://a/[d](http://b/onmouseover=x//)", "http://a/`c`", "[x](javascript:alert(1))",
                   "<img src=x onerror=alert(1)>"]
        out = subprocess.run(["node", "-e", probe + ";\nconsole.log(JSON.stringify(" + json.dumps(hostile) + ".map(md)))"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[-600:])
        for html in json.loads(out.stdout):
            self.assertNotRegex(html, r'<a href="[^"]*<')
            self.assertNotRegex(html, r"<img|href=\"javascript:")


class StartStop(Base):
    def test_start_status_stop(self):
        cache = self.tmp / "cache"
        with socket.socket() as s:  # a free port; never the default one, which a real dashboard may hold
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        def dash(*args, **env):
            return script("tempo_dash.py", *args, cache=cache, **env)

        self.addCleanup(dash, "stop")
        self.assertEqual(dash("status").stdout, "DASH: not running\n")
        line = f"DASH: http://127.0.0.1:{port}/\n"
        r = dash("start", "--port", port, "--root", self.root, TEMPO_TAG="abcdefabcdef", TEMPO_SVC="x")
        self.assertEqual((r.returncode, r.stdout), (0, line), r.stderr)
        rec = json.loads((cache / "dash.json").read_text())
        self.assertEqual((rec["port"], rec["roots"]), (port, [str(self.root)]))
        proc = tempo_procs.snapshot()[rec["pid"]]
        self.assertIn("tempo_dash.py serve", proc["command"])
        self.assertEqual(tempo_procs.marks(proc), {"tag": None, "owner": 0, "svc": None, "run": None})  # no task's process
        self.assertEqual((dash("start", "--port", port).stdout, dash("status").stdout), (line, line))
        self.assertEqual(json.loads((cache / "dash.json").read_text())["pid"], rec["pid"])  # nothing new started
        self.assertEqual(dash("stop").stdout, "DASH: stopped\n")
        self.assertEqual(dash("status").stdout, "DASH: not running\n")
        for _ in range(50):
            if not tempo_procs.alive(rec["pid"]):
                break
            time.sleep(0.1)
        self.assertFalse(tempo_procs.alive(rec["pid"]))

    def test_start_refuses_a_taken_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            r = script("tempo_dash.py", "start", "--port", s.getsockname()[1], cache=self.tmp / "cache")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("taken by something else", r.stderr)
        self.assertFalse((self.tmp / "cache" / "dash.json").exists())


if __name__ == "__main__":
    unittest.main()
