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
take a slot.

Usage: tempo_run.py [--heavy] [--slots N] [--label L] [--log-dir DIR] [--tail N]
                    [--timeout SECONDS] [--max SECONDS] -- COMMAND [ARG ...]
       tempo_run.py wait ID [--max SECONDS]
  One COMMAND argument runs through bash -c (a command line from `tempo_config.py cmd`);
  several run as an argument list. --max defaults to 110, inside the Bash tool's default 2-minute timeout; 0 blocks until the run ends.
Prints:
  RUN: <label>  EXIT: <code>  TIME: <m:ss>  WAITED: <m:ss>  LOG: <path>
  FAILURES: <count shown>   then up to 40 failure lines, or FAILURES: NIL
  TAIL:                     then the last --tail lines (default 25)
or, while it runs:
  RUNNING: <label>  ID: <id>  ELAPSED: <m:ss>  STATE: <waiting for a slot | running>
FAILURES are hints matched by pattern; EXIT decides whether the run passed.
Exit: the command's exit code; 75 while it still runs; 124 when --timeout killed it;
2 on a usage error.
"""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LOCK_DIR = Path(os.environ.get("TEMPO_LOCK_DIR") or Path.home() / ".cache" / "tempo" / "locks")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FAILURE = re.compile(
    r"\[E\]|\bFAIL(ED|URE)?\b|\bfailed\b|Some tests failed|\bError:|error •|\bERROR\b|Exception|✗|✘|"
    r"Test failed|AssertionError|Expected:|panicked at|BUILD FAILED|exit code [1-9]",
    re.IGNORECASE)
NOISE = re.compile(r"^\s*$|^\d+:\d+ \+\d+(?: ~\d+)?: (?:loading|All tests passed)", re.IGNORECASE)


def clock(seconds):
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def take_slot(slots, label):
    """Hold one of `slots` lock files; return (file, seconds waited, who held it when we started waiting)."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    start, holder = time.monotonic(), None
    while True:
        for i in range(slots):
            f = open(LOCK_DIR / f"heavy-{i}.lock", "a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
    (run / "state").write_text("waiting for a slot" if opts["heavy"] else "running")
    lock, waited, holder = (None, 0.0, None)
    if opts["heavy"]:
        lock, waited, holder = take_slot(max(1, opts["slots"]), opts["label"])
    (run / "state").write_text("running")
    start = time.monotonic()
    log, code = Path(opts["log"]), 0
    try:
        with open(log, "w", encoding="utf-8") as out:
            args = (["bash", "-c", cmd[0]] if len(cmd) == 1 else cmd)
            proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True, cwd=opts["cwd"])
            try:
                code = proc.wait(timeout=opts["timeout"])
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                out.write(f"\ntempo_run: killed after {opts['timeout']} s\n")
                code = 124
    finally:
        if lock:
            lock.seek(0); lock.truncate(); lock.close()
    took = time.monotonic() - start

    fails, total, tail = summary(log, opts["tail"])
    rows = [f"RUN: {opts['label']}  EXIT: {code}  TIME: {clock(took)}  WAITED: {clock(waited)}  LOG: {log}"]
    if waited >= 1 and holder:
        rows.append(f"WAITED FOR: {holder}")
    if fails:
        rows.append(f"FAILURES: {len(fails)}" + (f" of {total} (see the log for the rest)" if total > len(fails) else ""))
        rows += fails
    else:
        rows.append("FAILURES: NIL")
    rows.append("TAIL:")
    rows += tail
    tmp = run / "result.tmp"
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    (run / "code").write_text(str(code))
    tmp.rename(run / "result.txt")  # last: its presence means the run is over


def wait(run, max_seconds):
    """Block up to max_seconds (0: no limit). Print the summary, or RUNNING with exit 75."""
    run = Path(run)
    if not (run / "opts.json").exists():
        print(f"tempo_run: no run at {run}", file=sys.stderr); return 2
    opts = json.loads((run / "opts.json").read_text())
    end = time.monotonic() + max_seconds if max_seconds else None
    while not (run / "result.txt").exists():
        if end is not None and time.monotonic() >= end:
            if not alive(opts.get("pid")) and not (run / "result.txt").exists():
                print(f"tempo_run: the worker for {opts['label']} died; see {opts['log']}", file=sys.stderr)
                return 1
            state = (run / "state").read_text() if (run / "state").exists() else "starting"
            print(f"RUNNING: {opts['label']}  ID: {run}  ELAPSED: {clock(time.time() - opts['started'])}  STATE: {state}")
            return 75
        time.sleep(1)
    print((run / "result.txt").read_text(encoding="utf-8"), end="")
    return int((run / "code").read_text())


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--worker"]:
        run = Path(argv[1])
        opts = json.loads((run / "opts.json").read_text())
        worker(run, opts, opts["cmd"])
        return 0
    if argv[:1] == ["wait"]:
        p = argparse.ArgumentParser(prog="tempo_run.py wait")
        p.add_argument("id")
        p.add_argument("--max", type=int, default=110)
        a = p.parse_args(argv[1:])
        return wait(a.id, a.max)
    p = argparse.ArgumentParser(prog="tempo_run.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--heavy", action="store_true", help="take a machine-wide slot first")
    p.add_argument("--slots", type=int, default=default_slots())
    p.add_argument("--label", help="a few words naming the run (default: the command)")
    p.add_argument("--log-dir", help="folder for the log (default: a new private temp folder)")
    p.add_argument("--tail", type=int, default=25)
    p.add_argument("--timeout", type=int, help="seconds before the command is killed (exit 124)")
    p.add_argument("--max", type=int, default=110, help="seconds this call blocks; 0: until the run ends")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        p.print_usage(sys.stderr); return 2
    label = a.label or " ".join(cmd)[:80]
    run = Path(tempfile.mkdtemp(prefix="tempo-run-"))
    log_dir = Path(a.log_dir) if a.log_dir else run
    log_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40] or "run"
    log = log_dir.resolve() / f"{time.strftime('%H%M%S')}-{slug}.log"
    opts = {"label": label, "log": str(log), "heavy": a.heavy, "slots": a.slots, "tail": a.tail,
            "timeout": a.timeout, "cmd": cmd, "cwd": os.getcwd(), "started": time.time()}
    (run / "opts.json").write_text(json.dumps(opts))
    w = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--worker", str(run)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=open(run / "worker.err", "w"), start_new_session=True)
    opts["pid"] = w.pid
    (run / "opts.json").write_text(json.dumps(opts))
    return wait(run, a.max)


if __name__ == "__main__":
    sys.exit(main())
