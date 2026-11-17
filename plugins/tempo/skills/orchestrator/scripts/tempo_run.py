#!/usr/bin/env python3
"""TEMPO run: run one test, build or lint command and print a short summary instead of its output.

Agents run every verification command through this script. The command runs in a
detached worker, so a Bash call never outlives the Bash default timeout or the 3-minute
cap Claude Code puts on commands in async subagents. The call blocks for up to --max seconds. A run that
finishes in time prints its summary; a longer one prints RUNNING and exits 75, and
the agent calls `wait` with the printed ID until the summary comes. Nothing else
polls: no background runs, no sleep loops, no reading of the log to see if it ended.

--heavy takes one of a few machine-wide slots before it starts (default CPUs / 4, at
least 1; env TEMPO_HEAVY_SLOTS or --slots). Use it for whole suites, platform targets
and app builds: too many at once run slower than a queue. The wait happens inside the
worker and is reported as WAITED. Scoped runs (one package, a few test files) do not
take a slot. With --task and a config that can be read, the script decides for the commands
the config knows (decide_heavy): the whole test command and a target's whole command always
take a slot; test-one with test files, typecheck and lint never do. For any other command,
and without --task or a config, the caller's --heavy decides.

Leftovers. Every process a run starts carries TEMPO_RUN=<id> (and the task's
TEMPO_TAG and TEMPO_OWNER, see tempo_procs.py). When the command ends, anything it
left running (a test's emulator, chromedriver, a server it forgot) is stopped and
named in the summary as LEFTOVERS. Build daemons that make the next build faster
(Gradle, Kotlin) stay until the task's teardown; TEMPO_KEEP_DAEMONS sets that
pattern, and an empty value keeps nothing. A long-lived process that should outlive the
command (a dev server, an emulator for QA) is started with `tempo_procs.py start`.

Usage: tempo_run.py [--task DIR] [--heavy] [--slots N] [--label L] [--log-dir DIR] [--tail N]
                    [--timeout SECONDS] [--max SECONDS] -- COMMAND [ARG ...]
       tempo_run.py [--task DIR] wait ID [--max SECONDS]
       tempo_run.py [--task DIR] stop ID
       tempo_run.py --task DIR status
  status prints each run of the task: RUNNING for a live one, the RUN and TREE lines of an ended one.
  stop ends one run: its worker and every process marked with it, nothing else. It is the only way to
  cancel a run. Never pkill or killall: they match by name across the machine, and other tasks share it.
  --task names the task folder (.tempo/<task-id>), so teardown and sweep find what the run left.
  One COMMAND argument runs through bash -c (a command line from `tempo_config.py cmd`);
  several run as an argument list. --max defaults to 110, inside the Bash tool's default 2-minute timeout; 0 blocks until the run ends.
Prints:
  RUN: <label>  EXIT: <code>  TIME: <m:ss>  WAITED: <m:ss>  LOG: <path>
  TREE: <sha> clean|dirty   the git HEAD of the run's folder when it started, and whether the tree had no change
                            (untracked files count); TREE: none outside git
  FAILURES: <count shown>   then up to 40 failure lines, or FAILURES: NIL; only when EXIT is not 0
  TAIL:                     then the last --tail lines (default 25)
  KILLED: signal <n>. ...   first line when the exit is 137 or 143 (SIGKILL, SIGTERM from outside), or the worker died
or, while it runs:
  RUNNING: <label>  ID: <id>  ELAPSED: <m:ss>  STATE: <waiting for a slot | running>
FAILURES are hints matched by pattern; EXIT decides whether the run passed.
QA cites an integrator's run instead of running it again only when its TREE is clean, its sha is QA's HEAD,
it passed and QA's tree is clean too.
--timeout defaults to 3 hours, so a hung run always ends; agents leave it off.
Exit: the command's exit code (128 + n when signal n ended it); 75 while it still runs; 124 when --timeout killed it;
2 on a usage error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempo_os  # noqa: E402
import tempo_procs  # noqa: E402

LOCK_DIR = Path(os.environ.get("TEMPO_LOCK_DIR") or Path.home() / ".cache" / "tempo" / "locks")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FAILURE = re.compile(
    r"\[E\]|\bFAIL(ED|URE)?\b|\bfailed\b|Some tests failed|\bError:|error •|\bERROR\b|Exception|✗|✘|"
    r"Test failed|AssertionError|Expected:|panicked at|BUILD FAILED|exit code [1-9]",
    re.IGNORECASE)
KEEP_DAEMONS = re.compile(os.environ.get("TEMPO_KEEP_DAEMONS", r"GradleDaemon|KotlinCompileDaemon|kotlin-daemon") or "(?!x)x")
NOISE = re.compile(r"^\s*$|^\d+:\d+ \+\d+(?: ~\d+)?: (?:loading|All tests passed)", re.IGNORECASE)


TRAIL = re.compile(r"\s*(2>&1|\|\s*(tail|tee)\b[^|&;]*)\s*$")
EXPORT = re.compile(r"^\s*export\s[^;]*;")  # the env prefix `tempo_config.py cmd` prints
TESTS = r"[^-\s]\S*(?: [^-\s]\S*)*"  # test files only: with an option among them the line may be a target's scoped one


LAUNCHER = re.compile(r"^fvm (exec )?")  # shortcut: one project's launcher; a config key when a second one shows up


def parts(line):
    """The `&&` parts of a shell line, each without a leading `export ...;`, a launcher, or a trailing `2>&1`, `| tail ...`, `| tee ...`."""
    out = []
    for part in (line or "").split("&&"):
        part = EXPORT.sub("", part)
        while TRAIL.search(part):
            part = TRAIL.sub("", part)
        out.append(LAUNCHER.sub("", " ".join(part.split())))
    return out


def last_part(line):
    return parts(line)[-1]


DEFAULT_TIMEOUT = 10800  # 3 hours, /tempo:verify's value


def decide_heavy(cmd, flag, cfg):
    """Whether the run takes a heavy slot: yes for the config's whole suites, no for its scoped or cheap commands, else `flag`."""
    every = parts(cmd[0] if len(cmd) == 1 else " ".join(cmd))
    part = every[-1]
    c = cfg.get("commands") or {}
    # any part: a whole suite chained in front of a lint still needs its slot
    if set(every) & {last_part(x) for x in [c.get("test")] + [t.get("command") for t in cfg.get("targets") or []] if x}:
        return True
    one = re.split(r"(\{[a-z_]+\})", last_part(c.get("test_one")))  # placeholders land on the odd indexes
    rx = "".join((TESTS if x == "{tests}" else r"\S+") if i % 2 else re.escape(x) for i, x in enumerate(one))
    if "{tests}" in one and re.fullmatch(rx, part):
        return False
    if part in {last_part(c[k]) for k in ("typecheck", "lint") if c.get(k)}:
        return False
    return flag


