#!/usr/bin/env python3
"""TEMPO processes: start, track and tear down what a task runs, and sweep for leftovers.

A dev server, emulator, simulator, watcher or container that an agent starts with
nohup, `&` or setsid outlives the agent and the session. On 2026-10-30 a headless
Android emulator (8.3 GB, 17 h), five Java services (3 GB) and two `nest --watch`
processes (1.9 GB, 42 h) pushed a Mac to 11 GB of swap. This script makes every
process TEMPO starts findable, and stops exactly those, never anything else.

How a process is marked. Every process `start` and tempo_run.py launch carries
three environment variables, which every child inherits, even one a helper script
starts with nohup or that re-parents to launchd:
  TEMPO_TAG    12 hex digits naming the task folder (see `tag`); the registry in
               ~/.cache/tempo/tasks/<tag>.json maps it back to the folder
  TEMPO_OWNER  PID of the Claude Code process the task runs in (0 when unknown)
  TEMPO_SVC    the label, for processes `start` launched (long-lived services)
  TEMPO_RUN    the run ID, for processes tempo_run.py launched (finite commands)
Each `start` also writes an entry in <task>/procs.json (the ledger): PID, process
group, start time, command, log and an optional --stop command (for things that run
outside the process tree, such as a docker compose stack). The environment is read
from /proc on Linux and `ps -E` on macOS; where it cannot be read, the ledger's
process groups still find what `start` launched. Native Windows exposes no other
process's environment and has no process groups: there the ledger PID or the run's
worker PID is found in a PowerShell process table and taskkill /T stops its tree.

Usage: tempo_procs.py <command> [args]
  start    --task DIR --label L [--stop CMD] [--ready REGEX] [--max S] [--cwd D] -- COMMAND [ARG ...]
           Launch a long-lived process in its own session, record it, return at once. One COMMAND
           argument runs through bash -c. --ready waits up to --max seconds (default 100) for
           REGEX in its log. Prints STARTED|READY|EXITED with PID and LOG.
  adopt    --task DIR --label L [--pid PID] [--stop CMD]
           Record something started another way: a PID (its process group too) or a stop command.
  list     --task DIR                      the ledger and every live process marked with the task
  stop     --task DIR [--label L]          stop the task's services (all, or one label)
  teardown --task DIR [--services-only] [--dry-run]
           Run the ledger's stop commands, then stop every live process marked with the task
           (--services-only: only those `start` launched, so finite runs in flight finish).
           Children of a workspace task or split task (state.json children) are torn down too.
  sweep    [--kill] [--kill-pid PID ...] [--min-age MIN] [--all-users]
           Machine-wide. LEFTOVER: marked processes whose session ended, or whose task is DONE,
           FAILED or ABORTED, or whose folder is gone (services also when the task waits on
           Jorge). IN USE: marked processes of a running task. SUSPECT: unmarked orphans
           (parent PID 1) that look like dev tooling (emulator, java -jar, watchers, dev
           servers, flutter, chromedriver, `tail -f /dev/null`) or whose folder is a .tempo
           worktree or was deleted, older than --min-age (default 30). --kill stops LEFTOVER
           only. A SUSPECT is stopped only by naming its PID with --kill-pid.
  session-end                              SessionEnd hook: stop what this session's tasks started
  reap     PID [PID ...]                   (internal) SIGTERM, wait, then SIGKILL
  owner                                    print the Claude Code PID this shell runs under
  tag      DIR                             print the task's tag
Exit 0 ok, 1 something could not be stopped, 2 usage error.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempo_os  # noqa: E402

HOME_CACHE = Path(os.environ.get("TEMPO_CACHE") or Path.home() / ".cache" / "tempo")
CONFIG = Path(__file__).resolve().parents[2] / "config" / "scripts" / "tempo_config.py"
REGISTRY = HOME_CACHE / "tasks"
SESSIONS = HOME_CACHE / "sessions"
ENDED = {"DONE", "FAILED", "ABORTED"}
TAG_RE = re.compile(r"\bTEMPO_TAG=([0-9a-f]{12})\b")
OWNER_RE = re.compile(r"\bTEMPO_OWNER=(\d+)\b")
SVC_RE = re.compile(r"\bTEMPO_SVC=(\S+)")
RUN_RE = re.compile(r"\bTEMPO_RUN=(\S+)")
CLAUDE_EXE = re.compile(r'(^"?|[/\\])claude(\.exe)?"?$|claude-code|@anthropic-ai[/\\]claude')
# Unmarked orphans that look like dev tooling a session started for testing.
SUSPECT_RE = re.compile(
    r"qemu-system|/emulator(\s|$)|emulator\s+-avd|\bjava\b.*\s-jar\s|spring-boot|bootRun|"
    r"--watch\b|\bnodemon\b|\bvite\b|next(-server|\s+dev)|nest\s+start|webpack(-dev-server|\s+serve)|tsx\s+watch|"
    r"ts-node-dev|flutter_tester|\bflutter\s+(run|drive|test)|frontend_server|dart.*devtools|chromedriver|"
    r"--remote-debugging-port|--user-data-dir=/(tmp|var/folders|private)|tail\s+-f\s+/dev/null|sleep\s+infinity|"
    r"http\.server|uvicorn|gunicorn|xcrun\s+simctl|Simulator\.app|playwright|"
    r"build_runner\s+watch|melos\s+run|npm\s+(run\s+)?(dev|start|serve)|pnpm\s+(run\s+)?(dev|start)|yarn\s+(dev|start)")
# Parents an orphan is handed to: init, launchd, or a container's subreaper.
REAPER_RE = re.compile(r"^(/\S*/)?(init|launchd|tini|dumb-init|systemd)(\s|$)")
# Never suspects: shells, Claude itself, system and editor processes.
NEVER_RE = re.compile(r"^(-?(ba|z|fi)?sh|login|tmux|screen)(\s|$)|claude|/System/|/usr/libexec/|/Applications/(?!.*Simulator)|"
                      r"watchman|ssh-agent|gpg-agent|launchd|Code Helper|Cursor")


# ---------- process table ----------

def _clk():
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        return 100


def _etime(s):
    """ps etime [[dd-]hh:]mm:ss to seconds."""
    days, _, rest = s.rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(days) if days else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


# One tab-separated line per process: pid, ppid, working set bytes, creation time in UTC ticks (0.1 us), command line.
WIN_PS = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | ForEach-Object { "
          "$c = if ($_.CommandLine) { $_.CommandLine -replace '\\s', ' ' } else { $_.Name }; "
          "$t = if ($_.CreationDate) { $_.CreationDate.ToUniversalTime().Ticks } else { 0 }; "
          "\"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.WorkingSetSize)`t$t`t$c\" }")


def _parse_win(text, now):
    """WIN_PS output to snapshot rows. `now` is UTC seconds since year 1.
    shortcut: Windows cannot read another process's environment, so no row carries TEMPO_* marks, and it has
    no process groups, so pgid is the pid itself. Teardown finds what `start` and tempo_run launched by the
    ledger or worker PID and taskkill /T takes the tree; orphans whose parent already exited are missed.
    Upgrade with a named Job Object per task if that bites."""
    out = {}
    for line in text.splitlines():
        f = line.rstrip("\r").split("\t", 4)
        if len(f) < 5 or not f[0].isdigit():
            continue
        pid, ticks = int(f[0]), int(f[3] or 0)
        out[pid] = {"pid": pid, "ppid": int(f[1] or 0), "pgid": pid, "rss_kb": int(f[2] or 0) // 1024,
                    "age_s": max(0, int(now - ticks / 1e7)) if ticks else 0, "start": f[3], "uid": -1,
                    "command": f[4], "env": "", "cwd": None}
    return out


def snapshot(with_cwd=False):
    """Every readable process: pid, ppid, pgid, rss_kb, age_s, start (identity token), uid, command, env text."""
    out = {}
    if tempo_os.WINDOWS:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WIN_PS],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        now = (dt.datetime.now(dt.timezone.utc) - dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)).total_seconds()
        out = _parse_win(r.stdout, now)
        if not out:  # PowerShell missing or blocked: an empty table would read as "nothing running"
            raise RuntimeError(f"tempo_procs: no process table from PowerShell: {r.stderr.strip()[:300]}")
        return out
    if Path("/proc/self/stat").exists():
        clk = _clk()
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            uid = -1
            try:
                stat = (p / "stat").read_text(encoding="utf-8")
                rest = stat[stat.rindex(")") + 2:].split()
                cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
                try:
                    env = (p / "environ").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                except OSError:
                    env = ""
                rss = 0
                for line in (p / "status").read_text(encoding="utf-8").splitlines():
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                    elif line.startswith("Uid:"):
                        uid = int(line.split()[1])
                start = int(rest[19])
                d = {"pid": int(p.name), "ppid": int(rest[1]), "pgid": int(rest[2]), "rss_kb": rss,
                     "age_s": max(0, int(uptime - start / clk)), "start": str(start), "uid": uid,
                     "command": cmd or stat[stat.index("(") + 1:stat.rindex(")")], "env": env}
                if with_cwd:
                    try:
                        d["cwd"] = os.readlink(p / "cwd")
                    except OSError:
                        d["cwd"] = None
                out[d["pid"]] = d
            except (OSError, ValueError, IndexError):
                continue
        return out
    # macOS / BSD
    fmt = "pid=,ppid=,pgid=,rss=,uid=,etime=,lstart=,command="
    base = subprocess.run(["ps", "-axww", "-o", fmt], capture_output=True, text=True).stdout
    envs = subprocess.run(["ps", "-axww", "-E", "-o", "pid=,command="], capture_output=True, text=True).stdout
    env_by = {}
    for line in envs.splitlines():
        f = line.split(None, 1)
        if len(f) == 2 and f[0].isdigit():
            env_by[int(f[0])] = f[1]
    for line in base.splitlines():
        f = line.split()
        if len(f) < 12 or not f[0].isdigit():
            continue
        pid = int(f[0])
        cmd = " ".join(f[11:])
        out[pid] = {"pid": pid, "ppid": int(f[1]), "pgid": int(f[2]), "rss_kb": int(f[3]), "uid": int(f[4]),
                    "age_s": _etime(f[5]), "start": " ".join(f[6:11]), "command": cmd,
                    "env": env_by.get(pid, "")}
    if with_cwd and out:
        cw = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn", "-u", str(os.getuid())],
                            capture_output=True, text=True).stdout
        pid = None
        for line in cw.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid in out:
                out[pid]["cwd"] = line[1:]
    return out


def marks(p):
    e = p.get("env") or ""
    g = lambda r: (r.search(e).group(1) if r.search(e) else None)
    return {"tag": g(TAG_RE), "owner": int(g(OWNER_RE) or 0), "svc": g(SVC_RE), "run": g(RUN_RE)}


def alive(pid, start=None, table=None):
    if table is not None:
        p = table.get(int(pid))
        return bool(p) and (start is None or p["start"] == start)
    return tempo_os.alive(pid)


def ancestors(pid, table):
    seen = []
    while pid and pid in table and pid not in seen:
        seen.append(pid)
        pid = table[pid]["ppid"]
    return seen


def find_owner(table=None, pid=None):
    """PID of the nearest Claude Code process above `pid` (default: this process), or 0."""
    table = table or snapshot()
    for a in ancestors(pid or os.getpid(), table)[1:]:
        if is_claude(a, table):
            return a
    # The inherited mark counts only here (a detached worker): a session started under a marked process is its own owner.
    mark = os.environ.get("TEMPO_OWNER", "")
    return int(mark) if mark.isdigit() else 0


def is_claude(pid, table):
    """True when the process runs Claude Code: `claude ...`, or `node .../claude-code/cli.js ...`."""
    p = table.get(pid)
    return bool(p) and any(CLAUDE_EXE.search(w) for w in re.findall(r'"[^"]*"|\S+', p["command"])[:2])


# ---------- tags, registry, ledger ----------

def tag(task_dir):
    return hashlib.sha1(str(Path(task_dir).resolve()).encode()).hexdigest()[:12]


def register(task_dir, owner=0):
    """Map the tag back to the folder, and the owning session to its tasks. Cheap; called often."""
    d = Path(task_dir).resolve()
    try:
        REGISTRY.mkdir(parents=True, exist_ok=True)
        _write(REGISTRY / f"{tag(d)}.json", json.dumps({"dir": str(d), "task": d.name}))
        if owner:
            SESSIONS.mkdir(parents=True, exist_ok=True)
            f = SESSIONS / f"{owner}.json"
            try:
                cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
            except ValueError:
                cur = []  # an older, non-atomic writer left it half written
            if str(d) not in cur:
                _write(f, json.dumps(cur + [str(d)]))
    except OSError:
        pass


def _write(path, text):
    """Write via a temp file and rename, so a parallel reader never sees a half-written file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tempo_os.replace(tmp, path)


