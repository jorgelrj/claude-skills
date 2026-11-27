"""Tests for tempo_distill.py: which sessions distill may clear, apply, the DUE suggestion and rules.md.

Run: python3 -m unittest discover -s <plugin>/tests -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "distill" / "scripts"))
import tempo_distill as td  # noqa: E402

GH = """#!/usr/bin/env python3
import json, os, sys, pathlib
prs = json.loads((pathlib.Path(os.environ["STUB"]) / "prs.json").read_text())
if sys.argv[1:3] == ["pr", "view"] and sys.argv[3] in prs:
    print(json.dumps({"state": prs[sys.argv[3]]})); sys.exit(0)
sys.stderr.write("no pull requests found\\n"); sys.exit(1)
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "gh").write_text(GH)
        (self.tmp / "bin" / "gh").chmod(0o755)
        self.prs = {}
        self.write_prs()
        env = {"STUB": str(self.tmp), "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        self.root = self.repo / ".tempo"
        self.root.mkdir()

    def write_prs(self):
        (self.tmp / "prs.json").write_text(json.dumps(self.prs))

    def task(self, tid, stage="DONE", status="DONE", pr=None, pr_state=None, mode="FULL", parent=None, files=(),
             children=None, root=None):
        d = (root or self.root) / tid
        d.mkdir(parents=True)
        s = {"task": tid, "stage": stage, "status": status, "mode": mode, "pr": pr,
             "children": {k: {"folder": str(v)} for k, v in (children or {}).items()}}
        if parent:
            s["parent"] = str(parent if isinstance(parent, Path) else self.root / parent)
        (d / "state.json").write_text(json.dumps(s))
        for f in files:
            (d / f).write_text("x\n")
        if pr and pr_state:
            self.prs[pr] = pr_state
            self.write_prs()
        return d

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = td.main([*args, "--repo", str(self.repo)])
        return code, out.getvalue()

    def verdicts(self):
        return {i: (ok, why) for i, _, ok, why in td.sessions(self.repo)}


class Eligibility(Base):
    def test_only_merged_or_delivered_plans_are_eligible(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        self.task("T-002", pr="https://x/pull/2", pr_state="OPEN")
        self.task("T-003", pr="https://x/pull/3", pr_state="CLOSED")
        self.task("T-004", stage="BUILD", status="RUNNING")
        self.task("T-005", stage="QA", status="ABORTED")
        self.task("T-006", stage="BUILD", status="FAILED")
        self.task("T-007")  # DONE, no PR, full mode: never shipped
        self.task("T-008", stage="PLANNED", status="DONE", mode="PLAN-ONLY")
        self.task("T-009", pr="https://x/pull/9")  # gh does not know it
        v = self.verdicts()
        self.assertEqual({i for i, (ok, _) in v.items() if ok}, {"T-001", "T-008"})
        self.assertIn("PR still OPEN", v["T-002"][1])
        self.assertIn("closed without merge", v["T-003"][1])
        self.assertIn("running", v["T-004"][1])
        self.assertIn("ABORTED", v["T-005"][1])
        self.assertIn("FAILED", v["T-006"][1])
        self.assertIn("no PR", v["T-007"][1])
        self.assertIn("PR state unknown", v["T-009"][1])

    def test_folders_without_state_are_not_sessions(self):
        (self.root / "worktrees").mkdir()
        (self.root / "baselines").mkdir()
        (self.root / "rules.md").write_text("# TEMPO rules\n")
        self.assertEqual(td.sessions(self.repo), [])

    def test_a_task_with_a_worktree_left_is_kept(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "--detach",
                        str(self.tmp / "wt" / "T-001-wo-01")], check=True)
        ok, why = self.verdicts()["T-001"]
        self.assertFalse(ok)
        self.assertIn("worktree", why)

    def test_a_split_task_goes_with_all_its_slices(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        self.task("T-001-s1", parent="T-001")
        self.task("T-001-s2", parent="T-001")
        v = self.verdicts()
        self.assertTrue(all(ok for ok, _ in v.values()), v)

    def test_one_running_slice_keeps_the_parent_and_every_slice(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        self.task("T-001-s1", parent="T-001")
        self.task("T-001-s2", stage="REVIEW", status="RUNNING", parent="T-001")
        v = self.verdicts()
        self.assertFalse(v["T-001"][0])
        self.assertIn("child T-001-s2", v["T-001"][1])
        self.assertFalse(v["T-001-s1"][0])

    def test_slices_of_an_open_pr_are_kept(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="OPEN")
        self.task("T-001-s1", parent="T-001")
        self.assertFalse(self.verdicts()["T-001-s1"][0])

    def test_a_workspace_task_waits_for_every_repo_pr(self):
        other = self.tmp / "api" / ".tempo"
        self.task("AV-1", pr="https://x/pull/7", pr_state="MERGED", root=other, parent=self.root / "W-1")
        self.task("AV-1", pr="https://x/pull/8", pr_state="OPEN", root=self.tmp / "web" / ".tempo",
                  parent=self.root / "W-1")
        self.task("W-1", children={"api": other / "AV-1", "web": self.tmp / "web" / ".tempo" / "AV-1"})
        ok, why = self.verdicts()["W-1"]
        self.assertFalse(ok)
        self.assertIn("child web is kept: PR still OPEN", why)
        self.prs["https://x/pull/8"] = "MERGED"
        self.write_prs()
        self.assertEqual(self.verdicts()["W-1"], (True, "done, every child shipped"))

    def test_list_prints_sources_for_eligible_sessions(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED", files=("decisions.md", "esc-1.md", "spec.md"))
        self.task("T-002", stage="BUILD", status="RUNNING")
        code, out = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("ELIGIBLE T-001 done, PR merged", out)
        self.assertIn("decisions.md", out)
        self.assertIn("esc-1.md", out)
        self.assertNotIn("spec.md", out)
        self.assertIn("KEPT T-002 running", out)
        self.assertIn("TOTAL: 1 eligible, 1 kept", out)


class Apply(Base):
    def test_refuses_a_kept_task_and_changes_nothing(self):
        a = self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        b = self.task("T-002", pr="https://x/pull/2", pr_state="OPEN")
        code, out = self.run_cli("apply", "--task", "T-001", "--task", "T-002", "--delete")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED T-002", out)
        self.assertTrue(a.exists() and b.exists())

    def test_delete(self):
        a = self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        code, out = self.run_cli("apply", "--task", "T-001", "--delete")
        self.assertEqual(code, 0)
        self.assertIn("DELETED T-001", out)
        self.assertFalse(a.exists())

    def test_archive_never_overwrites(self):
        (self.root / "archive" / "T-001").mkdir(parents=True)
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED", files=("decisions.md",))
        code, out = self.run_cli("apply", "--task", "T-001", "--archive")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "archive" / "T-001-2" / "decisions.md").exists())
        self.assertFalse((self.root / "T-001").exists())

    def test_unknown_task_is_refused(self):
        code, out = self.run_cli("apply", "--task", "T-404", "--delete")
        self.assertEqual(code, 1)
        self.assertIn("no such session", out)


class Due(Base):
    def test_threshold_mark_and_reset(self):
        self.task("T-001", pr="https://x/pull/1", pr_state="MERGED")
        self.task("T-002", pr="https://x/pull/2", pr_state="MERGED")
        self.assertIn("NOT-DUE", self.run_cli("due", "--threshold", "3")[1])
        self.assertIn("NOT-DUE", self.run_cli("due", "--threshold", "0")[1])
        self.assertIn("DISTILL: DUE 2 finished sessions", self.run_cli("due", "--threshold", "2")[1])
        self.run_cli("due", "--mark")
        self.assertIn("NOT-DUE", self.run_cli("due", "--threshold", "2")[1])  # suggested once per pile
        self.run_cli("apply", "--task", "T-001", "--delete")
        self.task("T-003", pr="https://x/pull/3", pr_state="MERGED")
        self.assertIn("DUE 2", self.run_cli("due", "--threshold", "2")[1])  # apply cleared the mark

    def test_running_tasks_do_not_count(self):
        self.task("T-001", stage="BUILD", status="RUNNING")
        self.task("T-002", pr="https://x/pull/2", pr_state="OPEN")
        self.assertIn("NOT-DUE", self.run_cli("due", "--threshold", "1")[1])


class Rules(Base):
    def test_add_show_dedup_drop(self):
        self.assertIn("RULES: NONE", self.run_cli("rules", "show")[1])
        code, out = self.run_cli("rules", "add", "--text", "Never mock the database in integration tests.",
                                 "--from", "AV-12")
        self.assertEqual(code, 0)
        code, out = self.run_cli("rules", "add", "--text", "  never MOCK the database in integration tests  ")
        self.assertEqual(code, 3)
        self.assertIn("DUPLICATE: rule 1", out)
        self.run_cli("rules", "add", "--text", "Use pnpm, not npm.")
        out = self.run_cli("rules", "show")[1]
        self.assertIn("1. Never mock the database in integration tests.  (from AV-12)", out)
        self.assertIn("2. Use pnpm, not npm.", out)
        self.assertEqual(self.run_cli("rules", "drop", "1")[0], 0)
        out = self.run_cli("rules", "show")[1]
        self.assertEqual(out.strip(), "1. Use pnpm, not npm.")
        text = (self.root / "rules.md").read_text()
        self.assertTrue(text.startswith("# TEMPO rules\n"))

    def test_rules_stay_short(self):
        code, out = self.run_cli("rules", "add", "--text", "x" * 201)
        self.assertEqual(code, 1)
        self.assertIn("TOO-LONG", out)
        for n in range(td.MAX_RULES):
            self.assertEqual(self.run_cli("rules", "add", "--text", f"rule number {n}")[0], 0)
        code, out = self.run_cli("rules", "add", "--text", "one more")
        self.assertEqual(code, 1)
        self.assertIn("FULL", out)

    def test_drop_rejects_bad_numbers(self):
        self.run_cli("rules", "add", "--text", "a rule")
        code, out = self.run_cli("rules", "drop", "2")
        self.assertEqual(code, 1)
        self.assertIn("NO-SUCH-RULE", out)
        self.assertIn("a rule", self.run_cli("rules", "show")[1])

    def test_lines_jorge_wrote_by_hand_are_ignored_not_lost_as_rules(self):
        (self.root / "rules.md").write_text("# TEMPO rules\nsome prose\n- kept rule\n")
        self.assertEqual(self.run_cli("rules", "show")[1].strip(), "1. kept rule")


class Cli(unittest.TestCase):
    def test_runs_as_a_script(self):
        script = Path(td.__file__)
        r = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Eligibility", r.stdout)


if __name__ == "__main__":
    unittest.main()