def tree(cwd):
    """(HEAD sha, clean) of the git tree at cwd, or (None, None) outside git. Untracked files make it dirty."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=30)
        if head.returncode:
            return None, None
        # the task folder is TEMPO's own; no lock, so a parallel agent's git add never fails on index.lock
        st = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--", ":/", ":(top,exclude).tempo"],
                            cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        return head.stdout.strip(), st.returncode == 0 and not st.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, None


def tree_line(opts):
    return f"TREE: {opts['head']} {'clean' if opts.get('clean') else 'dirty'}" if opts.get("head") else "TREE: none"


def killed_line(sig):
    return f"KILLED: signal {sig}. Stopped from outside, not a test failure. Run it again once."


def run_end(run, opts, code, seconds, waited=0.0, killed=False, leftovers=0):
    """One line in the task's events.jsonl for a run that ended, with the machine's load, to see what queues and what dies."""
    if not opts.get("task"):
        return
    try:
        load = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):  # Windows has no load average
        load = None
    tempo_procs.event(opts["task"], ev="run-end", id=run.name, exit=code, seconds=round(seconds), waited=round(waited),
                      load1=load, killed=killed, leftovers=leftovers, head=opts.get("head"), clean=opts.get("clean"))


def clock(seconds):
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def take_slot(slots, label):
    """Hold one of `slots` lock files; return (file, seconds waited, who held it when we started waiting)."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    start, holder = time.monotonic(), None
    while True:
        for i in range(slots):
            f = open(LOCK_DIR / f"heavy-{i}.lock", "a+", encoding="utf-8")
            try:
                tempo_os.lock(f, block=False)
            except OSError:
                if holder is None:
                    f.seek(0)
                    holder = f.read().strip() or "another run"
                f.close()
                continue
            f.seek(0); f.truncate()
            f.write(f"{label} | pid {os.getpid()} | {os.getcwd()} | since {time.strftime('%H:%M:%S')}\n")
            f.flush()
            return f, time.monotonic() - start, holder
        time.sleep(2)