def event(task_dir, **fields):
    """Append one line to <task>/events.jsonl, the dashboard's history. Never raises, never creates the folder."""
    try:
        if Path(task_dir).is_dir():
            at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            line = json.dumps({"at": at, **fields}, ensure_ascii=False) + "\n"
            with open(Path(task_dir) / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(line)  # one write: lines from parallel commands never interleave
    except Exception:
        pass


def cfg(repo, *args):
    """Run tempo_config.py for `repo` and return what it prints. Raises when it fails or takes over 60 s."""
    how = ["uv", "run", "--quiet"] if shutil.which("uv") else [sys.executable]
    return subprocess.run([*how, str(CONFIG), "--repo", str(repo), *map(str, args)], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60, check=True).stdout


def registry():
    out = {}
    for f in (REGISTRY.glob("*.json") if REGISTRY.exists() else []):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))["dir"]
        except (OSError, ValueError, KeyError):
            continue
    return out


def task_env(task_dir, owner=None, **extra):
    env = dict(os.environ)
    env["TEMPO_TAG"] = tag(task_dir) if task_dir else env.get("TEMPO_TAG", "")
    env["TEMPO_OWNER"] = str(find_owner() if owner is None else owner)
    for k, v in extra.items():
        env[f"TEMPO_{k.upper()}"] = str(v)
    return {k: v for k, v in env.items() if v != ""}


