"""Tests for tempo_ci.py (the CI-WAIT watcher and evidence collector) against a stub gh.

Run: python3 -m unittest discover -s <plugin>/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tempo_ci  # noqa: E402

# The stub answers from files in $STUB: pr.json, checks.json (+ checks.exit), log.txt, runs.json (runs on the head),
# runs-prt.json (pull_request_target runs), review.json (the artifact of run 42), job-<id>.json (a job's steps),
# joblog.txt (a whole job log, `job<TAB>UNKNOWN STEP<TAB><timestamp> line`).
GH = """#!/usr/bin/env python3
import os, sys, pathlib
d, a = pathlib.Path(os.environ["STUB"]), sys.argv[1:]
with open(d / "calls.txt", "a") as f:
    f.write(" ".join(a) + "\\n")
def out(name, code=0):
    p = d / name
    sys.stdout.write(p.read_text() if p.exists() else "")
    sys.exit(code)
if a[:2] == ["pr", "view"]: out("pr.json")
if a[:2] == ["pr", "checks"]: out("checks.json", int((d / "checks.exit").read_text()) if (d / "checks.exit").exists() else 0)
if a[:2] == ["run", "view"]: out("log.txt" if "--log-failed" in a else "joblog.txt")
if a[:1] == ["api"]: out("job-" + a[1].rsplit("/", 1)[-1] + ".json")
if a[:2] == ["run", "list"]: out("runs-prt.json" if "--event" in a else "runs.json")
if a[:2] == ["run", "download"]:
    if a[2] != "42" or not (d / "review.json").exists():
        sys.stderr.write("no artifact matches any of the names\\n"); sys.exit(1)
    dest = pathlib.Path(a[a.index("-D") + 1]); dest.mkdir(parents=True, exist_ok=True)
    (dest / "review.json").write_text((d / "review.json").read_text()); sys.exit(0)