def clean(line):
    line = ANSI.sub("", line.rstrip("\n"))
    return line.split("\r")[-1]  # progress lines rewrite themselves with \r: keep the last state


def summary(log, tail):
    lines = [clean(x) for x in log.read_text(encoding="utf-8", errors="replace").splitlines()]
    lines = [x for x in lines if not NOISE.match(x)]
    seen, fails = set(), []
    for x in lines:
        if FAILURE.search(x) and x not in seen:
            seen.add(x); fails.append(x[:300])
    return fails[:40], len(fails), [x[:300] for x in lines[-tail:]]


def default_slots():
    return int(os.environ.get("TEMPO_HEAVY_SLOTS") or max(1, (os.cpu_count() or 4) // 4))


def worker(run, opts, cmd):
    """Runs in its own session: takes the slot, runs the command, writes result.txt, then exit."""
    (run / "state").write_text("waiting for a slot" if opts["heavy"] else "running", encoding="utf-8")
    lock, waited, holder = (None, 0.0, None)
    if opts["heavy"]:
        lock, waited, holder = take_slot(max(1, opts["slots"]), opts["label"])
    (run / "state").write_text("running", encoding="utf-8")
    start = time.monotonic()
    log, code = Path(opts["log"]), 0
    try:
        with open(log, "w", encoding="utf-8") as out:
            args = (tempo_os.shell(cmd[0]) if len(cmd) == 1 else cmd)
            proc = tempo_os.spawn(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=opts["cwd"])
            try:
                code = proc.wait(timeout=opts["timeout"])
            except subprocess.TimeoutExpired:
                tempo_os.kill(proc.pid, group=True)
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    tempo_os.kill(proc.pid, force=True, group=True); proc.wait()
                out.write(f"\ntempo_run: killed after {opts['timeout']} s\n")
                code = 124
    finally:
        if lock:
            lock.seek(0); lock.truncate(); lock.close()
    took = time.monotonic() - start
    if tempo_os.WINDOWS and code > 255 and not code & 0xFF:
        code = -(code >> 8)  # Git Bash exits with signal n << 8 when a signal kills it
    if code < 0:
        code = 128 - code  # died from a signal: the code a shell reports
    killed = code in (137, 143) and not (run / "stopped").exists()
    stopped, kept = reap_leftovers(run.name, locals().get("proc"))

    fails, total, tail = summary(log, opts["tail"])
    rows = [f"RUN: {opts['label']}  EXIT: {code}  TIME: {clock(took)}  WAITED: {clock(waited)}  LOG: {log.as_posix()}",
            tree_line(opts)]
    if killed:
        rows.insert(0, killed_line(code - 128))
    if waited >= 1 and holder:
        rows.append(f"WAITED FOR: {holder}")
    # on exit 0 the failure patterns are noise (a test named "failed", a logged Exception) and mislead agents
    if code and fails:
        rows.append(f"FAILURES: {len(fails)}" + (f" of {total} (see the log for the rest)" if total > len(fails) else ""))
        rows += fails
    elif code:
        rows.append("FAILURES: NIL")
    if stopped:
        rows.append(f"LEFTOVERS: stopped {len(stopped)} the command left running: " + "; ".join(stopped)[:400])
    if kept:
        rows.append(f"KEPT: {len(kept)} build daemon(s) until the task's teardown")
    rows.append("TAIL:")
    rows += tail
    tmp = run / "result.tmp"
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    (run / "code").write_text(str(code), encoding="utf-8")
    run_end(run, opts, code, took, waited, killed, len(stopped))
    tempo_os.replace(tmp, run / "result.txt")  # last: its presence means the run is over


def reap_leftovers(run_id, proc):
    """Stop what the command left running: processes marked with this run, or in its process group."""
    try:
        table = tempo_procs.snapshot()
        mine = tempo_procs.protected(table)
        group = proc.pid if proc is not None else None
        hits = [p for p in table.values() if p["pid"] not in mine and
                (tempo_procs.marks(p)["run"] == run_id or (group and group in (p["pgid"], p["ppid"] if tempo_os.WINDOWS else None)))]
        kept = [p for p in hits if KEEP_DAEMONS.search(p["command"])]
        gone = [p for p in hits if p not in kept]
        tempo_procs.kill_all([p["pid"] for p in gone], grace=5)
        return [f"{p['command'][:60]} ({tempo_procs.mb(p['rss_kb'])})" for p in gone], kept
    except Exception as e:  # cleanup never fails the run
        return [f"cleanup error: {e}"], []


def wait(run, max_seconds):
    """Block up to max_seconds (0: no limit). Print the summary, or RUNNING with exit 75."""
    run = Path(run)
    if not (run / "opts.json").exists():
        print(f"tempo_run: no run at {run}", file=sys.stderr); return 2
    opts = json.loads((run / "opts.json").read_text(encoding="utf-8"))
    end = time.monotonic() + max_seconds if max_seconds else None
    while not (run / "result.txt").exists():
        if end is not None and time.monotonic() >= end:
            # not while `stop` is at work: it writes its own STOPPED summary
            if not alive(opts.get("pid")) and not (run / "result.txt").exists() and not (run / "stopped").exists():
                print(f"tempo_run: the worker for {opts['label']} died; see {opts['log']}", file=sys.stderr)
                stopped, _ = reap_leftovers(run.name, None)  # the command may outlive its worker, and the caller runs it again
                (run / "code").write_text("1", encoding="utf-8")
                run_end(run, opts, 1, time.time() - opts["started"], killed=True, leftovers=len(stopped))
                # written down, so the next wait prints the same and the event is logged once
                (run / "result.txt").write_text(f"{killed_line('unknown')}\nRUN: {opts['label']}  EXIT: 1  WORKER DIED  LOG: {opts['log']}\n{tree_line(opts)}\n", encoding="utf-8")
                continue
            state = (run / "state").read_text(encoding="utf-8") if (run / "state").exists() else "starting"
            print(f"RUNNING: {opts['label']}  ID: {Path(run).as_posix()}  ELAPSED: {clock(time.time() - opts['started'])}  STATE: {state}")
            return 75
        time.sleep(1)
    print((run / "result.txt").read_text(encoding="utf-8"), end="")
    return int((run / "code").read_text(encoding="utf-8"))


def stop(run):
    """Cancel one run: its worker and what it started. `wait` then prints the STOPPED summary."""
    run = Path(run)
    if not (run / "opts.json").exists():
        print(f"tempo_run: no run at {run}", file=sys.stderr); return 2
    opts = json.loads((run / "opts.json").read_text(encoding="utf-8"))
    if (run / "result.txt").exists():
        print(f"ENDED: {opts['label']} had already ended"); return 0
    (run / "stopped").touch()  # a worker that sees its command die first must not report an outside kill
    table = tempo_procs.snapshot()
    mine = tempo_procs.protected(table)
    # The worker is known by its own command line (a reused PID never matches). The command runs in its own
    # process group under the worker; the mark alone misses system binaries, whose environment macOS hides.
    # by folder name: the same run is /var/... to one caller and /private/var/... to another
    worker = [p["pid"] for p in table.values() if "--worker" in p["command"] and run.name in p["command"]]
    groups = {p["pgid"] for p in table.values() if p["ppid"] in worker}
    pids = [p["pid"] for p in table.values() if p["pid"] not in mine and
            (p["pid"] in worker or p["pgid"] in groups or tempo_procs.marks(p)["run"] == run.name)]
    left = tempo_procs.kill_all(pids, grace=5)
    if not (run / "result.txt").exists():  # the worker died before it wrote a summary
        (run / "code").write_text("130", encoding="utf-8")
        (run / "result.txt").write_text(f"RUN: {opts['label']}  EXIT: 130  STOPPED by tempo_run.py stop  LOG: {opts['log']}\n{tree_line(opts)}\n", encoding="utf-8")
        run_end(run, opts, 130, time.time() - opts["started"])
    print(f"STOPPED: {opts['label']}  PROCESSES: {len(pids) - len(left)}" + (f"  STILL ALIVE: {left}" if left else ""))
    return 1 if left else 0


def status(task):
    """Each run the task's events.jsonl names: the RUNNING line, or the RUN and TREE lines of its summary."""
    ev = Path(task) / "events.jsonl"
    rows = ev.read_text(encoding="utf-8", errors="replace").splitlines() if ev.is_file() else []
    runs = [Path(e["dir"]) for e in map(json.loads, rows) if e.get("ev") == "run" and e.get("dir")]
    runs = [r for r in runs if (r / "opts.json").exists()]  # the OS may have cleaned old run folders
    for run in runs:
        if (run / "result.txt").exists():
            print("\n".join(x for x in (run / "result.txt").read_text(encoding="utf-8").splitlines()
                            if x.startswith(("RUN:", "TREE:", "KILLED:"))))
        elif not (o := json.loads((run / "opts.json").read_text(encoding="utf-8"))).get("pid"):
            print(f"RUNNING: {o['label']}  ID: {run.as_posix()}  STATE: starting")  # no worker yet: never call it dead
        else:
            wait(run, 0.01)  # prints RUNNING, or reports a dead worker once
    if not runs:
        print("RUNS: NIL")
    return 0


def alive(pid):
    return tempo_os.alive(pid)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    task = None
    if argv[:1] == ["--task"] and len(argv) > 1:
        task, argv = argv[1], argv[2:]
    if argv[:1] == ["--worker"]:
        run = Path(argv[1])
        opts = json.loads((run / "opts.json").read_text(encoding="utf-8"))
        worker(run, opts, opts["cmd"])
        return 0
    if argv[:1] == ["wait"]:
        p = argparse.ArgumentParser(prog="tempo_run.py wait")
        p.add_argument("id")
        p.add_argument("--max", type=int, default=110)
        a = p.parse_args(argv[1:])
        return wait(a.id, a.max)
    if argv[:1] == ["stop"] and len(argv) == 2:
        return stop(argv[1])
    if argv == ["status"] and task:
        return status(task)
    p = argparse.ArgumentParser(prog="tempo_run.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--heavy", action="store_true", help="take a machine-wide slot first")
    p.add_argument("--task", help="the task folder, .tempo/<task-id>")
    p.add_argument("--slots", type=int, default=default_slots())
    p.add_argument("--label", help="a few words naming the run (default: the command)")
    p.add_argument("--log-dir", help="folder for the log (default: a new private temp folder)")
    p.add_argument("--tail", type=int, default=25)
    p.add_argument("--timeout", type=int, help=f"seconds before the command is killed (exit 124); default {DEFAULT_TIMEOUT}")
    p.add_argument("--max", type=int, default=110, help="seconds this call blocks; 0: until the run ends")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        p.print_usage(sys.stderr); return 2
    task = task or a.task
    heavy = a.heavy
    if task:
        try:
            cfg = json.loads(tempo_procs.cfg(Path(task).resolve().parent.parent, "resolve", "--format", "json"))
            heavy = decide_heavy(cmd, a.heavy, cfg["config"])
        except Exception:  # no config, or tempo_config.py cannot run here: the caller's flag decides, as before
            pass
    # a hung run ends on its own; the default clears a whole suite or package folder several times over under load
    a.timeout = a.timeout or DEFAULT_TIMEOUT
    label = a.label or " ".join(cmd)[:80]
    run = Path(tempfile.mkdtemp(prefix="tempo-run-"))
    log_dir = Path(a.log_dir) if a.log_dir else run
    log_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40] or "run"
    log = log_dir.resolve() / f"{time.strftime('%H%M%S')}-{slug}.log"
    head, tidy = tree(os.getcwd())
    opts = {"label": label, "log": log.as_posix(), "heavy": heavy, "slots": a.slots, "tail": a.tail,
            "timeout": a.timeout, "cmd": cmd, "cwd": os.getcwd(), "started": time.time(),
            "task": os.path.abspath(task) if task else None, "head": head, "clean": tidy}
    (run / "opts.json").write_text(json.dumps(opts), encoding="utf-8")
    owner = tempo_procs.find_owner()
    if task:
        tempo_procs.register(task, owner)
        tempo_procs.event(task, ev="run", id=run.name, dir=str(run), label=label, heavy=heavy)
    env = tempo_procs.task_env(task, owner, run=run.name)
    w = tempo_os.spawn([sys.executable, os.path.abspath(__file__), "--worker", str(run)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, env=env,
                       stderr=open(run / "worker.err", "w", encoding="utf-8"))
    opts["pid"] = w.pid
    (run / "opts.json").write_text(json.dumps(opts), encoding="utf-8")
    return wait(run, a.max)


if __name__ == "__main__":
    sys.exit(main())