def ledger_path(d):
    return Path(d) / "procs.json"


def load_ledger(d):
    try:
        return json.loads(ledger_path(d).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_ledger(d, rows):
    tmp = ledger_path(d).with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tempo_os.replace(tmp, ledger_path(d))


def task_status(d):
    try:
        s = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
        return s.get("status") or "RUNNING", s
    except (OSError, ValueError):
        return ("GONE" if not Path(d).exists() else "UNKNOWN"), {}


# ---------- stopping ----------

def mb(kb):
    return f"{kb / 1024:.0f} MB"


def describe(p):
    return f"pid {p['pid']}  {mb(p['rss_kb'])}  up {p['age_s'] // 3600}h{p['age_s'] % 3600 // 60:02d}m  {p['command'][:110]}"


def kill_all(pids, grace=10):
    """SIGTERM, wait up to `grace` s, then SIGKILL. Returns the PIDs still alive after that."""
    pids = [p for p in set(pids) if p not in (os.getpid(), os.getppid())]
    for p in pids:
        tempo_os.kill(p)
    end = time.monotonic() + grace
    while time.monotonic() < end and any(alive(p) for p in pids):
        time.sleep(0.2)
    left = [p for p in pids if alive(p)]
    for p in left:
        tempo_os.kill(p, force=True)
    time.sleep(0.3)
    return [p for p in left if alive(p) and not _zombie(p)]


def _zombie(pid):
    if tempo_os.WINDOWS:
        return False  # an exited process leaves no entry behind
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] == "Z"
    except (OSError, IndexError):
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return out.startswith("Z") or not out


