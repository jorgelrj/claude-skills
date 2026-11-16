"""Tests for tempo_os.py and the Windows process table: the parts that run on any machine.

Run: python3 -m unittest discover -s <plugin>/tests -v
Locks, kills and detach on Windows itself are only checked on a Windows machine.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tempo_os  # noqa: E402
import tempo_procs  # noqa: E402

HOLD = "import sys, time; sys.path.insert(0, sys.argv[1]); import tempo_os; f = open(sys.argv[2], 'a+'); " \
       "tempo_os.lock(f); print('held', flush=True); time.sleep(30)"


class Primitives(unittest.TestCase):
    def test_a_held_lock_refuses_a_second_holder_and_its_text_stays_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "heavy-0.lock"
            path.write_text("WO-01 | pid 1\n", encoding="utf-8")
            p = subprocess.Popen([sys.executable, "-c", HOLD, str(SCRIPTS), str(path)], stdout=subprocess.PIPE, text=True)
            self.addCleanup(p.wait)
            self.addCleanup(p.kill)
            self.assertEqual(p.stdout.readline().strip(), "held")
            with open(path, "a+", encoding="utf-8") as f:
                with self.assertRaises(OSError):
                    tempo_os.lock(f, block=False)
                f.seek(0)
                self.assertEqual(f.read(), "WO-01 | pid 1\n")
            p.kill(); p.wait()
            with open(path, "a+", encoding="utf-8") as f:
                tempo_os.lock(f, block=False)  # free once the holder is gone

    def test_alive_never_harms_what_it_probes(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        self.assertTrue(tempo_os.alive(p.pid))
        self.assertTrue(tempo_os.alive(p.pid))  # on Windows os.kill(pid, 0) would have ended it
        tempo_os.kill(p.pid, force=True)
        p.wait(10)
        self.assertFalse(tempo_os.alive(p.pid))
        self.assertFalse(tempo_os.alive("x"))


class GitBash(unittest.TestCase):
    def test_finds_bash_from_each_git_layout_and_never_the_wsl_launcher(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "Git"
            for rel in ("bin/bash.exe", "usr/bin/bash.exe", "cmd/git.exe", "mingw64/bin/git.exe"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).touch()
            for git in ("cmd/git.exe", "mingw64/bin/git.exe"):
                with mock.patch.object(tempo_os, "WINDOWS", True), mock.patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": ""}), \
                        mock.patch.object(tempo_os.shutil, "which", lambda n, g=git: str(root / g) if n == "git" else None):
                    self.assertEqual(tempo_os.git_bash(), os.path.join(str(root), "bin", "bash.exe"), git)
            wsl = lambda n: "C:\\Windows\\System32\\bash.exe" if n == "bash" else None
            with mock.patch.object(tempo_os, "WINDOWS", True), mock.patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": ""}), \
                    mock.patch.object(tempo_os.shutil, "which", wsl):
                self.assertIsNone(tempo_os.git_bash())
        if not tempo_os.WINDOWS:
            self.assertEqual(tempo_os.shell("echo hi"), ["bash", "-c", "echo hi"])  # POSIX: as before


class WindowsTable(unittest.TestCase):
    def test_parses_the_powershell_lines(self):
        now = 63_900_000_000.0  # seconds since year 1
        text = ("4\t0\t155648\t0\tSystem\r\n"
                f"812\t4\t52428800\t{int((now - 90) * 1e7)}\t\"C:\\Users\\a b\\.local\\bin\\claude.exe\" --resume\r\n"
                f"900\t812\t2048\t{int((now - 5) * 1e7)}\tpython  tempo_run.py\twith a tab\r\n"
                "garbage line\r\n")
        t = tempo_procs._parse_win(text, now)
        self.assertEqual(sorted(t), [4, 812, 900])
        self.assertEqual((t[812]["ppid"], t[812]["pgid"], t[812]["rss_kb"], t[812]["age_s"]), (4, 812, 51200, 90))
        self.assertEqual(t[900]["command"], "python  tempo_run.py\twith a tab")
        self.assertEqual(t[4]["age_s"], 0)
        self.assertTrue(tempo_procs.is_claude(812, t))
        self.assertEqual(tempo_procs.find_owner(t, 900), 812)

    def test_claude_on_windows_and_posix_but_not_a_mention(self):
        table = {i: {"command": c} for i, c in enumerate([
            "C:\\Users\\x\\.local\\bin\\claude.exe", "\"C:\\Program Files\\nodejs\\node.exe\" C:\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js",
            "/usr/local/bin/claude --resume", "claude", "vim claude.md", "C:\\tools\\claudette.exe"])}
        self.assertEqual([tempo_procs.is_claude(i, table) for i in table], [True, True, True, True, False, False])


@unittest.skipUnless(tempo_os.WINDOWS, "job objects are Windows only")
class WindowsJob(unittest.TestCase):
    def test_kill_reaches_a_grandchild_whose_parent_has_exited(self):
        """Git Bash's fork and exec leave such orphans; taskkill /T cannot see them, the spawn's job can."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "pid"
            mid = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                   f"open({str(f)!r}, 'w').write(str(p.pid))")
            top = f"import subprocess, sys, time; subprocess.run([sys.executable, '-c', {mid!r}]); time.sleep(60)"
            a = tempo_os.spawn([sys.executable, "-c", top])
            for _ in range(100):
                if f.exists() and f.read_text():
                    break
                time.sleep(0.1)
            orphan = int(f.read_text())
            self.assertTrue(tempo_os.alive(orphan))
            tempo_os.kill(a.pid)
            time.sleep(0.5)
            self.assertEqual((tempo_os.alive(a.pid), tempo_os.alive(orphan)), (False, False))


if __name__ == "__main__":
    unittest.main()
