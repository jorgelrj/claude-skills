"""Tests for tempo_run.py (the heavy slot it decides, KILLED, run-end events, `stop`) and the kill-by-name guard
in hooks/guard_spawn.py.

Run: python3 -m unittest discover -s <plugin>/tests -v
Everything happens in temp folders, with TEMPO_CACHE pointed at one.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "skills" / "orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tempo_run  # noqa: E402  (in this process: its pure functions, and wait() on a run folder made by hand)

# The command strings of pod1um's .tempo/config.yaml, as `tempo_config.py resolve` prints them.
POD = {"commands": {"test": "cd flutter-client && melos run test",
                    "test_one": "cd {package} && flutter test {tests}",
                    "build": "cd flutter-client && melos run analyze", "typecheck": None,
                    "lint": "cd flutter-client && dart format --output=none --set-exit-if-changed modules/core apps "
                            "&& melos run i18n:check"},
       "targets": [{"name": "web", "command": "cd flutter-client && melos run test:web:full",
                    "scoped_command": "cd {package} && flutter test --platform chrome {tests}", "advisory": True}]}
NPM = {"commands": {"test": "npm test", "test_one": None, "lint": "npm run lint"}, "targets": []}
APP = "cd flutter-client/apps/coach"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tempo-run-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {**os.environ, "TEMPO_CACHE": str(self.tmp / "cache"), "TEMPO_OWNER": "0", "TMPDIR": str(self.tmp),
                    "TEMPO_LOCK_DIR": str(self.tmp / "locks")}

    def run_py(self, path, *args, stdin=None, **env):
        return subprocess.run([sys.executable, str(path), *map(str, args)], capture_output=True, text=True,
                              input=stdin, env={**self.env, **env})


    def task(self, config=None):
        d = self.tmp / "repo" / ".tempo" / "T-001"
        d.mkdir(parents=True)
        if config:
            (d.parent / "config.yaml").write_text(config)
            subprocess.run(["git", "init", "-q", str(self.tmp / "repo")], check=True)  # tempo_config.py reads a git repo's config
        return d

    def events(self, d, ev="run-end"):
        rows = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
        return [e for e in rows if e["ev"] == ev]


class Heavy(Base):
    def test_the_config_decides_the_slot_for_the_commands_it_knows(self):
        always, never, flag = (True, True), (False, False), (False, True)  # the result without and with --heavy
        for cfg, cmd, want in (
                (POD, "cd flutter-client && melos run test", always),
                (POD, 'export FVM_HOME="/x y"; cd flutter-client && melos run test', always),
                (POD, "cd flutter-client && melos run test 2>&1 | tail -40", always),
                (POD, "cd /w/flutter-client && melos run test 2>&1 | tee out.log | tail -5", always),
                (POD, "cd flutter-client && melos run test:web:full", always),
                (POD, "cd flutter-client && fvm exec melos run test", always),  # the launcher agents add
                (POD, f"{APP} && fvm flutter test test/a_test.dart", never),
                (POD, "cd flutter-client && melos run test && melos run analyze", always),  # a suite in front of a cheap tail
                (POD, f"cd flutter-client && melos run test && cd apps/coach && flutter test test/a_test.dart", always),
                (POD, "cd flutter-client && melos run test:web:full && melos run i18n:check", always),
                (POD, f"{APP} && flutter test test/a_test.dart", never),
                (POD, f"{APP} && flutter test test/a_test.dart test/b_test.dart 2>&1 | tail -40", never),
                (POD, f"{APP} && flutter test --platform chrome test/a_test.dart", flag),  # the scoped Chrome line
                (POD, f"{APP} && flutter test", flag),  # a whole package: no test argument
                (POD, POD["commands"]["lint"], never),
                (POD, POD["commands"]["build"], flag),
                (POD, f"{APP} && flutter build web", flag),
                (NPM, "npm test", always),
                (NPM, 'export CI="1"; npm test', always),
                (NPM, "npx jest a.test.ts", flag),
                (NPM, "npm run lint", never),
                ({}, "npm test", flag)):
            got = tuple(tempo_run.decide_heavy([cmd], f, cfg) for f in (False, True))
            self.assertEqual(got, want, cmd)
        self.assertIs(tempo_run.decide_heavy(["npm", "test"], False, NPM), True)  # an argument list, not a shell line

    def test_only_a_task_with_a_readable_config_overrides_the_flag(self):
        d = self.task("version: 1\ncommands:\n  test: echo suite\n  lint: echo lint\n")

        def heavy(*args):
            before = set(self.tmp.glob("tempo-run-*"))
            r = self.run_py(SCRIPTS / "tempo_run.py", *args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (run,) = set(self.tmp.glob("tempo-run-*")) - before
            opts = json.loads((run / "opts.json").read_text())
            timeouts.append(opts["timeout"])
            return opts["heavy"]

        timeouts = []
        self.assertIs(heavy("--heavy", "--", "echo lint"), True)  # no --task: the flag, as before
        self.assertIs(heavy("--timeout", "60", "--", "echo lint"), False)
        self.assertEqual(timeouts, [10800, 60])  # a run with no --timeout still ends, after 3 hours
        self.assertIs(heavy("--", "echo suite"), False)
        (d.parent / "config.yaml").write_text("commands: [")
        self.assertIs(heavy("--task", d, "--heavy", "--", "echo lint"), True)  # a config that cannot be read: the flag
        (d.parent / "config.yaml").write_text("version: 1\ncommands:\n  test: echo suite\n  lint: echo lint\n")
        if not shutil.which("uv"):
            try:
                import jsonschema, yaml  # noqa: F401
            except ImportError:
                self.skipTest("tempo_config.py needs uv, or PyYAML and jsonschema")
        self.assertIs(heavy("--task", d, "--heavy", "--", "echo lint"), False)
        self.assertIs(heavy("--task", d, "--", "echo suite"), True)
        self.assertEqual([e["heavy"] for e in self.events(d, "run")], [True, False, True])


class BeforeRun(Base):
    def repo(self):
        main = self.tmp / "repo"
        git = lambda *a: subprocess.run(["git", "-C", str(main), *a], check=True, capture_output=True)
        main.mkdir()
        git("init", "-q"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        git("worktree", "add", "-q", "--detach", str(self.tmp / "wt"))
        (self.tmp / "wt" / "sub").mkdir()
        return main, self.tmp / "wt"

    def test_steps_run_at_a_worktree_root_and_never_in_the_main_checkout(self):
        main, wt = self.repo()
        steps = ["touch swept", "exit 3"]
        self.assertEqual(tempo_run.before_run(steps, wt / "sub"), ["BEFORE RUN: exit 3: exit 3"])
        self.assertTrue((wt / "swept").exists())
        self.assertEqual(tempo_run.before_run(steps, main), [])
        self.assertFalse((main / "swept").exists())
        self.assertEqual(tempo_run.before_run(steps, self.tmp), [])  # outside git
        self.assertEqual(tempo_run.before_run([], wt), [])

    def test_a_task_run_sweeps_first_and_names_a_failed_step(self):
        main, wt = self.repo()
        if not shutil.which("uv"):
            try:
                import jsonschema, yaml  # noqa: F401
            except ImportError:
                self.skipTest("tempo_config.py needs uv, or PyYAML and jsonschema")
        d = main / ".tempo" / "T-001"
        d.mkdir(parents=True)
        (d.parent / "config.yaml").write_text("version: 1\nworktree:\n  before_run:\n    - rm -f stray\n    - exit 4\n")
        (wt / "stray").write_text("x")
        r = subprocess.run([sys.executable, str(SCRIPTS / "tempo_run.py"), "--task", str(d), "--max", "0", "--",
                            "test ! -e stray"], cwd=wt, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("BEFORE RUN: exit 4: exit 4", r.stdout)
        self.assertIn(" clean", r.stdout)  # TREE is taken after the sweep


class Killed(Base):
    KEYS = {"at", "ev", "id", "exit", "seconds", "waited", "load1", "killed", "leftovers", "head", "clean"}

    def test_a_kill_from_outside_prints_killed_and_every_run_logs_its_end(self):
        d = self.task()
        r = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--label", "dies", "--", "kill -9 $$")
        self.assertEqual(r.returncode, 137, r.stdout + r.stderr)
        first, second = r.stdout.splitlines()[:2]
        self.assertEqual(first, "KILLED: signal 9. Stopped from outside, not a test failure. Run it again once.")
        self.assertTrue(second.startswith("RUN: dies  EXIT: 137  "), second)
        r = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--label", "term", "--", "sh -c 'kill -15 $$'; exit $?")
        self.assertEqual((r.returncode, r.stdout[:18]), (143, "KILLED: signal 15."), r.stdout)
        r = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--label", "fails", "--", "exit 3")
        self.assertEqual((r.returncode, r.stdout[:21]), (3, "RUN: fails  EXIT: 3  "), r.stdout)
        ev = self.events(d)
        self.assertEqual([(e["exit"], e["killed"], e["leftovers"]) for e in ev], [(137, True, 0), (143, True, 0), (3, False, 0)])
        self.assertEqual([set(e) for e in ev], [self.KEYS] * 3)
        self.assertEqual([e["id"] for e in ev], [e["id"] for e in self.events(d, "run")])
        self.assertIsInstance(ev[0]["load1"], type(None) if sys.platform == "win32" else float)  # no load average there

    def run_dir(self, d, cmd, pid=None):
        """A run folder as main() leaves it for the worker."""
        run = self.tmp / "tempo-run-made"
        run.mkdir()
        (run / "opts.json").write_text(json.dumps({
            "label": "made", "log": str(run / "out.log"), "heavy": False, "slots": 1, "tail": 5, "timeout": None,
            "cmd": [cmd], "cwd": str(self.tmp), "started": 0, "task": str(d), "pid": pid}))
        return run

    def test_a_dead_worker_is_reported_as_killed_once_and_its_command_is_stopped(self):
        d = self.task()
        gone = subprocess.Popen(["true"])
        gone.wait()
        run = self.run_dir(d, "true", gone.pid)
        out = io.StringIO()
        with mock.patch.object(tempo_run, "reap_leftovers", return_value=(["orphan (1 MB)"], [])) as reap, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual([tempo_run.wait(run, 1), tempo_run.wait(run, 1)], [1, 1])
        reap.assert_called_once_with(run.name, None)
        first, second = out.getvalue().splitlines()[:2]
        self.assertEqual(first, "KILLED: signal unknown. Stopped from outside, not a test failure. Run it again once.")
        self.assertTrue(second.startswith("RUN: made  EXIT: 1  WORKER DIED  LOG: "), second)
        self.assertEqual(out.getvalue().count("KILLED:"), 2)  # the second wait says the same
        self.assertEqual([(e["id"], e["exit"], e["killed"], e["leftovers"]) for e in self.events(d)], [(run.name, 1, True, 1)])

    def test_a_run_its_own_agent_stopped_is_not_killed(self):
        d = self.task()
        run = self.run_dir(d, "kill -9 $$")
        (run / "stopped").touch()  # what `stop` leaves before it kills; here the worker lives to write the summary
        r = self.run_py(SCRIPTS / "tempo_run.py", "--worker", run)
        self.assertEqual((r.returncode, (run / "code").read_text()), (0, "137"), r.stderr)
        self.assertTrue((run / "result.txt").read_text().startswith("RUN: made  EXIT: 137  "))
        self.assertEqual([(e["exit"], e["killed"]) for e in self.events(d)], [(137, False)])


class Summary(Base):
    def run_in(self, cwd, cmd, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "tempo_run.py"), *map(str, args), "--", cmd], capture_output=True,
                              text=True, env=self.env, cwd=cwd)

    def test_tree_names_the_head_and_whether_the_tree_was_clean(self):
        repo = self.tmp / "git"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo,
                                        check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q"); (repo / "a.txt").write_text("a"); git("add", "."); git("commit", "-qm", "a")
        head = git("rev-parse", "HEAD")
        d = repo / ".tempo" / "T-001"  # the task folder inside the repo, not ignored: TEMPO's own files never dirty it
        d.mkdir(parents=True)
        r = self.run_in(repo, "exit 0", "--task", d)
        self.assertEqual(r.stdout.splitlines()[1], f"TREE: {head} clean", r.stdout)
        self.assertEqual([(e["head"], e["clean"]) for e in self.events(d)], [(head, True)])
        (repo / "sub").mkdir()
        r = self.run_in(repo / "sub", "exit 0")  # a run in a subfolder still sees a change at the top
        self.assertEqual(r.stdout.splitlines()[1], f"TREE: {head} clean", r.stdout)
        (repo / "a.txt").write_text("changed")
        r = self.run_in(repo / "sub", "exit 0")
        self.assertEqual(r.stdout.splitlines()[1], f"TREE: {head} dirty", r.stdout)
        git("checkout", "a.txt")
        (repo / "new.txt").write_text("untracked")  # an untracked file makes the tree dirty
        r = self.run_in(repo, "exit 0")
        self.assertEqual(r.stdout.splitlines()[1], f"TREE: {head} dirty", r.stdout)
        out = self.tmp / "nogit"
        out.mkdir()
        r = self.run_in(out, "exit 0")
        self.assertEqual(r.stdout.splitlines()[1], "TREE: none", r.stdout)

    def test_status_lists_the_task_runs(self):
        d = self.task()
        self.assertEqual(self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "status").stdout, "RUNS: NIL\n")
        self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--label", "quick", "--", "exit 0")
        r = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--label", "slow", "--max", "1", "--", "sleep 5")
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.addCleanup(self.run_py, SCRIPTS / "tempo_run.py", "stop", r.stdout.split("ID: ")[1].split("  ")[0])
        out = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "status").stdout.splitlines()
        self.assertEqual([x.split()[0] for x in out], ["RUN:", "TREE:", "RUNNING:"], out)
        self.assertTrue(out[0].startswith("RUN: quick  EXIT: 0") and out[2].startswith("RUNNING: slow"), out)
        # a run whose worker is not spawned yet (no pid) is starting, not dead
        young = self.tmp / "tempo-run-young"
        young.mkdir()
        (young / "opts.json").write_text(json.dumps({"label": "young", "log": "x", "started": 0, "task": str(d)}))
        with open(Path(d) / "events.jsonl", "a") as f:
            f.write(json.dumps({"ev": "run", "dir": str(young)}) + "\n")
        out = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "status").stdout
        self.assertIn("RUNNING: young  ID: ", out)
        self.assertIn("STATE: starting", out)
        self.assertFalse((young / "result.txt").exists())

    def test_failures_show_only_when_the_run_failed(self):
        line = "echo 'Exception in a log line'; echo 'a test named failed works'; exit"
        ok = self.run_in(self.tmp, f"{line} 0")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertNotIn("FAILURES", ok.stdout)
        self.assertIn("TAIL:", ok.stdout)
        bad = self.run_in(self.tmp, f"{line} 1")
        self.assertEqual(bad.returncode, 1, bad.stderr)
        self.assertIn("FAILURES: 2\nException in a log line\na test named failed works\n", bad.stdout)
        self.assertIn("FAILURES: NIL", self.run_in(self.tmp, "exit 1").stdout)


class Stop(Base):
    @unittest.skipIf(sys.platform == "win32", "uses pgrep; check 6 of the Windows handoff covers stop there")
    def test_stop_ends_only_its_own_run(self):
        mark = f"sleep 3{os.getpid() % 1000:03d}"  # a command line no other test or task uses
        d = self.task()
        runs = []
        for _ in range(2):
            r = self.run_py(SCRIPTS / "tempo_run.py", "--task", d, "--max", "1", "--", mark)
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
        self.assertNotIn("KILLED", w.stdout)  # its own agent stopped it: not a kill from outside
        self.assertEqual([(Path(runs[0]).name, 130, False)], [(e["id"], e["exit"], e["killed"]) for e in self.events(d)])
        after = pgrep()
        self.assertTrue(after and after < before, (before, after))  # its processes are gone, the other run's are alive
        self.assertEqual(self.run_py(SCRIPTS / "tempo_run.py", "wait", runs[1], "--max", "1").returncode, 75)
        self.assertIn("already ended", self.run_py(SCRIPTS / "tempo_run.py", "stop", runs[0]).stdout)
        self.assertEqual(self.run_py(SCRIPTS / "tempo_run.py", "stop", self.tmp / "nope").returncode, 2)


class Guard(Base):
    def hook(self, command, bg=False, **env):
        ti = {"command": command, "run_in_background": bg}
        r = self.run_py(PLUGIN / "hooks" / "guard_spawn.py", stdin=json.dumps({"tool_input": ti}), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_kill_by_name_is_denied_only_in_a_tempo_session(self):
        self.assertEqual(self.hook('pkill -f "flutter_tester"'), "")  # no TEMPO session: the hook does nothing
        task = self.tmp / "repo" / ".tempo" / "T-001"
        task.mkdir(parents=True)
        (task / "state.json").write_text(json.dumps({"status": "RUNNING"}))
        sessions = self.tmp / "cache" / "sessions"
        sessions.mkdir(parents=True)
        # The session the hook sees: the Claude Code process the suite runs under, else the 4242 given below.
        owner = self.run_py(SCRIPTS / "tempo_procs.py", "owner", TEMPO_OWNER="4242").stdout.strip()
        (sessions / f"{owner}.json").write_text(json.dumps([str(task)]))
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
        # the orchestrator's stall watcher (SKILL 2.7.0) is the one background command it allows by name
        for cmd in ("python3 /p/tempo_state.py watch .tempo/T-001 --file /o", 'python3 "C:/My Home/tempo_state.py" watch d --file o',
                    "python3 /p/tempo_ci.py watch --pr 7 --repo /r --max 3600"):
            self.assertEqual(self.hook(cmd, bg=True, TEMPO_OWNER="4242"), "", cmd)
        self.assertIn("deny", self.hook("python3 /p/tempo_state.py log .tempo/T-001", bg=True, TEMPO_OWNER="4242"))
        amp, nh = chr(38), "no" + "hup"  # the watcher's name does not carry a second command or a detach past the guard
        for cmd in (f"python3 /p/tempo_state.py watch d --file o; sleep 99 {amp}", f"python3 /p/tempo_state.py watch d --file o; {nh} x",
                    f"sleep 99 {amp}{amp} python3 /p/tempo_state.py watch d --file o", f"python3 /p/tempo_state.py watch d --file o {amp}",
                    "python3 /p/tempo_ci.py collect --pr 7 --out o", f"python3 /p/tempo_ci.py watch --pr 7; {nh} x"):
            self.assertIn("deny", self.hook(cmd, bg=True, TEMPO_OWNER="4242"), cmd)


if __name__ == "__main__":
    unittest.main()