def protected(table):
    """This process, its ancestors (the shell, Claude Code) are never stopped."""
    return set(ancestors(os.getpid(), table))


def run_stop_cmd(row):
    if not row.get("stop"):
        return None
    try:
        r = subprocess.run(tempo_os.shell(row["stop"]), cwd=row.get("cwd") or None, capture_output=True,
                           text=True, timeout=90)
        return f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return "timed out after 90 s"


def task_targets(d, table, services_only=False, label=None):
    """Live processes that belong to task folder `d`: marked with its tag, or in a ledger process group."""
    t = tag(d)
    rows = load_ledger(d)
    groups = {r["pgid"]: r for r in rows if r.get("pgid") and not r.get("stopped")
              and (label is None or r["label"] == label)}
    keep = protected(table)
    out = {}
    for p in table.values():
        if p["pid"] in keep:
            continue
        m = marks(p)
        if m["tag"] == t:
            if services_only and not m["svc"]:
                continue
            if label is not None and m["svc"] != label:
                continue
            out[p["pid"]] = p
        elif p["pgid"] in groups:
            r = groups[p["pgid"]]
            if p["age_s"] <= time.time() - r.get("started_at", 0) + 5:
                out[p["pid"]] = p  # started after the entry: not an older process that reused the group id
    return out


