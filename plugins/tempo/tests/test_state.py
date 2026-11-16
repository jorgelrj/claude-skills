"""Tests for tempo_state.py: the state lock, the QA counter, the SHIP entry, and a state.json from 0.21.0.

Run: python3 -m unittest discover -s <plugin>/tests -v
Everything happens in temp folders, with TEMPO_CACHE pointed at one.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tempo_os  # noqa: E402

# A state.json as 0.21.0 left it: a finished M feature on autopilot, with the shape of a real one
# (same keys, entries and counters); the title, links, paths and decision texts are stand-ins.
OLD_STATE = {
    "version": 1, "task": "NOV-592", "flow": "FEATURE", "lane": "M", "mode": "FULL", "title": "Show the previous record",
    "started": "2026-11-10 08:53", "stage_since": "2026-11-10 09:36", "base_branch": "develop",
    "base_commit": "90366811bb731e5657b2d2e07a2194b8b0c392eb", "task_branch": "feature/NOV-592", "parent": None,
    "pr": "https://example.test/pull/342", "stage": "DONE", "status": "DONE",
    "log": [["2026-11-10 08:53", "2026-11-10 08:54", "TRIAGE", "task.md", "PASS"],
            ["2026-11-10 08:54", "2026-11-10 08:57", "EXPLORE", "context.md", "PASS"],
            ["2026-11-10 08:57", "2026-11-10 09:00", "SPEC", "spec.md", "PASS"],
            ["2026-11-10 09:00", "2026-11-10 09:02", "HANDOFF", "wo-01.md", "PASS"],
            ["2026-11-10 09:02", "2026-11-10 09:10", "BUILD", "report-02.md", "PASS"],
            ["2026-11-10 09:11", "2026-11-10 09:13", "INTEGRATE", "integration.md", "PASS"],
            ["2026-11-10 09:17", "2026-11-10 09:18", "INTEGRATE", "integration.md", "PASS"],
            ["2026-11-10 09:18", "2026-11-10 09:19", "REVIEW", "findings-r2.md", "PASS"],
            ["2026-11-10 09:19", "2026-11-10 09:21", "QA", "qa-r1.md", "PASS"],
            ["2026-11-10 09:21", "2026-11-10 09:35", "SHIP", "integration.md", "PASS"]],
    "counters": {"review": 2, "review_limit": 3, "review_extensions": 1, "qa": 0, "qa_limit": 3, "reissue": 0},
    "work_orders": {
        "WO-01": {"worktree": "/repo/.tempo/worktrees/NOV-592-wo-01", "branch": "tempo/NOV-592-wo-01", "status": "DONE",
                  "started": "2026-11-10 09:02", "finished": "2026-11-10 09:08"},
        "WO-02": {"status": "DONE", "started": "2026-11-10 09:02", "worktree": "/repo/.tempo/worktrees/NOV-592-wo-02",
                  "branch": "tempo/NOV-592-wo-02", "finished": "2026-11-10 09:10"}},
    "waiting": None, "next": "Draft PR open; one criterion needs manual QA", "agents": {}, "children": {},
    "autopilot": True,
    "decisions": [{"at": "2026-11-10 09:00", "kind": "GATE-SPEC", "question": "D-1: which way?", "choice": "(a)",
                   "why": "the other one changes a second screen", "from": "spec.md §1"}],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-state-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {**os.environ, "TEMPO_CACHE": str(self.tmp / "cache"), "TEMPO_OWNER": "0", "TMPDIR": str(self.tmp),
                    "TEMPO_LOCK_DIR": str(self.tmp / "locks")}
        self.d = self.tmp / "repo" / ".tempo" / "T-001"

    def cmd(self, *args):
        return [sys.executable, str(SCRIPTS / "tempo_state.py"), args[0], str(self.d), *map(str, args[1:])]

    def state(self, *args, code=0):
        r = subprocess.run(self.cmd(*args), capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def init(self, *extra):
        self.state("init", "--task", "T-001", "--flow", "FEATURE", "--title", "Title", "--base-branch", "main",
                   "--base-commit", "abc", *extra)

    def json(self):
        return json.loads((self.d / "state.json").read_text())


class Lock(Base):
    def test_two_concurrent_wo_updates_both_persist(self):
        self.init()
        with open(self.d / ".state.lock", "w") as held:
            tempo_os.lock(held)
            procs = [subprocess.Popen(self.cmd("wo", wo, "--status", "BUILDING"), env=self.env, stdout=subprocess.DEVNULL)
                     for wo in ("WO-01", "WO-02")]
            self.addCleanup(lambda: [p.kill() for p in procs if p.poll() is None])
            time.sleep(1)
            self.assertEqual([p.poll() for p in procs], [None, None])  # both wait for the lock: no read yet
            self.assertEqual(self.json()["work_orders"], {})
        self.assertEqual([p.wait(20) for p in procs], [0, 0])
        self.assertEqual(sorted(self.json()["work_orders"]), ["WO-01", "WO-02"])

        names = [f"WO-{n:02d}" for n in range(3, 13)]
        procs = [subprocess.Popen(self.cmd("wo", wo, "--status", "BUILDING"), env=self.env, stdout=subprocess.DEVNULL)
                 for wo in names]
        self.assertEqual([p.wait(30) for p in procs], [0] * len(names))
        self.assertEqual(sorted(self.json()["work_orders"]), ["WO-01", "WO-02", *names])
        events = [json.loads(x) for x in (self.d / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(e["wo"] for e in events if e["ev"] == "wo"), ["WO-01", "WO-02", *names])

    def test_the_lock_is_free_during_the_teardown(self):
        self.init()
        (self.d / "procs.json").write_text(json.dumps([{"label": "slow", "stop": "sleep 3"}]))
        p = subprocess.Popen(self.cmd("set", "--status", "ABORTED"), env=self.env, stdout=subprocess.DEVNULL)
        self.addCleanup(p.wait)
        events = self.d / "events.jsonl"
        for _ in range(100):  # the event is the last thing written under the lock
            if '"ev": "set"' in events.read_text():
                break
            time.sleep(0.1)
        time.sleep(0.5)
        with open(self.d / ".state.lock", "w") as f:
            tempo_os.lock(f, block=False)  # raises when the command still holds it
        self.assertIsNone(p.poll())  # the stop command is still running
        self.assertEqual(p.wait(30), 0)

    def test_no_folder_and_the_dashboard_list(self):
        r = subprocess.run(self.cmd("show"), capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("state.json not found. Run `init`", r.stderr)
        self.assertFalse(self.d.exists())
        self.init()
        self.state("set", "--lane", "M")
        self.assertTrue((self.d / ".state.lock").exists())
        r = subprocess.run([sys.executable, "-c", "import sys, tempo_dash, pathlib; "
                            "print('\\n'.join(tempo_dash.files(pathlib.Path(sys.argv[1]))))", str(self.d)],
                           capture_output=True, text=True, env={**self.env, "PYTHONPATH": str(SCRIPTS)})
        self.assertEqual(r.stdout.split(), ["events.jsonl", "state.json", "state.md"], r.stderr)


class Counters(Base):
    def test_a_qa_report_raises_the_counter_and_prints_the_limit_line(self):
        self.init("--qa-limit", "2")
        self.state("set", "--stage", "QA")
        out = self.state("log", "QA", "qa-r1.md", "FAIL")
        self.assertEqual((self.json()["counters"]["qa"], out.count("\n")), (1, 1), out)
        out = self.state("log", "QA", "qa-r2.md", "FAIL")  # a FAIL at the limit: said, and still exit 0 (3.11)
        self.assertEqual(out.splitlines(), [f"STATE: {self.d}/state.md  STAGE: QA  STATUS: RUNNING",
                                            "LIMIT: qa rounds 2 of 2; raise LOOP-LIMIT"])
        out = self.state("log", "QA", ".tempo/T-001/qa-r3.md", "FAIL")
        self.assertEqual(out.splitlines()[1], "LIMIT: qa rounds 3 of 2; raise LOOP-LIMIT")
        self.assertEqual(self.json()["counters"]["qa"], 3)
        self.assertEqual(self.state("log", "QA", "qa-r3.md", "PASS").count("\n"), 1)  # a PASS never prints it
        self.state("log", "QA", "qa-joint-r9.md", "PASS")
        self.state("log", "REVIEW", "qa-r9.md", "PASS")
        self.assertEqual(self.json()["counters"]["qa"], 3)

        self.d = self.tmp / "repo" / ".tempo" / "T-002"  # `bump` keeps its own lines
        self.init("--qa-limit", "2")
        self.state("bump", "qa")
        self.state("bump", "qa")
        self.assertEqual(self.state("bump", "qa", code=2),
                         "HARD STOP: qa rounds 3 of 2 plus 0 extensions; ship open findings as known risks\n")
        self.state("bump", "review"), self.state("bump", "review"), self.state("bump", "review")
        self.assertEqual(self.state("bump", "review", code=1), "LIMIT: review rounds 4 of 3; raise LOOP-LIMIT\n")
        self.assertIn("HARD STOP: review rounds 5 of 3 plus 1 extensions", self.state("bump", "review", code=2))


class Ship(Base):
    def test_pr_logs_ship_once(self):
        self.init()
        self.state("log", "QA", "qa-r1.md", "PASS")
        self.state("set", "--stage", "SHIP")
        since = "2026-11-11 10:00"
        (self.d / "state.json").write_text(json.dumps({**self.json(), "stage_since": since}))
        self.state("set", "--pr", "https://example.test/pull/1", "--stage", "DONE", "--next", "Jorge merges")
        st = self.json()
        self.assertEqual([e[2:] for e in st["log"]], [["QA", "qa-r1.md", "PASS"], ["SHIP", "pr.md", "PASS"]])
        self.assertEqual(st["log"][-1][0], since)  # SHIP's own start, not the moment of DONE
        self.assertEqual((st["pr"], st["stage"], st["status"], st["next"]),
                         ("https://example.test/pull/1", "DONE", "DONE", "Jorge merges"))
        self.state("set", "--pr", "https://example.test/pull/2")
        self.assertEqual(len(self.json()["log"]), 2)
        self.assertIn("| SHIP | pr.md | PASS", (self.d / "state.md").read_text())

    def test_pr_on_an_empty_log_and_after_a_logged_ship(self):
        self.init()
        self.state("set", "--pr", "https://example.test/pull/1")
        self.assertEqual([e[2] for e in self.json()["log"]], ["SHIP"])
        self.d = self.tmp / "repo" / ".tempo" / "T-002"
        self.init()
        self.state("log", "SHIP", "integration.md", "PASS")  # what a FOLD logs
        self.state("set", "--pr", "https://example.test/pull/1")
        self.assertEqual([e[2:4] for e in self.json()["log"]], [["SHIP", "integration.md"]])

    def test_done_clears_next(self):
        self.init()
        self.state("set", "--next", "Open the PR")
        self.state("set", "--status", "FAILED")
        self.assertEqual(self.json()["next"], "Open the PR")  # only DONE clears it
        self.state("set", "--stage", "DONE")
        self.assertIsNone(self.json()["next"])
        self.assertIn("## 7 Next action\n- NIL", (self.d / "state.md").read_text())


class OldState(Base):
    def test_a_0_21_0_state_accepts_every_old_command(self):
        self.d.mkdir(parents=True)
        (self.d / "state.json").write_text(json.dumps(OLD_STATE, indent=2, ensure_ascii=False) + "\n")
        self.assertIn("# Task State: NOV-592", self.state("show"))
        self.assertEqual(json.loads(self.state("show", "--json")), OLD_STATE)
        self.state("set", "--status", "RUNNING", "--stage", "REVIEW", "--next", "Fix round", "--lane", "L",
                   "--title", "T", "--task-branch", "feature/NOV-592", "--base-commit", "abc", "--review-limit", "3",
                   "--review-extensions", "1", "--autopilot", "on", "--mode", "FULL")
        self.state("agent", "start", "a1", "--label", "builder-wo-01", "--output", "report-01.md")
        self.state("agent", "start", "a2", "--label", "verifier", "--output", "findings-r3.md")
        self.state("agent", "done", "a1")
        self.state("wo", "WO-01", "--status", "BUILDING")
        self.state("wo", "WO-01", "--status", "DONE")
        self.state("log", "BUILD", "report-01.md", "PASS")
        self.state("log", "REVIEW", "findings-r3.md", "PASS")
        self.state("bump", "reissue")
        self.state("bump", "qa")
        self.assertIn("LIMIT: review rounds 4 of 3", self.state("bump", "review", code=1))
        self.state("decide", "SCOPE", "--question", "q", "--choice", "c", "--why", "w", "--from", "spec.md")
        self.state("wait", "esc-1.md")
        self.state("wait", "--clear")
        self.state("child", "S-1", "--folder", self.tmp / "child")
        self.state("tracker")
        self.state("set", "--pr", "https://example.test/pull/343", "--stage", "DONE")
        st = self.json()
        self.assertEqual(set(st), set(OLD_STATE))  # the schema is the one 0.21.0 wrote
        self.assertEqual(set(st["counters"]), set(OLD_STATE["counters"]))
        self.assertEqual((st["status"], st["next"], st["agents"], st["counters"]["review"], st["counters"]["qa"]),
                         ("DONE", None, {}, 4, 1))
        self.assertEqual(st["log"][:10], OLD_STATE["log"])
        self.assertEqual([e[2:4] for e in st["log"][10:]],
                         [["BUILD", "report-01.md"], ["REVIEW", "findings-r3.md"], ["SHIP", "pr.md"]])
        self.assertEqual(len(st["work_orders"]["WO-01"]["runs"]), 1)
        self.assertEqual(len(st["decisions"]), 2)
        self.assertIn("| S-1 |", (self.d / "tracker.md").read_text())


if __name__ == "__main__":
    unittest.main()
