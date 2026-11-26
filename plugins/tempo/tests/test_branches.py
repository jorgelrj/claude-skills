"""Tests for tempo_branches.py shipped (delete the task branch once its PR merged) against a stub gh.

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
GH = """#!/usr/bin/env python3
import os, sys, pathlib
p = pathlib.Path(os.environ["STUB"]) / "pr.json"
if sys.argv[1:3] == ["pr", "view"] and p.exists():
    sys.stdout.write(p.read_text()); sys.exit(0)
sys.stderr.write("no pull requests found\\n"); sys.exit(1)
"""


class Shipped(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "gh").write_text(GH)
        (self.tmp / "bin" / "gh").chmod(0o755)
        self.env = {**os.environ, "STUB": str(self.tmp), "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"}
        self.repo, origin = self.tmp / "repo", self.tmp / "origin.git"
        self.git(self.tmp, "init", "-q", "--bare", str(origin))
        self.git(self.tmp, "init", "-q", "-b", "main", str(self.repo))
        self.commit("base")
        self.git(self.repo, "remote", "add", "origin", str(origin))
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "switch", "-q", "-c", "feat/PD-1")
        self.head = self.commit("work")
        self.git(self.repo, "push", "-q", "-u", "origin", "feat/PD-1")
        self.git(self.repo, "switch", "-q", "main")
        # squash merge on the server, then the server deletes the branch
        self.git(self.repo, "push", "-q", "origin", "--delete", "feat/PD-1")
        self.git(self.repo, "fetch", "-q", "--prune", "origin")
        self.pr("MERGED")

    def git(self, cwd, *a):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, msg):
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", msg)
        return self.git(self.repo, "rev-parse", "HEAD")

    def pr(self, state, head=None):
        (self.tmp / "pr.json").write_text(json.dumps({"state": state, "headRefOid": head or self.head, "headRefName": "feat/PD-1"}))

    def run_shipped(self, *extra):
        r = subprocess.run([sys.executable, str(SCRIPTS / "tempo_branches.py"), "shipped", "--repo", str(self.repo),
                            "--branch", "feat/PD-1", "--pr", "7", *extra], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def exists(self):
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "-q", "refs/heads/feat/PD-1"],
                              capture_output=True).returncode == 0

    def test_squash_merged_remote_deleted_is_deleted(self):
        self.assertTrue(self.run_shipped("--dry-run").startswith("WOULD-DELETE feat/PD-1"))
        self.assertTrue(self.exists())
        self.assertTrue(self.run_shipped().startswith("DELETED feat/PD-1"))
        self.assertFalse(self.exists())

    def test_local_commit_after_pr_head_is_kept(self):
        self.git(self.repo, "switch", "-q", "feat/PD-1")
        self.commit("unpushed")
        self.git(self.repo, "switch", "-q", "main")
        self.assertIn("1 commits not in the PR", self.run_shipped())
        self.assertTrue(self.exists())

    def test_checked_out_in_a_worktree_is_kept(self):
        self.git(self.repo, "worktree", "add", "-q", str(self.tmp / "wt"), "feat/PD-1")
        self.assertIn("checked out in a worktree", self.run_shipped())
        self.assertTrue(self.exists())

    def test_open_or_closed_pr_is_kept(self):
        for state in ("OPEN", "CLOSED"):
            self.pr(state)
            self.assertIn("not merged", self.run_shipped())
        (self.tmp / "pr.json").unlink()
        self.assertIn("gh pr view failed", self.run_shipped())
        self.assertTrue(self.exists())

    def test_remote_copy_elsewhere_is_kept(self):
        self.git(self.repo, "update-ref", "refs/remotes/origin/feat/PD-1", "main")
        self.assertIn("remote copy", self.run_shipped())
        self.assertTrue(self.exists())


if __name__ == "__main__":
    unittest.main()