def children_of(d):
    _, s = task_status(d)
    return [c["folder"] for c in (s.get("children") or {}).values() if c.get("folder")]


def teardown(d, services_only=False, dry_run=False, label=None, quiet=False):
    d = Path(d).resolve()
    lines, bad = [], 0
    for c in ([] if label else children_of(d)):
        cl, cb = teardown(c, services_only, dry_run, quiet=True)
        lines += cl; bad += cb
    rows = load_ledger(d)
    for r in rows:
        if r.get("stopped") or (label is not None and r["label"] != label):
            continue
        if r.get("stop"):
            lines.append(f"{'WOULD RUN' if dry_run else 'RAN'}: {r['label']} stop: {r['stop']}"
                         + ("" if dry_run else f" ({run_stop_cmd(r)})"))
    table = snapshot()
    targets = task_targets(d, table, services_only, label)
    for p in sorted(targets.values(), key=lambda x: -x["rss_kb"]):
        lines.append(f"{'WOULD STOP' if dry_run else 'STOPPED'}: {d.name} {marks(p)['svc'] or 'run'}  {describe(p)}")
    if not dry_run:
        left = kill_all(list(targets))
        for pid in left:
            lines.append(f"FAILED: pid {pid} still running after SIGKILL")
        bad += len(left)
        now = time.time()
        for r in rows:
            if not r.get("stopped") and (label is None or r["label"] == label):
                r["stopped"] = now
        if rows:
            save_ledger(d, rows)
        if targets or any(l.startswith("RAN") for l in lines):
            with open(d / "procs.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} teardown{' services' if services_only else ''}\n"
                        + "".join(f"  {l}\n" for l in lines))
    if not lines and not quiet:
        lines.append(f"TEARDOWN: {d.name} nothing running")
    return lines, bad


# ---------- start ----------

def start(a):
    d = Path(a.task).resolve()
    d.mkdir(parents=True, exist_ok=True)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        print("tempo_procs: start needs a command after --", file=sys.stderr); return 2
    owner = find_owner()
    register(d, owner)
    logs = d / "procs"; logs.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", a.label).strip("-")[:40] or "proc"
    log = logs / f"{slug}.log"
    args = tempo_os.shell(cmd[0]) if len(cmd) == 1 else cmd
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start: {' '.join(cmd)}\n"); out.flush()
        since = out.tell()  # the log is appended to: the ready line must come from this start
        proc = tempo_os.spawn(args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              cwd=a.cwd or os.getcwd(), env=task_env(d, owner, svc=slug))
    time.sleep(0.2)
    table = snapshot()
    row = {"label": slug, "pid": proc.pid, "pgid": proc.pid, "start": (table.get(proc.pid) or {}).get("start"),
           "started_at": time.time(), "command": " ".join(cmd), "cwd": a.cwd or os.getcwd(), "stop": a.stop,
           "log": str(log), "owner": owner}
    rows = [r for r in load_ledger(d) if not (r["label"] == slug and r.get("stopped"))]
    save_ledger(d, rows + [row])
    if a.ready:
        rx, end = re.compile(a.ready), time.monotonic() + a.max
        while time.monotonic() < end:
            if rx.search(log.read_bytes()[since:].decode("utf-8", "replace")):
                print(f"READY: {slug}  PID: {proc.pid}  LOG: {log.as_posix()}"); return 0
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        if proc.poll() is not None:
            print(f"EXITED: {slug}  CODE: {proc.returncode}  LOG: {log.as_posix()}"); return 1
        print(f"NOT READY: {slug}  PID: {proc.pid}  after {a.max} s, still running  LOG: {log.as_posix()}"); return 1
    if proc.poll() is not None:
        print(f"EXITED: {slug}  CODE: {proc.returncode}  LOG: {log.as_posix()}"); return 1
    print(f"STARTED: {slug}  PID: {proc.pid}  LOG: {log.as_posix()}\nSTOP: tempo_procs.py stop --task {d.as_posix()} --label {slug}")
    return 0


