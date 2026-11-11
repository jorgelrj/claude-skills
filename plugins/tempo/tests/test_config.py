"""Tests for tempo_config.py: a config written for 0.21.0 still passes, and gates.full_bars: verify.

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
                    "TEMPO_LOCK_DIR": str(self.tmp / "locks")}  # HOME stays: uv keeps its packages there
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


if __name__ == "__main__":
    unittest.main()
