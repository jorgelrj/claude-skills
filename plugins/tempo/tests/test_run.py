"""Tests for `tempo_run.py stop` and the kill-by-name guard in hooks/guard_spawn.py.

Run: python3 -m unittest discover -s <plugin>/tests -v
Everything happens in temp folders, with TEMPO_CACHE pointed at one.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "skills" / "orchestrator" / "scripts"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-run-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {**os.environ, "TEMPO_CACHE": str(self.tmp / "cache"), "TEMPO_OWNER": "0", "TMPDIR": str(self.tmp),
                    "TEMPO_LOCK_DIR": str(self.tmp / "locks")}

    def run_py(self, path, *args, stdin=None, **env):
        return subprocess.run([sys.executable, str(path), *map(str, args)], capture_output=True, text=True,
                              input=stdin, env={**self.env, **env})


class Stop(Base):
    def test_stop_ends_only_its_own_run(self):
        mark = f"sleep 3{os.getpid() % 1000:03d}"  # a command line no other test or task uses
        runs = []
        for _ in range(2):
            r = self.run_py(SCRIPTS / "tempo_run.py", "--max", "1", "--", mark)
            self.assertEqual(r.returncode, 75, r.stderr)
            runs.append(r.stdout.split("ID: ")[1].split("  ")[0])
        self.addCleanup(self.run_py, SCRIPTS / "tempo_run.py", "stop", runs[1])
        pgrep = lambda: set(subprocess.run(["pgrep", "-f", mark], capture_output=True, text=True).stdout.split())
        before = pgrep()
        r = self.run_py(SCRIPTS / "tempo_run.py", "stop", runs[0])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("STOPPED:", r.stdout)
        w = self.run_py(SCRIPTS / "tempo_run.py", "wait", runs[0], "--max", "1")
        self.assertEqual(w.returncode, 130, w.stdout)
        self.assertIn("EXIT: 130  STOPPED", w.stdout)
        after = pgrep()
        self.assertTrue(after and after < before, (before, after))  # its processes are gone, the other run's are alive
        self.assertEqual(self.run_py(SCRIPTS / "tempo_run.py", "wait", runs[1], "--max", "1").returncode, 75)
        self.assertIn("already ended", self.run_py(SCRIPTS / "tempo_run.py", "stop", runs[0]).stdout)
        self.assertEqual(self.run_py(SCRIPTS / "tempo_run.py", "stop", self.tmp / "nope").returncode, 2)


class Guard(Base):
    def hook(self, command, **env):
        r = self.run_py(PLUGIN / "hooks" / "guard_spawn.py", stdin=json.dumps({"tool_input": {"command": command}}), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_kill_by_name_is_denied_only_in_a_tempo_session(self):
        self.assertEqual(self.hook('pkill -f "flutter_tester"'), "")  # no TEMPO session: the hook does nothing
        task = self.tmp / "repo" / ".tempo" / "T-001"
        task.mkdir(parents=True)
        (task / "state.json").write_text(json.dumps({"status": "RUNNING"}))
        sessions = self.tmp / "cache" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "4242.json").write_text(json.dumps([str(task)]))
        for cmd in ('cd x && sed -n 1p f; pkill -f "flutter_tester" -n; pkill -f "tempo-run-abc"', "killall node",
                    "pkill -f tempo_run.py", 'kill -9 $(pgrep -f "flutter_tester")', "kill `pgrep node`",
                    "pgrep -f dart | xargs kill -9", "sudo pkill node", "true && killall Simulator",
                    "ps ax | grep x | xargs -n1 pkill -P", "(pkill -f x)", "echo $(pkill -f x)"):
            out = json.loads(self.hook(cmd, TEMPO_OWNER="4242"))["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "deny", cmd)
            self.assertIn("tempo_run.py stop <ID>", out["permissionDecisionReason"])
        for cmd in ("kill 1234", "grep -rn pkill .", "git log --grep killall", "cat notes.md | grep -c pkill", "ls pkill",
                    "git commit -m 'guard: deny pkill and killall'", "pgrep -fl flutter_tester", "kill $PID; pgrep -f x", "echo 'never pkill here'", "grep -rn pkillx .", "TEMPO_ALLOW_KILL=1 pkill -f mine",
                    "python3 tempo_run.py stop /tmp/tempo-run-abc"):
            self.assertEqual(self.hook(cmd, TEMPO_OWNER="4242"), "", cmd)
        out = json.loads(self.hook("nohup sleep 9 &", TEMPO_OWNER="4242"))["hookSpecificOutput"]
        self.assertIn("outlives", out["permissionDecisionReason"])  # the detach guard still answers its own way


if __name__ == "__main__":
    unittest.main()