sys.exit(2)
"""

PR = {"state": "OPEN", "isDraft": False, "mergeStateStatus": "CLEAN", "headRefOid": "abc123", "url": "https://x/pull/7",
      "title": "feat(PD-1): a change"}


class Verdict(unittest.TestCase):
    def test_each_state_has_its_line(self):
        green = [{"name": "ci-gate", "bucket": "pass"}]
        self.assertIsNone(tempo_ci.verdict(PR, green))  # green but not merged: keep waiting
        self.assertIsNone(tempo_ci.verdict(PR, [{"name": "ci-gate", "bucket": "pending"}]))
        early = [{"name": "flutter", "bucket": "fail"}, {"name": "ai-review", "bucket": "pending"}]
        self.assertIsNone(tempo_ci.verdict(PR, early))  # the review still runs: wait, so one round sees both
        self.assertEqual(tempo_ci.waiting(early), "pending ai-review; red so far: flutter")
        self.assertEqual(tempo_ci.verdict({**PR, "state": "MERGED"}, []), ("MERGED", PR["url"]))
        self.assertEqual(tempo_ci.verdict({**PR, "state": "CLOSED"}, green), ("CLOSED", PR["url"]))
        self.assertEqual(tempo_ci.verdict({**PR, "mergeStateStatus": "DIRTY"}, green), ("CONFLICT", PR["url"]))
        self.assertEqual(tempo_ci.verdict({**PR, "isDraft": True}, green), ("DRAFT", PR["url"]))
        self.assertEqual(tempo_ci.verdict(PR, green + [{"name": "ai-review", "bucket": "fail"}, {"name": "web", "bucket": "cancel"}]),
                         ("RED", "ai-review, web"))
        self.assertEqual(tempo_ci.waiting([]), "pending (no checks reported yet)")
        self.assertTrue(tempo_ci.waiting(green).startswith("green"))
        # a required check that has not reported yet (a commit status posts when its run ends) counts as pending
        fast_fail = tempo_ci.with_required([{"name": "ci-gate", "bucket": "fail"}], ["ci-gate", "ai-review"])
        self.assertIsNone(tempo_ci.verdict(PR, fast_fail))
        self.assertEqual(tempo_ci.waiting(tempo_ci.with_required(green, ["ai-review"])), "pending ai-review")

    def test_review_findings_keeps_critical_and_high(self):
        items = [{"severity": "HIGH", "file": "a"}, {"severity": "medium"}, {"severity": "critical"}, "junk"]
        self.assertEqual(len(tempo_ci.review_findings({"findings": items})), 2)
        self.assertEqual(len(tempo_ci.review_findings(items)), 2)
        self.assertEqual(tempo_ci.review_findings({}), [])


@unittest.skipIf(os.name == "nt", "the gh stub is a script with a shebang")
class Stub(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-ci-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "gh").write_text(GH)
        (self.tmp / "bin" / "gh").chmod(0o755)
        self.env = {**os.environ, "STUB": str(self.tmp), "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"}
        self.put("pr.json", PR)

    def put(self, name, data):
        (self.tmp / name).write_text(data if isinstance(data, str) else json.dumps(data))

    def ci(self, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / "tempo_ci.py"), *map(str, args), "--pr", "7", "--repo", str(self.tmp)],
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_watch_waits_on_green_and_stops_on_merge_or_red(self):
        self.put("checks.json", [{"name": "ci-gate", "bucket": "pass", "state": "SUCCESS"}])
        self.assertEqual(self.ci("watch", "--poll", "0.1", "--max", "0.3"),
                         "TIMEOUT: green (every check passed; the PR is not merged yet)\n")
        self.put("checks.json", [{"name": "ci-gate", "bucket": "pending"}]); self.put("checks.exit", "8")
        self.assertEqual(self.ci("watch", "--poll", "0.1", "--max", "0.1"), "TIMEOUT: pending ci-gate\n")
        self.put("checks.json", [{"name": "ci-gate", "bucket": "fail"}]); self.put("checks.exit", "1")
        self.assertEqual(self.ci("watch", "--poll", "5", "--max", "60"), "RED: ci-gate\n")
        self.put("pr.json", {**PR, "state": "MERGED"})
        self.assertEqual(self.ci("watch", "--poll", "5", "--max", "60"), f"MERGED: {PR['url']}\n")

    def test_watch_survives_gh_that_does_not_answer(self):
        (self.tmp / "bin" / "gh").write_text("#!/bin/sh\necho 'connection refused' >&2\nexit 1\n")
        self.assertIn("TIMEOUT: pending (gh did not answer", self.ci("watch", "--poll", "0.1", "--max", "0.1"))  # one blip
        self.assertIn("ERROR: gh did not answer in the window: gh pr view: connection refused",
                      self.ci("watch", "--poll", "0.05", "--max", "0.3"))

    def test_watch_waits_for_a_required_check_that_has_not_reported(self):
        self.put("checks.json", [{"name": "ci-gate", "bucket": "fail"}]); self.put("checks.exit", "1")
        self.assertEqual(self.ci("watch", "--poll", "0.1", "--max", "0.1", "--require", "ai-review"),
                         "TIMEOUT: pending ai-review; red so far: ci-gate\n")

    def test_collect_writes_log_tails_and_blocking_findings(self):
        self.put("checks.json", [
            {"name": "flutter (core)", "bucket": "fail", "state": "FAILURE", "link": "https://g/o/r/actions/runs/9/job/11"},
            {"name": "ai-review", "bucket": "fail", "state": "FAILURE", "link": "https://g/o/r/pull/7"},
            {"name": "server", "bucket": "pass", "state": "SUCCESS", "link": "https://g/o/r/actions/runs/9/job/12"}])
        self.put("checks.exit", "1")
        self.put("log.txt", "\n".join(f"line {i}" for i in range(200)) + "\nExpected: 2 Actual: 3\n")
        self.put("runs.json", [{"databaseId": 41, "workflowName": "pr-tests"}, {"databaseId": 42, "workflowName": "pr-review"}])
        self.put("review.json", {"findings": [
            {"severity": "HIGH", "file": "lib/a.dart", "line": 4, "title": "Null crash", "detail": "x is null on logout"},
            {"severity": "MEDIUM", "file": "lib/b.dart", "line": 1, "title": "Naming"}]})
        out = self.tmp / "ci" / "round-1.md"
        self.assertEqual(self.ci("collect", "--out", out, "--lines", "5"),
                         f"CI: {out}  FAILED: 2  BLOCKING: 1  NO-EVIDENCE: NIL  CANCELLED: 0\n")
        text = out.read_text()
        self.assertIn("Expected: 2 Actual: 3", text)
        self.assertNotIn("line 150", text)  # only the tail
        self.assertIn("HIGH lib/a.dart:4 Null crash: x is null on logout", text)
        self.assertNotIn("Naming", text)
        self.assertIn("run view --job 11 --log-failed", (self.tmp / "calls.txt").read_text())
        (self.tmp / "review.json").unlink()  # an indeterminate review: red, and nothing to fix
        self.assertIn("NO-EVIDENCE: ai-review", self.ci("collect", "--out", out))
        self.assertIn("no run of this PR has an artifact named ai-review", out.read_text())

    def test_collect_reads_a_self_cancelled_job_and_skips_its_cancelled_siblings(self):
        # pr-tests cancels its own run on a failure: the failing job ends cancelled and --log-failed prints nothing
        self.put("checks.json", [
            {"name": "server-int", "bucket": "cancel", "state": "CANCELLED", "link": "https://g/o/r/actions/runs/9/job/11"},
            {"name": "client (apps/coach 0/6)", "bucket": "cancel", "state": "CANCELLED", "link": "https://g/o/r/actions/runs/9/job/12"}])
        self.put("checks.exit", "1")
        self.put("job-11.json", {"steps": [
            {"name": "Run pnpm build", "conclusion": "success", "started_at": "2026-11-25T10:00:00Z", "completed_at": "2026-11-25T10:00:20Z"},
            {"name": "Run pnpm test:int", "conclusion": "failure", "started_at": "2026-11-25T10:00:21Z", "completed_at": "2026-11-25T10:03:00Z"},
            {"name": "Run gh run cancel", "conclusion": "cancelled", "started_at": "2026-11-25T10:03:00Z", "completed_at": "2026-11-25T10:03:01Z"}]})
        self.put("job-12.json", {"steps": [{"name": "Test the shard", "conclusion": "cancelled"}]})
        # gh run view --log names every step UNKNOWN STEP: the failed step's lines are found by its time window
        self.put("joblog.txt", "server-int\tUNKNOWN STEP\t﻿2026-11-25T10:00:10.1Z built ok\n"
                 "server-int\tUNKNOWN STEP\t2026-11-25T10:01:00.1Z FAIL src/a.int-spec.ts > lists rows\n"
                 "server-int\tUNKNOWN STEP\t2026-11-25T10:02:59.9Z expected 2 to be 3\n"
                 "server-int\tUNKNOWN STEP\t2026-11-25T10:03:01.5Z ##[error]The operation was canceled.\n")
        out = self.tmp / "r.md"
        self.assertEqual(self.ci("collect", "--out", out), f"CI: {out}  FAILED: 2  BLOCKING: 0  NO-EVIDENCE: NIL  CANCELLED: 1\n")
        text = out.read_text()
        self.assertIn("failed step: Run pnpm test:int", text)
        self.assertIn("FAIL src/a.int-spec.ts > lists rows", text)
        self.assertIn("expected 2 to be 3", text)
        self.assertNotIn("built ok", text)  # only the failed step's lines
        self.assertNotIn("operation was canceled", text)
        self.assertNotIn("2026-11-25T10:01:00", text)  # timestamps dropped
        self.assertIn("cancelled with no failed step of its own", text)
        # a failed step with no lines in its window is no evidence; with nothing else in the round, nothing is
        self.put("joblog.txt", "")
        self.assertEqual(self.ci("collect", "--out", out),
                         f"CI: {out}  FAILED: 2  BLOCKING: 0  NO-EVIDENCE: server-int, client (apps/coach 0/6)  CANCELLED: 0\n")
        self.assertNotIn("Run pnpm test:int (the job then cancelled its own run, so it shows as cancelled)\n- cancelled", out.read_text())
        # no job failed on its own (a runner died, or every job was stopped): that is NO-EVIDENCE again
        self.put("job-11.json", {"steps": [{"name": "Run pnpm test:int", "conclusion": "cancelled"}]})
        self.assertEqual(self.ci("collect", "--out", out),
                         f"CI: {out}  FAILED: 2  BLOCKING: 0  NO-EVIDENCE: server-int, client (apps/coach 0/6)  CANCELLED: 0\n")

    def test_collect_finds_the_review_run_off_the_head(self):
        # pull_request_target runs on the base's head commit, so no run on the PR head holds the review
        self.put("checks.json", [{"name": "ai-review", "bucket": "fail", "state": "FAILURE",
                                  "link": "https://g/o/r/actions/runs/42"}])
        self.put("runs.json", [{"databaseId": 41, "displayTitle": PR["title"]}])
        self.put("review.json", {"findings": [{"severity": "CRITICAL", "file": "a.ts", "line": 2, "title": "Leak"}]})
        out = self.tmp / "r.md"
        self.assertEqual(self.ci("collect", "--out", out), f"CI: {out}  FAILED: 1  BLOCKING: 1  NO-EVIDENCE: NIL  CANCELLED: 0\n")
        downloads = [c for c in (self.tmp / "calls.txt").read_text().splitlines() if c.startswith("run download")]
        self.assertTrue(downloads[0].startswith("run download 42 "), downloads)  # the link's run, tried first
        # no link: the pull_request_target run with the PR's title
        self.put("checks.json", [{"name": "ai-review", "bucket": "fail", "state": "FAILURE", "link": ""}])
        self.put("runs-prt.json", [{"databaseId": 40, "displayTitle": "another PR"}, {"databaseId": 42, "displayTitle": PR["title"]}])
        self.assertEqual(self.ci("collect", "--out", out), f"CI: {out}  FAILED: 1  BLOCKING: 1  NO-EVIDENCE: NIL  CANCELLED: 0\n")
        self.assertNotIn("run download 40 ", (self.tmp / "calls.txt").read_text())
        # the review's own run has no artifact (an indeterminate review): an older run's findings do not count
        self.put("checks.json", [{"name": "ai-review", "bucket": "fail", "state": "FAILURE",
                                  "link": "https://g/o/r/actions/runs/43"}])
        self.assertIn("NO-EVIDENCE: ai-review", self.ci("collect", "--out", out))


if __name__ == "__main__":
    unittest.main()
