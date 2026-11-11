"""Tests for tempo_procs.py: who owns a process, the config helper, and what a session's end marks as stopped.

Run: python3 -m unittest discover -s <plugin>/tests -v
The process table is a fake one and the cache a temp folder: no real session or process is touched.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tempo_procs  # noqa: E402


def proc(pid, ppid, command, env=""):
    return {"pid": pid, "ppid": ppid, "pgid": pid, "rss_kb": 0, "uid": 0, "age_s": 0, "start": "x", "command": command, "env": env}


class Owner(unittest.TestCase):
    def test_a_claude_ancestor_beats_the_inherited_mark(self):
        table = {p["pid"]: p for p in (
            proc(1, 0, "/sbin/launchd"), proc(10, 1, "claude"), proc(20, 10, "/bin/zsh -c tempo_run.py"),
            proc(30, 20, "python3 tempo_run.py --worker x"), proc(40, 30, "node /x/claude-code/cli.js -p go"),
            proc(50, 40, "python3 tempo_state.py"), proc(60, 1, "python3 tempo_run.py --worker y"), proc(70, 60, "bash -c t"))}
        with mock.patch.dict(os.environ, {"TEMPO_OWNER": "999"}):
            self.assertEqual(tempo_procs.find_owner(table, 30), 10)  # the session above, not the mark
            self.assertEqual(tempo_procs.find_owner(table, 50), 40)  # a session started under a run: the nearest one
            self.assertEqual(tempo_procs.find_owner(table, 70), 999)  # a detached worker: only the mark is left
        with mock.patch.dict(os.environ):
            os.environ.pop("TEMPO_OWNER", None)
            self.assertEqual(tempo_procs.find_owner(table, 70), 0)


class Cfg(unittest.TestCase):
    def test_cfg_runs_the_config_script_with_uv_or_this_python(self):
        done = mock.Mock(stdout="{}")
        for uv, how in (("/bin/uv", ["uv", "run", "--quiet"]), (None, [sys.executable])):
            with mock.patch.object(shutil, "which", return_value=uv), \
                    mock.patch.object(tempo_procs.subprocess, "run", return_value=done) as run:
                self.assertEqual(tempo_procs.cfg(Path("/r"), "resolve", "--format", "json"), "{}")
            self.assertEqual(run.call_args[0][0], [*how, str(tempo_procs.CONFIG), "--repo", "/r", "resolve", "--format", "json"])
            self.assertTrue(run.call_args[1]["check"] and run.call_args[1]["timeout"])
        self.assertTrue(tempo_procs.CONFIG.is_file())


class SessionEnd(unittest.TestCase):
    def test_only_the_ending_session_s_rows_are_marked_stopped(self):
        tmp = Path(tempfile.mkdtemp(prefix="tempo-procs-test-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        d = tmp / "repo" / ".tempo" / "T-001"
        d.mkdir(parents=True)
        tempo_procs.save_ledger(d, [{"label": "mine", "owner": 4242, "stop": "true"}, {"label": "theirs", "owner": 77, "stop": "true"}])
        (tmp / "sessions").mkdir()
        (tmp / "sessions" / "4242.json").write_text(json.dumps([str(d)]))
        table = {1: proc(1, 0, "/sbin/launchd"), 5: proc(5, 1, "sleep 9", "TEMPO_OWNER=77")}
        with mock.patch.object(tempo_procs, "HOME_CACHE", tmp), mock.patch.object(tempo_procs, "SESSIONS", tmp / "sessions"), \
                mock.patch.object(tempo_procs, "snapshot", return_value=table), mock.patch.object(sys, "stdin", io.StringIO("{}")), \
                mock.patch.dict(os.environ, {"TEMPO_OWNER": "4242"}), mock.patch.object(tempo_procs.subprocess, "Popen") as popen:
            self.assertEqual(tempo_procs.session_end(), 0)
        job = Path(popen.call_args[0][0][-1])
        self.assertEqual((job.parent, json.loads(job.read_text())["owner"], json.loads(job.read_text())["pids"]), (tmp, 4242, []))
        tempo_procs.reap_job(job)
        self.assertEqual([(r["label"], "stopped" in r) for r in tempo_procs.load_ledger(d)], [("mine", True), ("theirs", False)])
        self.assertFalse(job.exists())


if __name__ == "__main__":
    unittest.main()
