"""Tests for tempo_config.py: a config written for 0.21.0 still passes, gates.full_bars: verify, task.trackers,
run: final targets, tests.always and tests.slow, dupes and the space WARN, the ci tier, run: ci targets, the
machine override file and sync merged.

Run: python3 -m unittest discover -s <plugin>/tests -v
The script needs PyYAML and jsonschema, so it runs the way the plugin runs it, with `uv run`.
Each test makes its own git repo in a temp folder.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "skills" / "config"
UV = shutil.which("uv")

# A repo config as 0.21.0 accepted it: no gates block, one scoped advisory target and one with a whole command only.
OLD = """\
version: 1
commands:
  test: cd app && melos run test
  test_one: cd {package} && flutter test {tests}
  build: cd app && melos run analyze
  lint: cd app && dart format --output=none --set-exit-if-changed .
targets:
  - name: web
    command: cd app && melos run test:web:full
    scoped_command: cd {package} && flutter test --platform chrome {tests}
    advisory: true
    paths: [app/**]
  - name: e2e
    command: cd app && melos run e2e
    run: critical
    paths: [app/**]
git:
  base_branch: develop
  commit:
    message: "{type}({scope}): {summary} (#{ticket})"
pr:
  base: develop
  draft: false
worktree:
  link: [app/.fvm]
task:
  tracker: github
  ticket_pattern: "(?:#|/issues/)(\\\\d+)"
  standing_decisions:
    - "The full Chrome suite runs for a critical change only."
"""
WEB = "web\tcd app && flutter test --platform chrome test/foo_test.dart\tadvisory\n"


@unittest.skipUnless(UV, "uv is not installed: tempo_config.py needs PyYAML and jsonschema, which `uv run` provides")
class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-config-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.env = {**os.environ, "TEMPO_CACHE": str(self.tmp / "cache"), "TMPDIR": str(self.tmp),
                    "TEMPO_LOCK_DIR": str(self.tmp / "locks"), "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}  # HOME stays: uv keeps its packages there
        for f in ("app/pubspec.yaml", "app/lib/foo.dart", "app/test/foo_test.dart", ".tempo/config.yaml"):
            (self.repo / f).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / f).write_text("")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "app"], check=True)  # targets reads the tracked files
        self.write(OLD)

    def write(self, text):
        (self.repo / ".tempo" / "config.yaml").write_text(text)

    def cfg(self, *args, code=0):
        r = subprocess.run([UV, "run", "--quiet", str(CONFIG / "scripts" / "tempo_config.py"), "--repo", str(self.repo),
                            *map(str, args)], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_a_0_21_0_config_passes_check(self):
        self.assertEqual(self.cfg("check"),
                         f"PASS: {CONFIG / 'defaults.yaml'}, {self.repo / '.tempo' / 'config.yaml'}\n")
        self.assertEqual(self.cfg("check", *sorted((CONFIG / "templates").glob("*.yaml"))), "PASS: 2 file(s)\n")
        for value in ("on_demand", "integrate", "verify"):
            self.write(OLD + f"gates:\n  full_bars: {value}\n")
            self.assertIn("PASS: ", self.cfg("check"))
        self.write(OLD + "gates:\n  full_bars: never\n")
        self.assertIn("gates.full_bars: 'never' is not one of", self.cfg("check", code=1))

    def test_bars_are_full_under_on_demand_and_deferred_under_verify(self):
        lock = "app/pubspec.lock"
        for text in (OLD, OLD + "gates:\n  full_bars: on_demand\n"):  # the default did not change
            self.write(text)
            self.assertEqual(self.cfg("bars", "--critical"), "BARS: FULL  WHY: critical change\n")
            self.assertEqual(self.cfg("bars", "--paths", lock), f"BARS: FULL  WHY: gates.full_paths matches {lock}\n")
            self.assertEqual(self.cfg("bars", "--paths", "app/lib/foo.dart"), "BARS: NARROW  WHY: routine change\n")
        self.write(OLD + "gates:\n  full_bars: integrate\n")
        self.assertEqual(self.cfg("bars"), "BARS: FULL  WHY: gates.full_bars is integrate\n")
        self.write(OLD + "gates:\n  full_bars: verify\n")
        narrow = "BARS: NARROW  WHY: gates.full_bars is verify\n"
        self.assertEqual(self.cfg("bars", "--critical", "--paths", lock), narrow + "DEFERRED: critical change\n")
        self.assertEqual(self.cfg("bars", "--paths", lock), narrow + f"DEFERRED: gates.full_paths matches {lock}\n")
        self.assertEqual(self.cfg("bars", "--paths", "app/lib/foo.dart"), narrow)  # no whole suite was owed

    def test_targets_scoped_only_never_prints_a_whole_command(self):
        paths = ("--critical", "--paths", "app/lib/foo.dart")
        self.assertEqual(self.cfg("targets", *paths), WEB + "e2e\tcd app && melos run e2e\n")
        self.assertEqual(self.cfg("targets", *paths, "--scoped-only"), WEB + "e2e\t# DEFERRED whole suite\n")
        self.assertEqual(self.cfg("targets", "--critical", "--scoped-only"),
                         "web\t# DEFERRED whole suite\tadvisory\ne2e\t# DEFERRED whole suite\n")
        self.assertEqual(self.cfg("targets", "--paths", "app/lib/foo.dart", "--scoped-only"), "")  # both run: critical

    def test_verify_gate_defers_whole_suites_unless_verify_asks(self):
        self.write(OLD + "gates:\n  full_bars: verify\n")
        out = self.cfg("targets", "--critical", "--full", "--paths", "app/lib/foo.dart")
        self.assertNotIn("melos run", out)
        self.assertIn("# DEFERRED whole suite", out)
        self.assertIn("melos run", self.cfg("targets", "--critical", "--full", "--verify", "--paths", "app/lib/foo.dart"))

    def test_trackers_pick_the_ticket_named_first_and_sync_is_opt_in(self):
        self.assertEqual(self.cfg("ticket", "--text", "Fix #215 for POD-3"), "TICKET: 215\nTRACKER: github\n")  # 0.21.0 form
        self.assertEqual(self.cfg("ticket", "--text", "T-004 again"), "TICKET: NONE\n")
        self.write(OLD.split("task:")[0] + TRACKERS)
        self.assertEqual(self.cfg("check"), f"PASS: {CONFIG / 'defaults.yaml'}, {self.repo / '.tempo' / 'config.yaml'}\n")
        self.assertEqual(self.cfg("ticket", "--text", "POD-3: see #215"), "TICKET: POD-3\nTRACKER: jira\n")
        self.assertEqual(self.cfg("ticket", "--text", "#215, from POD-3"), "TICKET: 215\nTRACKER: github\n")
        self.assertEqual(self.cfg("sync", "pr", "--text", "POD-3"), "SYNC: OFF (jira POD-3: nothing set for pr)\n")
        self.assertEqual(self.cfg("sync", "start", "--text", "nothing here"), "SYNC: OFF (no ticket in the request)\n")
        self.assertIn("atlassian-multi is not installed", self.cfg("sync", "start", "--text", "POD-3"))  # CLAUDE_CONFIG_DIR is empty
        self.assertEqual(self.cfg("sync", "pr", "--text", "#215"),
                         "WARN: 215 not moved: sync.project names no GitHub Projects board\n")
        self.write(OLD + TRACKERS.replace("task:\n", ""))
        self.assertIn("trackers replaces tracker and ticket_pattern", self.cfg("check", code=1))


    def test_final_targets_print_with_final_critical_or_full_only(self):
        self.write(OLD.replace("    run: critical\n", "    run: final\n"))  # e2e becomes final; web keeps the advisory default
        e2e = "e2e\tcd app && melos run e2e\n"
        self.assertEqual(self.cfg("targets", "--paths", "app/lib/foo.dart"), "")
        self.assertEqual(self.cfg("targets", "--paths", "app/lib/foo.dart", "--final"), e2e)  # advisory stays critical-only
        self.assertEqual(self.cfg("targets", "--paths", "app/lib/foo.dart", "--critical"), WEB + e2e)
        self.assertEqual(self.cfg("targets", "--paths", "app/lib/foo.dart", "--full"),
                         "web\tcd app && melos run test:web:full\tadvisory\n" + e2e)

    def test_bars_print_always_and_the_slow_files_a_change_touches_or_mirrors(self):
        for f in ("app/lib/bar.dart", "app/test/bar_test.dart"):
            (self.repo / f).write_text("")
        subprocess.run(["git", "-C", str(self.repo), "add", "app"], check=True)
        self.write(OLD + "tests:\n  always: [app/test/guard_test.dart]\n  slow: [app/test/foo_test.dart]\n")
        narrow = "BARS: NARROW  WHY: routine change\nALWAYS: app/test/guard_test.dart\n"
        self.assertEqual(self.cfg("bars", "--paths", "app/test/foo_test.dart"), narrow + "SLOW: app/test/foo_test.dart\n")
        self.assertEqual(self.cfg("bars", "--paths", "app/lib/foo.dart"), narrow + "SLOW: app/test/foo_test.dart\n")
        self.assertEqual(self.cfg("bars", "--paths", "app/lib/bar.dart", "app/test/bar_test.dart"), narrow)
        self.assertEqual(self.cfg("bars"), narrow)

    def test_check_warns_when_the_repo_path_has_a_space(self):
        self.assertNotIn("WARN", self.cfg("check"))
        self.repo = self.repo.rename(self.tmp / "my repo")
        self.assertIn("contains a space: melos splits it on Windows", self.cfg("check"))

    @unittest.skipIf(os.name == "nt", "the gh stub is a shell script")
    def test_dupes_lists_other_open_prs_and_remote_branches_for_the_ticket(self):
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(git + ["commit", "-qm", "x"], check=True)
        self.assertIn("WARN: remote branches not checked", self.cfg("dupes", "--ticket", "PD-12", "--branch", "feat/PD-12"))
        bare = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(bare)], check=True)
        for b in ("feat/PD-12", "feat/PD-12-s2", "fix/pd-12-retry", "feat/PD-123", "chore/PD-12-x", "fix/PD-12-old"):
            subprocess.run(git + ["push", "-q", "origin", f"HEAD:refs/heads/{b}"], check=True)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        prs = ('[{"number":7,"headRefName":"chore/PD-12-x","url":"u7","title":"x"},'
               '{"number":8,"headRefName":"feat/PD-12","url":"u8","title":"PD-12"},'
               '{"number":9,"headRefName":"feat/PD-123","url":"u9","title":"PD-123"},'
               '{"number":10,"headRefName":"docs/y","url":"u10","title":"Follow PD-12 up"},'
               '{"number":5,"headRefName":"fix/PD-12-old","url":"u5","title":"PD-12","state":"MERGED"},'
               '{"number":4,"headRefName":"feat/PD-12-v0","url":"u4","title":"PD-12","state":"CLOSED"}]')
        (bin_ / "gh").write_text(f"#!/bin/sh\necho '{prs}'\n")
        (bin_ / "gh").chmod(0o755)
        self.env["PATH"] = f"{bin_}{os.pathsep}{self.env['PATH']}"
        self.assertEqual(self.cfg("dupes", "--ticket", "PD-12", "--branch", "feat/PD-12", "--branch", "feat/PD-12-s2", code=3),
                         "DUPE: pr chore/PD-12-x u7\nDUPE: pr docs/y u10\nDUPE: branch fix/pd-12-retry\n")
        (bin_ / "gh").write_text("#!/bin/sh\nexit 1\n")
        out = self.cfg("dupes", "--ticket", "PD-99", "--branch", "feat/PD-99")
        self.assertEqual(out.splitlines()[0][:40], "WARN: open PRs not checked: gh did not a")
        self.assertNotIn("DUPE", out)

    def test_ci_tier_runs_light_and_defers_targets_to_ci(self):
        self.write(OLD + "gates:\n  full_bars: ci\nlimits:\n  ci_rounds: 3\n")
        self.assertNotIn("WARN", self.cfg("check"))
        self.assertEqual(self.cfg("bars", "--paths", "app/pubspec.lock"), "BARS: LOCAL  WHY: gates.full_bars is ci\nDEFERRED: ci\n")
        self.assertEqual(self.cfg("bars", "--critical"), "BARS: LOCAL  WHY: gates.full_bars is ci\nDEFERRED: ci (critical change)\n")
        paths = ("--critical", "--final", "--paths", "app/lib/foo.dart")
        self.assertEqual(self.cfg("targets", *paths), "web\t# DEFERRED to CI\tadvisory\ne2e\t# DEFERRED to CI\n")
        self.assertIn("flutter test --platform chrome", self.cfg("targets", *paths, "--verify"))
        self.assertEqual(self.cfg("cmd", "test_one"), "cd {package} && flutter test {tests}\n")  # no test_local: test_one
        self.write(OLD.replace("  build:", "  test_local: cd {package} && flutter test -x widget {tests}\n  build:")
                   + "gates:\n  full_bars: ci\nlimits:\n  ci_rounds: 3\n")
        self.assertEqual(self.cfg("cmd", "test_one"), "cd {package} && flutter test -x widget {tests}\n")
        (self.repo / ".tempo" / "config.local.yaml").write_text(  # a slow laptop caps the command its tier runs
            "commands:\n  test_local: cd {package} && flutter test -j 2 -x widget {tests}\n  test_one: cd {package} && flutter test -j 2 {tests}\n")
        self.assertEqual(self.cfg("cmd", "test_one"), "cd {package} && flutter test -j 2 -x widget {tests}\n")
        (self.repo / ".tempo" / "config.local.yaml").unlink()
        self.write(OLD.replace("  build:", "  test_local: cd {package} && flutter test -x widget {tests}\n  build:"))
        self.assertEqual(self.cfg("cmd", "test_one"), "cd {package} && flutter test {tests}\n")  # other tiers ignore it
        self.write(OLD + "gates:\n  full_bars: ci\n")
        self.assertIn("limits.ci_rounds is 0", self.cfg("check"))
        self.write(OLD.replace("draft: false", "draft: true") + "limits:\n  ci_rounds: 2\n")
        self.assertIn("a draft PR never merges", self.cfg("check"))
        self.write(OLD.replace("  draft: false", "  draft: false\n  required_checks: [ci-gate, ai-review]") + "limits:\n  ci_rounds: 2\n")
        self.assertNotIn("WARN", self.cfg("check"))
        self.write(OLD.replace("  draft: false", "  draft: false\n  required_checks: ['flutter (core)']"))
        self.assertIn("pr.required_checks.0", self.cfg("check", code=1))  # the spawn guard refuses parentheses

    def test_a_run_ci_target_never_prints_without_verify(self):
        self.write(OLD.replace("    run: critical\n", "    run: ci\n"))
        for flags in ((), ("--critical",), ("--full",), ("--critical", "--full", "--final")):
            self.assertNotIn("e2e", self.cfg("targets", *flags, "--paths", "app/lib/foo.dart"), flags)
            self.assertNotIn("e2e", self.cfg("targets", *flags), flags)
        self.assertNotIn("e2e", self.cfg("targets", "--full", "--verify"))  # not even /tempo:verify runs it

    def test_the_machine_override_merges_last_and_its_absence_changes_nothing(self):
        before = self.cfg("resolve")
        local = self.repo / ".tempo" / "config.local.yaml"
        local.write_text("limits:\n  max_parallel_builders: 1\ncommands:\n  test_one: cd {package} && flutter test -j 2 {tests}\n")
        out = self.cfg("check")
        self.assertTrue(out.rstrip().endswith(str(local)), out)
        self.assertNotIn("WARN", out)
        self.assertEqual(self.cfg("cmd", "test_one"), "cd {package} && flutter test -j 2 {tests}\n")
        self.assertIn('"max_parallel_builders": 1', self.cfg("resolve"))
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(git + ["commit", "-qm", "x"], check=True)
        wt = self.tmp / "wt"
        subprocess.run(git + ["worktree", "add", "-q", "--detach", str(wt)], check=True)
        (wt / ".tempo").mkdir()
        (wt / ".tempo" / "config.yaml").write_text(OLD)
        self.assertIn("-j 2", self.cfg("--repo", wt, "cmd", "test_one"))  # a linked worktree uses the main checkout's
        subprocess.run(git + ["add", "-f", ".tempo/config.local.yaml"], check=True)
        self.assertIn("is committed", self.cfg("check"))
        local.write_text("limits:\n  max_parallel_builders: 0\n")
        self.assertIn("max_parallel_builders", self.cfg("check", code=1))
        local.unlink()
        self.assertEqual(self.cfg("resolve"), before)

    def test_sync_merged_is_a_tracker_event(self):
        self.write(OLD.split("task:")[0] + TRACKERS.replace("sync: {pr: In review}", "sync: {pr: In review, merged: Done}"))
        self.assertNotIn("WARN", self.cfg("check"))
        self.assertEqual(self.cfg("sync", "merged", "--text", "POD-3"), "SYNC: OFF (jira POD-3: nothing set for merged)\n")
        self.assertEqual(self.cfg("sync", "merged", "--text", "#215"),
                         "WARN: 215 not moved: sync.project names no GitHub Projects board\n")


TRACKERS = """\
task:
  trackers:
    - type: jira
      ticket_pattern: "\\\\b(POD-\\\\d+)\\\\b"
      sync: {assign: true, start: In Progress}
    - type: github
      ticket_pattern: "(?:#|/issues/)(\\\\d+)"
      sync: {pr: In review}
"""


if __name__ == "__main__":
    unittest.main()
