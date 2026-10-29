#!/usr/bin/env python3
"""TEMPO run: run one test, build or lint command and print a short summary instead of its output.

Agents run every verification command through this script, in the foreground, with
the Bash tool's timeout at its maximum. It never goes to the background, so there is
nothing to poll. The full output goes to a private log file; the reply holds the exit
code, the time, the failure lines and the last lines of output.

--heavy takes one of a few machine-wide slots before it starts (default 1, env
TEMPO_HEAVY_SLOTS or --slots). Use it for whole suites, platform targets and app
builds: two of them at once on one machine run slower than one after the other,
and agents used to wait on each other with `pgrep` loops. The wait happens inside
this script and is reported as WAITED. Scoped runs (one package, a few test files)
do not take a slot.

Usage: tempo_run.py [--heavy] [--slots N] [--label L] [--log-dir DIR] [--tail N]
                    [--timeout SECONDS] -- COMMAND [ARG ...]
  One COMMAND argument runs through bash -c (a command line from `tempo_config.py cmd`);
  several run as an argument list.
Prints:
  RUN: <label>  EXIT: <code>  TIME: <m:ss>  WAITED: <m:ss>  LOG: <path>
  FAILURES: <count shown>   then up to 40 failure lines, or FAILURES: NIL
  TAIL:                     then the last --tail lines (default 25)
FAILURES are hints matched by pattern; EXIT decides whether the run passed.
Exit: the command's exit code; 124 when --timeout killed it; 2 on a usage error.
"""
import argparse
import fcntl
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_run.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--heavy", action="store_true", help="take a machine-wide slot first")
    p.add_argument("--slots", type=int, default=int(os.environ.get("TEMPO_HEAVY_SLOTS") or 1))
    p.add_argument("--label", help="a few words naming the run (default: the command)")
    p.add_argument("--log-dir", help="folder for the log (default: a new private temp folder)")
    p.add_argument("--tail", type=int, default=25)
    p.add_argument("--timeout", type=int, help="seconds before the command is killed (exit 124)")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        p.print_usage(sys.stderr); return 2
    label = a.label or " ".join(cmd)[:80]
    log_dir = Path(a.log_dir) if a.log_dir else Path(tempfile.mkdtemp(prefix="tempo-run-"))
    log_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40] or "run"
    log = log_dir / f"{time.strftime('%H%M%S')}-{slug}.log"

    lock, waited, holder = (None, 0.0, None)
    if a.heavy:
        lock, waited, holder = take_slot(max(1, a.slots), label)
    start = time.monotonic()
    code = 0
    try:
        with open(log, "w", encoding="utf-8") as out:
            args = (["bash", "-c", cmd[0]] if len(cmd) == 1 else cmd)
            proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                code = proc.wait(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                out.write(f"\ntempo_run: killed after {a.timeout} s\n")
                code = 124
    finally:
        if lock:
            lock.seek(0); lock.truncate(); lock.close()
    took = time.monotonic() - start

    fails, total, tail = summary(log, a.tail)
    print(f"RUN: {label}  EXIT: {code}  TIME: {clock(took)}  WAITED: {clock(waited)}  LOG: {log}")
    if waited >= 1 and holder:
        print(f"WAITED FOR: {holder}")
    if fails:
        print(f"FAILURES: {len(fails)}" + (f" of {total} (see the log for the rest)" if total > len(fails) else ""))
        print("\n".join(fails))
    else:
        print("FAILURES: NIL")
    print("TAIL:")
    print("\n".join(tail))
    return code


if __name__ == "__main__":
    sys.exit(main())