def adopt(a):
    d = Path(a.task).resolve()
    owner = find_owner(); register(d, owner)
    if not a.pid and not a.stop:
        print("tempo_procs: adopt needs --pid or --stop", file=sys.stderr); return 2
    table = snapshot()
    row = {"label": re.sub(r"[^A-Za-z0-9]+", "-", a.label).strip("-"), "pid": a.pid, "started_at": time.time(),
           "stop": a.stop, "owner": owner, "cwd": os.getcwd(), "command": "adopted"}
    if a.pid:
        p = table.get(a.pid)
        if not p:
            print(f"tempo_procs: no process {a.pid}", file=sys.stderr); return 1
        if p["pid"] in protected(table):
            print("tempo_procs: refusing to adopt this shell or Claude Code", file=sys.stderr); return 2
        row.update(pgid=p["pgid"] if p["pgid"] == p["pid"] else None, start=p["start"], command=p["command"][:300])
    save_ledger(d, load_ledger(d) + [row])
    print(f"ADOPTED: {row['label']}" + (f"  PID: {a.pid}" if a.pid else "") + (f"  STOP: {a.stop}" if a.stop else ""))
    return 0


# ---------- sweep ----------

def sweep(a):
    table = snapshot(with_cwd=True)
    reg, me = registry(), tempo_os.uid()
    keep = protected(table)
    leftover, inuse, suspects = [], [], []
    for p in table.values():
        if p["pid"] in keep or (p.get("uid") != me and not a.all_users):
            continue
        m = marks(p)
        if m["tag"]:
            d = reg.get(m["tag"])
            status, _ = task_status(d) if d else ("UNREGISTERED", {})
            why = None
            if m["owner"] and not is_claude(m["owner"], table):
                why = "its session ended"
            elif status in ENDED or status in ("GONE", "UNREGISTERED"):
                why = f"task {status}"
            elif status == "WAITING-ON-JORGE" and m["svc"]:
                why = "task waits on Jorge"
            (leftover if why else inuse).append((p, Path(d).name if d else m["tag"], why or status))
            continue
        parent = table.get(p["ppid"]) or {}
        orphan = p["ppid"] == 1 or bool(REAPER_RE.search(parent.get("command", ""))) or (tempo_os.WINDOWS and not parent)
        if not orphan or p["age_s"] < a.min_age * 60 or NEVER_RE.search(p["command"]):
            continue
        cwd = p.get("cwd") or ""
        hit = SUSPECT_RE.search(p["command"])
        gone = bool(cwd) and os.path.isabs(cwd) and not os.path.isdir(cwd)
        if hit or "/.tempo/" in cwd or gone:
            suspects.append((p, cwd, "folder deleted" if gone else ".tempo worktree" if "/.tempo/" in cwd else hit.group(0)))
    tot = lambda xs: mb(sum(x[0]["rss_kb"] for x in xs))
    print(f"LEFTOVER: {len(leftover)} ({tot(leftover)})  IN USE: {len(inuse)} ({tot(inuse)})  "
          f"SUSPECT: {len(suspects)} ({tot(suspects)})")
    for p, t, why in sorted(leftover, key=lambda x: -x[0]["rss_kb"]):
        print(f"LEFTOVER: {t} ({why})  {describe(p)}")
    for p, t, why in sorted(inuse, key=lambda x: -x[0]["rss_kb"]):
        print(f"IN USE: {t} ({why})  {describe(p)}")
    for p, cwd, why in sorted(suspects, key=lambda x: -x[0]["rss_kb"]):
        print(f"SUSPECT: {why}  {describe(p)}  cwd {cwd or '?'}")
    bad = 0
    targets = []
    if a.kill:
        targets += [p["pid"] for p, _, _ in leftover]
    if a.kill_pid:
        allowed = {p["pid"] for p, _, _ in leftover + suspects}
        for pid in a.kill_pid:
            if pid in allowed:
                targets.append(pid)
            else:
                print(f"SKIPPED: pid {pid} is not a LEFTOVER or SUSPECT in this sweep"); bad += 1
    if targets:
        left = kill_all(targets)
        print(f"STOPPED: {len(targets) - len(left)}" + (f"  FAILED: {' '.join(map(str, left))}" if left else ""))
        bad += len(left)
    return 1 if bad else 0


# ---------- session end ----------

def session_end():
    """SessionEnd hook: stop every process marked with this session as owner. Never blocks long."""
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    table = snapshot()
    owner = find_owner(table)
    if not owner:
        return 0
    pids = [p["pid"] for p in table.values() if marks(p)["owner"] == owner and p["pid"] not in protected(table)]
    stops = []
    f = SESSIONS / f"{owner}.json"
    try:
        dirs = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        dirs = []
    for d in dirs:
        for r in load_ledger(d):
            if r.get("stop") and not r.get("stopped") and r.get("owner") == owner:
                stops.append(r)
            # the ledger PID too: on Windows no process carries the owner mark
            if tempo_os.WINDOWS and r.get("pid") and not r.get("stopped") and r.get("owner") == owner and alive(r["pid"], r.get("start"), table) \
                    and r["pid"] not in pids and r["pid"] not in protected(table):
                pids.append(r["pid"])
    if pids or stops:
        # Hand the work to a detached reaper: the hook returns at once, the reaper outlives the session.
        job = HOME_CACHE / f"reap-{owner}.json"
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(json.dumps({"pids": pids, "stops": stops, "dirs": dirs, "owner": owner}), encoding="utf-8")
        tempo_os.spawn([sys.executable, os.path.abspath(__file__), "reap-job", str(job)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={k: v for k, v in os.environ.items() if not k.startswith("TEMPO_")})
    try:
        f.unlink()
    except OSError:
        pass
    return 0


def reap_job(path):
    job = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in job["stops"]:
        run_stop_cmd(r)
    kill_all(job["pids"])
    for d in job["dirs"]:
        rows = load_ledger(d)
        if rows:
            for r in rows:
                if r.get("owner") == job.get("owner"):  # another session's services in the same task still run
                    r.setdefault("stopped", time.time())
            try:
                save_ledger(d, rows)
                with open(Path(d) / "procs.log", "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} session ended: stopped {len(job['pids'])} process(es)\n")
            except OSError:
                pass
    Path(path).unlink(missing_ok=True)
    return 0


# ---------- main ----------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["session-end"]:
        return session_end()
    if argv[:1] == ["reap-job"]:
        return reap_job(argv[1])
    p = argparse.ArgumentParser(prog="tempo_procs.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start"); s.add_argument("--task", required=True); s.add_argument("--label", required=True)
    s.add_argument("--stop"); s.add_argument("--ready"); s.add_argument("--max", type=int, default=100)
    s.add_argument("--cwd"); s.add_argument("command", nargs=argparse.REMAINDER)
    ad = sp.add_parser("adopt"); ad.add_argument("--task", required=True); ad.add_argument("--label", required=True)
    ad.add_argument("--pid", type=int); ad.add_argument("--stop")
    ls = sp.add_parser("list"); ls.add_argument("--task", required=True)
    st = sp.add_parser("stop"); st.add_argument("--task", required=True); st.add_argument("--label")
    td = sp.add_parser("teardown"); td.add_argument("--task", required=True)
    td.add_argument("--services-only", action="store_true"); td.add_argument("--dry-run", action="store_true")
    sw = sp.add_parser("sweep"); sw.add_argument("--kill", action="store_true")
    sw.add_argument("--kill-pid", type=int, nargs="*"); sw.add_argument("--min-age", type=int, default=30)
    sw.add_argument("--all-users", action="store_true")
    rp = sp.add_parser("reap"); rp.add_argument("pids", type=int, nargs="+")
    sp.add_parser("owner")
    tg = sp.add_parser("tag"); tg.add_argument("dir")
    a = p.parse_args(argv)
    if a.cmd == "start":
        return start(a)
    if a.cmd == "adopt":
        return adopt(a)
    if a.cmd == "list":
        d = Path(a.task).resolve()
        for r in load_ledger(d):
            print(f"{'STOPPED' if r.get('stopped') else 'LEDGER'}: {r['label']}  pid {r.get('pid')}  "
                  f"{r.get('command', '')[:100]}" + (f"  stop: {r['stop']}" if r.get("stop") else ""))
        for q in task_targets(d, snapshot()).values():
            print(f"LIVE: {marks(q)['svc'] or 'run ' + (marks(q)['run'] or '?')}  {describe(q)}")
        return 0
    if a.cmd in ("stop", "teardown"):
        lines, bad = teardown(a.task, services_only=(a.cmd == "stop" or a.services_only),
                              dry_run=getattr(a, "dry_run", False), label=getattr(a, "label", None))
        print("\n".join(lines))
        return 1 if bad else 0
    if a.cmd == "sweep":
        return sweep(a)
    if a.cmd == "reap":
        left = kill_all(a.pids)
        return 1 if left else 0
    if a.cmd == "owner":
        print(find_owner()); return 0
    if a.cmd == "tag":
        print(tag(a.dir)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
